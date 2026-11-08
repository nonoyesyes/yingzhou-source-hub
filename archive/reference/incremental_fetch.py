#!/usr/bin/env python3
"""Version-first source CONFIGURATION fetcher. Never fetch dependencies or media.
Staged bodies/state proposals must not be committed before the publication safety gate.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import base64
import hashlib
import ipaddress
import http.client as http_client
import socket
import ssl
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from read_feed import load_feed

STATE_VERSION = 'source-hub-fetch-state.v1'
MAX_BYTES = 32 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat()


def sha256(b):
    return hashlib.sha256(b).hexdigest()


def blob_sha(b):
    return hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest()


def safe_path(root, value):
    if not isinstance(value, str) or Path(value).is_absolute():
        raise ValueError('invalid_relative_path')
    path = (Path(root).resolve() / value).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError('path_escape')
    return path


def verified(root, record):
    try:
        b = safe_path(root, record['archive_path']).read_bytes()
        return (len(b) == record['byte_count'] and sha256(b) == record['sha256']
                and (not record.get('github_blob_sha') or blob_sha(b) == record['github_blob_sha']))
    except (KeyError, OSError, ValueError, TypeError):
        return False


def github_file(url):
    """Known registry convention: raw owner/repo/<single-component ref>/path.
    Branches containing slashes require an explicit github selector, never guess.
    Query/fragment URLs use HTTP fallback so no URL condition is discarded.
    """
    u = urlsplit(url)
    if u.scheme != 'https' or u.port not in (None, 443) or u.query or u.fragment or u.username or u.password:
        return None
    p = u.path.lstrip('/').split('/')
    if u.hostname == 'raw.githubusercontent.com' and len(p) >= 4:
        owner, repo, ref, *path = p
        if ref == 'refs':
            if len(path) < 3 or path[0] not in ('heads', 'tags'):
                return None
            ref, path = path[1], path[2:]
    elif u.hostname == 'github.com' and len(p) >= 5 and p[2] == 'blob':
        owner, repo, _, ref, *path = p
    else:
        return None
    vals = [unquote(v) for v in [owner, repo, ref, *path]]
    if any(not v or v in ('.', '..') or '/' in v or '\\' in v for v in vals):
        return None
    return {'owner': vals[0], 'repo': vals[1], 'ref': vals[2], 'path': '/'.join(vals[3:])}


def load_state(path):
    if not path or not Path(path).exists():
        return {'schema_version': STATE_VERSION, 'entries': {}}
    state = json.loads(Path(path).read_text('utf-8'))
    if state.get('schema_version') != STATE_VERSION or not isinstance(state.get('entries'), dict):
        raise ValueError('invalid_fetch_state')
    return state


def bootstrap_record(root, source, entry):
    # Bind version evidence to the exact archived bytes and exact original URL.
    if entry and entry.get('url') == source['original_url'] and verified(root, entry):
        return dict(entry)
    snapshots = sorted(source.get('snapshots', []), key=lambda s: s.get('fetch_time') or '', reverse=True)
    for sn in snapshots:
        ev = sn.get('capture_evidence') or {}
        r = {'url': source['original_url'], 'archive_path': sn['path'], 'sha256': sn['sha256'],
             'byte_count': sn['byte_count'], 'github_blob_sha': None, 'etag': None, 'last_modified': None}
        # Blob metadata is used only when the captured URL matches this entry.
        if ev.get('url') == source['original_url']:
            r['github_blob_sha'] = ev.get('github_blob_sha')
        if verified(root, r):
            # Git's blob hash is deterministically derivable from retained bytes.
            # This permits metadata-only first adoption even when prior capture
            # lacked a Git SHA; it does not rewrite historical custody evidence.
            if github_file(source['original_url']):
                r['github_blob_sha'] = blob_sha(safe_path(root, r['archive_path']).read_bytes())
            return r
    return None


class FetchError(Exception):
    pass


class GitHub:
    """gh uses its existing authorized login. Never prints/exports credentials.
    Tree metadata is cached per ref for one run, pinning all sibling paths.
    """
    def __init__(self):
        self.trees = {}

    def api(self, endpoint):
        p = subprocess.run(['gh', 'api', endpoint], capture_output=True, timeout=60)
        if p.returncode:
            match = re.search(rb'HTTP (\d{3})', p.stderr)
            raise FetchError('github_' + (match.group(1).decode() if match else 'request_failed'))
        try:
            return json.loads(p.stdout)
        except ValueError:
            raise FetchError('github_invalid_json')

    def tree(self, owner, repo, ref):
        key = (owner, repo, ref)
        if key not in self.trees:
            endpoint = '/repos/' + quote(owner, safe='') + '/' + quote(repo, safe='') + '/git/trees/' + quote(ref, safe='')
            data = self.api(endpoint)
            if data.get('truncated') or not isinstance(data.get('tree'), list):
                raise FetchError('github_tree_incomplete')
            self.trees[key] = data
        return self.trees[key]

    def metadata(self, selector):
        o, r, ref, path = (selector[k] for k in ('owner', 'repo', 'ref', 'path'))
        parts = path.split('/')
        for i, name in enumerate(parts):
            tree = self.tree(o, r, ref)
            matches = [v for v in tree['tree'] if v['path'] == name]
            if len(matches) != 1:
                raise FetchError('github_path_not_found')
            item = matches[0]
            if i < len(parts)-1:
                if item['type'] != 'tree':
                    raise FetchError('github_not_directory')
                ref = item['sha']
            elif item.get('type') != 'blob' or item.get('mode') not in ('100644', '100755'):
                raise FetchError('github_not_regular_config_file')
        return {'sha': item['sha'], 'size': item.get('size')}

    def body(self, selector, digest):
        endpoint = '/repos/' + quote(selector['owner'], safe='') + '/' + quote(selector['repo'], safe='') + '/git/blobs/' + digest
        data = self.api(endpoint)
        if data.get('encoding') != 'base64':
            raise FetchError('github_unsupported_blob_encoding')
        try:
            b = base64.b64decode(''.join(data['content'].split()), validate=True)
        except (KeyError, ValueError):
            raise FetchError('github_invalid_blob')
        if len(b) > MAX_BYTES or blob_sha(b) != digest or data.get('sha') != digest:
            raise FetchError('github_blob_integrity_failed')
        return b


def public_url(url):
    u = urlsplit(url)
    if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password:
        raise FetchError('unsafe_url')
    if u.hostname.lower() in ('localhost',) or u.hostname.lower().endswith(('.local', '.localhost')):
        raise FetchError('local_url_not_allowed')
    if re.fullmatch(r'[0-9.]+|0[xX][0-9a-fA-F]+', u.hostname):
        try:
            ipaddress.ip_address(u.hostname)
        except ValueError:
            raise FetchError('noncanonical_numeric_host')
    try:
        if not ipaddress.ip_address(u.hostname).is_global:
            raise FetchError('nonpublic_ip_not_allowed')
    except ValueError:
        pass
    return u


def public_addresses(host, port):
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(v[4][0]).is_global for v in addresses):
        raise FetchError('nonpublic_destination_not_allowed')
    return addresses


class HTTP:
    def get(self, url, headers):
        u = public_url(url)
        port = u.port or (443 if u.scheme == 'https' else 80)
        host = u.hostname.encode('idna').decode('ascii')
        addresses = public_addresses(host, port)
        # Pin the connection to the address just checked; do not resolve again,
        # follow redirects, inherit proxies or send credentials.
        family, socktype, proto, _, address = addresses[0]
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(30)
        connection = http_client.HTTPConnection(host, port, timeout=30)
        try:
            sock.connect(address)
            if u.scheme == 'https':
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
            connection.sock = sock
            path = (u.path or '/') + ('?' + u.query if u.query else '')
            connection.request('GET', path, headers={'User-Agent': 'source-hub-config-fetch/1',
                               'Accept-Encoding': 'identity', **headers})
            response = connection.getresponse()
            h = dict(response.getheaders())
            if response.status != 200:
                return response.status, h if response.status == 304 else {}, b''
            body = response.read(MAX_BYTES+1)
            if len(body) > MAX_BYTES:
                raise FetchError('configuration_too_large')
            if response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                raise FetchError('unsupported_content_encoding')
            return response.status, h, body
        finally:
            connection.close()
            sock.close()


def validators(headers):
    h = {k.lower(): v for k, v in headers.items()}
    # Bound untrusted header lengths; never reuse CR/LF values in a request.
    def clean(k):
        v = h.get(k)
        return v if isinstance(v, str) and len(v) <= 1024 and '\r' not in v and '\n' not in v else None
    return {'etag': clean('etag'), 'last_modified': clean('last-modified')}


def fetch_one(root, source, prior, staging, github, http):
    url = source['original_url']
    result = {'source_id': source['source_id'], 'url': url, 'checked_at': now()}
    if source.get('fetch_status') == 'sensitive_quarantined':
        return {**result, 'status': 'quarantined_skipped', 'content_downloaded': False}
    try:
        selector = github_file(url)
        cached = bootstrap_record(root, source, prior)
        if selector:
            meta = github.metadata(selector)
            if not re.fullmatch('[0-9a-f]{40}', meta.get('sha', '')):
                raise FetchError('github_invalid_metadata_sha')
            if meta.get('size') is not None and meta['size'] > MAX_BYTES:
                raise FetchError('configuration_too_large')
            if cached and cached.get('github_blob_sha') == meta['sha']:
                return {**result, 'status': 'reused_blob_sha', 'content_downloaded': False, 'record': cached}
            body = github.body(selector, meta['sha'])
            if blob_sha(body) != meta['sha'] or (meta.get('size') is not None and len(body) != meta['size']):
                raise FetchError('github_blob_integrity_failed')
            version = {'github_blob_sha': meta['sha'], 'etag': None, 'last_modified': None}
        else:
            headers = {}
            if cached:
                v = validators({'etag': cached.get('etag'), 'last-modified': cached.get('last_modified')})
                if v['etag']:
                    headers['If-None-Match'] = v['etag']
                if v['last_modified']:
                    headers['If-Modified-Since'] = v['last_modified']
            status, h, body = http.get(url, headers)
            if status == 304:
                if cached and headers and verified(root, cached):
                    updated = dict(cached)
                    updated.update({k: v for k, v in validators(h).items() if v is not None})
                    return {**result, 'status': 'reused_http_304', 'content_downloaded': False, 'record': updated}
                # Unexpected 304 or cache lost mid-request: one unconditional request.
                status, h, body = http.get(url, {})
            if status != 200:
                raise FetchError('http_' + str(status))
            version = {'github_blob_sha': None, **validators(h)}
        digest = sha256(body)
        if cached and cached['sha256'] == digest and cached['byte_count'] == len(body) and verified(root, cached):
            cached.update(version)
            return {**result, 'status': 'downloaded_unchanged', 'content_downloaded': True, 'record': cached}
        path = Path(staging) / (hashlib.sha256(source['source_id'].encode()).hexdigest()[:20] + '-' + digest + '.body')
        path.write_bytes(body)
        return {**result, 'status': 'downloaded_pending_safety_review', 'content_downloaded': True,
                'staged_file': str(path), 'record': {'url': url, 'archive_path': None, 'sha256': digest,
                'byte_count': len(body), **version}}
    except (FetchError, OSError, TimeoutError, subprocess.TimeoutExpired, http_client.HTTPException, ValueError) as e:
        reason = str(e) if isinstance(e, FetchError) else type(e).__name__
        return {**result, 'status': 'blocked_or_failed', 'reason': reason, 'content_downloaded': None}


def accept_state(root, old, report, accepted):
    """Only archive-verified, explicitly accepted new bodies enter reusable state.
    `accepted` is source_id -> approved archive path, after safety and ingestion.
    """
    state = json.loads(json.dumps(old))
    for item in report['results']:
        sid, status = item['source_id'], item['status']
        if status == 'quarantined_skipped':
            state['entries'].pop(sid, None)
            continue
        record = item.get('record')
        if not record:
            continue
        record = dict(record)
        if status == 'downloaded_pending_safety_review':
            if sid not in accepted:
                continue
            record['archive_path'] = accepted[sid]
        if not verified(root, record):
            raise ValueError('accepted_archive_integrity_failed:' + sid)
        record['checked_at'] = item['checked_at']
        state['entries'][sid] = record
    return state


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', default='.')
    p.add_argument('--state', default='archive/historical/fetch_state.json')
    sub = p.add_subparsers(dest='command', required=True)
    f = sub.add_parser('fetch'); f.add_argument('--staging', required=True); f.add_argument('--source-id', action='append')
    a = sub.add_parser('accept'); a.add_argument('--report', required=True); a.add_argument('--accepted', required=True)
    args = p.parse_args(); root = Path(args.root).resolve()
    state_path = safe_path(root, args.state); state = load_state(state_path)
    if args.command == 'accept':
        result = accept_state(root, state, json.loads(Path(args.report).read_text()), json.loads(Path(args.accepted).read_text()))
        state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = state_path.with_suffix('.tmp'); temp.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n'); temp.replace(state_path)
        print(json.dumps({'state_entries': len(result['entries'])})); return
    staging = Path(args.staging).resolve()
    if staging.is_relative_to(root):
        raise ValueError('staging_must_be_outside_repository')
    staging.mkdir(parents=True, exist_ok=True)
    if (staging / 'report.json').exists():
        raise ValueError('use_a_fresh_staging_directory')
    feed = load_feed(root/'feed.json'); gh = GitHub(); http = HTTP(); results = []
    for source in feed['sources']:
        if args.source_id and source['source_id'] not in args.source_id:
            continue
        results.append(fetch_one(root, source, state['entries'].get(source['source_id']), staging, gh, http))
    report = {'schema_version': 'source-hub-fetch-report.v1', 'created_at': now(), 'results': results}
    (staging/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    from collections import Counter
    print(json.dumps(dict(Counter(r['status'] for r in results)), ensure_ascii=False))


if __name__ == '__main__':
    main()
