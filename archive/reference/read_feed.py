"""Minimal deterministic consumer. No AI, network or playback required."""
import sys
sys.dont_write_bytecode=True
from pathlib import Path
from feed_common import strict_load,expand_shared

def load_feed(path='feed.json'):
 feed=strict_load(Path(path))
 if feed.get('schema_version')!='source-hub-feed.v1':raise ValueError('unsupported schema')
 return expand_shared(feed)

def live_origins(candidate):
 for origin in candidate['origins']:
  resolved={k:v for k,v in {**candidate,**origin}.items() if k not in ['origins','inherits_candidate_fields','origin_count','deduplication_basis']}
  resolved['url_raw']=resolved['request']['url']
  yield resolved

def vod_origins(site):
 for origin in site['origins']:
  yield {k:v for k,v in {**site,**origin}.items() if k not in ['origins','origin_count','deduplication_basis']}

def request_provenance(candidate):
 for record in candidate['request_provenance']:
  value=dict(record)
  if value.pop('path_ref',None)=='raw_ref':value['path']=candidate['raw_ref']
  if value.pop('locator_ref',None)=='entry_locator':value['locator']=candidate['entry_locator']
  yield value
