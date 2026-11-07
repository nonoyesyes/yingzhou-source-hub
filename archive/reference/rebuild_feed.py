#!/usr/bin/env python3
"""Rebuild source-hub-feed.v1 solely from an existing feed and its local archive.
Usage: python archive/reference/rebuild_feed.py --root . [--input-feed PATH]
No networking or execution of source-supplied code. Requires Python 3.10+.
"""
import sys
sys.dont_write_bytecode=True
import argparse,copy,hashlib,json
from pathlib import Path
from datetime import datetime,timezone
from read_feed import load_feed,live_origins
from feed_common import strict_load
from static_parser import parse_snapshot
from assemble_feed import assemble

def rebuild(root,input_feed=None,generated_at=None):
 root=Path(root).resolve(); old=load_feed(input_feed or root/'feed.json')
 prior_live_snapshots={(o['source_id'],o['source_snapshot_sha256']) for e in old['live_entries'] for o in live_origins(e)}
 now=generated_at or datetime.now(timezone.utc).isoformat()
 x={'original_inventory':copy.deepcopy(old['original_inventory']),'sources':copy.deepcopy(old['sources']),'raw_live_entries':[],'vod_sites':[]}
 for s in x['sources']:
  if not s['snapshots']:continue
  s['live_candidate_count']=0;s['vod_site_count']=0
  statuses=[]
  for sn in s['snapshots']:
   p=(root/sn['path']).resolve()
   if not p.is_relative_to(root):raise ValueError('escaped snapshot path')
   b=p.read_bytes()
   if len(b)!=sn['byte_count'] or hashlib.sha256(b).hexdigest()!=sn['sha256']:raise ValueError('snapshot bytes changed')
   result=parse_snapshot(s,sn,b,preserve_proxy_candidates=(s['source_id'],sn['sha256']) in prior_live_snapshots)
   sn['parse_result']=result['parse_result'];sn['parse_status']=result.get('parse_status') or ('partial' if result['parse_result'].get('unparsed_items') else 'complete')
   sn['parse_time']=now;statuses.append(sn['parse_status'])
   x['raw_live_entries'].extend(result['raw_live_entries']);x['vod_sites'].extend(result['vod_sites'])
   s['live_candidate_count']+=len(result['raw_live_entries']);s['vod_site_count']+=len(result['vod_sites'])
  s['parse_status']='complete' if set(statuses)=={'complete'} else 'partial' if any(v in ['partial','complete'] for v in statuses) else 'unsupported'
  s['parse_time']=now;s['parse_scope']='all_retained_snapshots'
  s['incomplete_reasons']=[v for v in s['incomplete_reasons'] if v!='see_snapshot_parse_result']
  if s['parse_status']!='complete':s['incomplete_reasons'].append('see_snapshot_parse_result')
 f=assemble(x,copy.deepcopy(old['checks']),copy.deepcopy(old['environments']),'source-hub-offline-rebuild-'+now.replace(':','').replace('-',''),now)
 # Only derivative feed is rewritten. All raw/evidence/history bytes stay untouched.
 f['archive_files']=[{'path':str(p.relative_to(root)),'byte_count':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted((root/'archive').rglob('*')) if p.is_file() and '__pycache__' not in p.parts]
 (root/'feed.json').write_text(json.dumps(f,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n','utf-8')
 return f
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',default='.');p.add_argument('--input-feed');p.add_argument('--generated-at');a=p.parse_args()
 f=rebuild(a.root,a.input_feed,a.generated_at);print(json.dumps(f['summary'],ensure_ascii=False,indent=2))
