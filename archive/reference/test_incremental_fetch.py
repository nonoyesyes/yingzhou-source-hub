#!/usr/bin/env python3
"""Offline regression: all network transports are fakes. No source/media requests."""
import sys
sys.dont_write_bytecode = True
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from incremental_fetch import (fetch_one, blob_sha, sha256, accept_state, STATE_VERSION,
                               GitHub, FetchError, github_file, public_url, public_addresses)


class FakeGitHub:
    def __init__(self, body=b'abc', digest=None):
        self.value = body; self.digest = digest or blob_sha(body); self.metadata_calls = 0; self.body_calls = 0
    def metadata(self, selector):
        self.metadata_calls += 1
        return {'sha': self.digest, 'size': len(self.value)}
    def body(self, selector, digest):
        self.body_calls += 1; return self.value


class FakeHTTP:
    def __init__(self, responses): self.responses = list(responses); self.calls = []
    def get(self, url, headers):
        self.calls.append((url, headers.copy()))
        r = self.responses.pop(0)
        return r() if callable(r) else r


class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory(); self.root = Path(self.t.name)/'repo'; self.root.mkdir()
        self.stage = Path(self.t.name)/'stage'; self.stage.mkdir()
        self.url = 'https://raw.githubusercontent.com/user/repo/main/list.txt'
        self.b = b'abc'; self.p = self.root/'archive'/'source.txt'; self.p.parent.mkdir(); self.p.write_bytes(self.b)
        self.sn = {'path': 'archive/source.txt', 'byte_count': 3, 'sha256': sha256(self.b), 'fetch_time': '2026-01-01',
                   'capture_evidence': {'url': self.url, 'github_blob_sha': blob_sha(self.b)}}
        self.s = {'source_id': 's', 'original_url': self.url, 'snapshots': [self.sn], 'fetch_status': 'retained'}
        self.gh = FakeGitHub(); self.http = FakeHTTP([])
    def tearDown(self): self.t.cleanup()
    def call(self, prior=None): return fetch_one(self.root, self.s, prior, self.stage, self.gh, self.http)
    def http_source(self):
        self.s['original_url'] = 'https://example.com/list?token=public&b=2&a=1'
        return {'url': self.s['original_url'], 'archive_path': 'archive/source.txt', 'sha256': sha256(self.b),
                'byte_count': 3, 'etag': '"abc"', 'last_modified': 'Wed, 01 Jan 2025 00:00:00 GMT', 'github_blob_sha': None}
    def test_malformed_port_is_reported_not_crash(self):
        self.s['original_url'] = 'https://raw.githubusercontent.com:bad/o/r/main/a'
        self.assertEqual(self.call()['status'], 'blocked_or_failed')
    def test_unchanged_blob_no_body_download(self):
        r = self.call(); self.assertEqual(r['status'], 'reused_blob_sha'); self.assertEqual(self.gh.body_calls, 0)
    def test_existing_bytes_without_prior_git_sha_reuse(self):
        self.sn['capture_evidence'] = {'type': 'historical_content'}
        self.assertEqual(self.call()['status'], 'reused_blob_sha'); self.assertEqual(self.gh.body_calls, 0)
    def test_nondefault_github_port_preserved_by_http(self):
        self.assertIsNone(github_file('https://raw.githubusercontent.com:8443/o/r/main/a'))
    def test_changed_blob_downloads(self):
        self.gh = FakeGitHub(b'new'); r = self.call()
        self.assertEqual(r['status'], 'downloaded_pending_safety_review'); self.assertEqual(Path(r['staged_file']).read_bytes(), b'new')
    def test_first_fetch_downloads(self):
        self.s['snapshots'] = []; self.assertEqual(self.call()['status'], 'downloaded_pending_safety_review')
    def test_missing_local_does_not_skip(self):
        self.p.unlink(); self.assertTrue(self.call()['content_downloaded'])
    def test_corrupt_local_does_not_skip(self):
        self.p.write_bytes(b'bad'); self.assertTrue(self.call()['content_downloaded'])
    def test_wrong_blob_hash_rejected(self):
        self.gh = FakeGitHub(b'new', digest='1'*40); self.assertEqual(self.call()['reason'], 'github_blob_integrity_failed')
    def test_body_does_not_change_original(self):
        self.gh = FakeGitHub(b'new'); self.call(); self.assertEqual(self.p.read_bytes(), b'abc')
    def test_cached_prior_wrong_url_ignored(self):
        p = self.http_source(); p['url'] += '&wrong=1'; self.s['snapshots'] = []
        self.http = FakeHTTP([(200, {}, b'new')]); self.call(p); self.assertEqual(self.http.calls[0][1], {})
    def test_http_304_uses_valid_archive(self):
        p = self.http_source(); self.http = FakeHTTP([(304, {}, b'')]); r = self.call(p)
        self.assertEqual(r['status'], 'reused_http_304'); self.assertEqual(self.http.calls[0][1]['If-None-Match'], '"abc"')
        self.assertEqual(self.http.calls[0][0], self.s['original_url'])
    def test_http_missing_archive_unconditional(self):
        p = self.http_source(); self.p.unlink(); self.http = FakeHTTP([(200, {}, b'abc')]); self.call(p)
        self.assertEqual(self.http.calls[0][1], {})
    def test_http_corrupt_archive_unconditional(self):
        p = self.http_source(); self.p.write_bytes(b'bad'); self.http = FakeHTTP([(200, {}, b'abc')]); self.call(p)
        self.assertEqual(self.http.calls[0][1], {})
    def test_http_unexpected_304_one_fallback(self):
        self.http_source(); self.s['snapshots'] = []; self.http = FakeHTTP([(304, {}, b''), (200, {}, b'abc')]); r = self.call()
        self.assertEqual(r['status'], 'downloaded_pending_safety_review'); self.assertEqual(len(self.http.calls), 2)
    def test_http_repeated_304_fails(self):
        self.http_source(); self.s['snapshots'] = []; self.http = FakeHTTP([(304, {}, b''), (304, {}, b'')]); r = self.call()
        self.assertEqual(r['reason'], 'http_304'); self.assertEqual(len(self.http.calls), 2)
    def test_http_cache_disappears_at_304(self):
        p = self.http_source()
        def lost(): self.p.unlink(); return 304, {}, b''
        self.http = FakeHTTP([lost, (200, {}, b'abc')]); r = self.call(p)
        self.assertEqual(r['status'], 'downloaded_pending_safety_review'); self.assertEqual(self.http.calls[1][1], {})
    def test_no_validator_same_body(self):
        p = self.http_source(); p['etag'] = p['last_modified'] = None
        self.http = FakeHTTP([(200, {'ETag': '"fresh"'}, b'abc')]); r = self.call(p)
        self.assertEqual(r['status'], 'downloaded_unchanged'); self.assertEqual(r['record']['etag'], '"fresh"')
    def test_changed_http_body_needs_safety(self):
        p = self.http_source(); self.http = FakeHTTP([(200, {'ETag': '"new"'}, b'new')]); r = self.call(p)
        self.assertEqual(r['status'], 'downloaded_pending_safety_review'); self.assertIsNone(r['record']['archive_path'])
    def test_http_403_not_retried(self):
        p = self.http_source(); self.http = FakeHTTP([(403, {}, b'')]); self.assertEqual(self.call(p)['reason'], 'http_403')
        self.assertEqual(len(self.http.calls), 1)
    def test_header_injection_ignored(self):
        p = self.http_source(); p['etag'] = 'x\r\nInjected: secret'; p['last_modified'] = None
        self.http = FakeHTTP([(200, {}, b'abc')]); self.call(p); self.assertEqual(self.http.calls[0][1], {})
    def test_quarantine_never_requested(self):
        self.s['fetch_status'] = 'sensitive_quarantined'; self.assertEqual(self.call()['status'], 'quarantined_skipped')
        self.assertEqual(self.gh.metadata_calls, 0)
    def test_new_body_not_promoted_implicitly(self):
        self.gh = FakeGitHub(b'new'); r = self.call(); state = {'schema_version': STATE_VERSION, 'entries': {}}
        self.assertEqual(accept_state(self.root, state, {'results': [r]}, {})['entries'], {})
    def test_safe_archive_promoted_by_exact_bytes(self):
        self.gh = FakeGitHub(b'new'); r = self.call(); (self.root/'archive/new').write_bytes(b'new')
        state = accept_state(self.root, {'entries': {}}, {'results': [r]}, {'s': 'archive/new'})
        self.assertEqual(state['entries']['s']['github_blob_sha'], blob_sha(b'new'))
    def test_wrong_or_escaped_accepted_archive_rejected(self):
        self.gh = FakeGitHub(b'new'); r = self.call()
        for path in ['archive/source.txt', '../stage/file', '/tmp/no']:
            with self.assertRaises(ValueError): accept_state(self.root, {'entries': {}}, {'results': [r]}, {'s': path})
    def test_shared_tree_metadata_cached(self):
        gh = GitHub(); calls = []
        def api(endpoint):
            calls.append(endpoint); return {'tree': [{'path': 'a', 'sha': 'a'*40, 'type': 'blob', 'mode': '100644', 'size': 1}, {'path': 'b', 'sha': 'b'*40, 'type': 'blob', 'mode': '100644', 'size': 1}]}
        gh.api = api
        for name in ['a','b']: gh.metadata({'owner': 'o', 'repo': 'r', 'ref': 'main', 'path': name})
        self.assertEqual(len(calls), 1)
    def test_symlink_not_downloaded(self):
        gh = GitHub(); gh.api = lambda e: {'tree': [{'path': 'a', 'sha': 'a'*40, 'type': 'blob', 'mode': '120000'}]}
        with self.assertRaises(FetchError): gh.metadata({'owner': 'o', 'repo': 'r', 'ref': 'main', 'path': 'a'})
    def test_explicit_refs_heads_real_registry_urls(self):
        u = 'https://raw.githubusercontent.com/MercuryZz/IPTVN/refs/heads/Files/IPTV.m3u'
        self.assertEqual(github_file(u), {'owner': 'MercuryZz', 'repo': 'IPTVN', 'ref': 'Files', 'path': 'IPTV.m3u'})
    def test_noncanonical_numeric_local_urls_blocked(self):
        for host in ['127.1', '2130706433', '0x7f000001', 'localhost', '127.0.0.1']:
            with self.assertRaises(FetchError): public_url('http://'+host+'/config')
    def test_dns_private_or_mixed_answers_blocked(self):
        for ips in [['127.0.0.1'], ['8.8.8.8', '10.0.0.1']]:
            with patch('incremental_fetch.socket.getaddrinfo', return_value=[(2, 1, 6, '', (ip, 443)) for ip in ips]):
                with self.assertRaises(FetchError): public_addresses('public.example', 443)
    def test_public_dns_allowed(self):
        with patch('incremental_fetch.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('8.8.8.8',443))]):
            self.assertEqual(public_addresses('public.example',443)[0][4][0], '8.8.8.8')
    def test_query_url_not_rewritten_to_github_api(self):
        self.assertIsNone(github_file(self.url+'?token=public'))


if __name__ == '__main__': unittest.main(verbosity=2)
