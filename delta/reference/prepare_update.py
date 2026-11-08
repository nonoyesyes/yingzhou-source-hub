"""Offline staging/acquisition handoff. No network and no third-party execution."""
import argparse,copy,hashlib,json,shutil,sys
from pathlib import Path
sys.dont_write_bytecode=True
import delta_delivery as delta
from feed_common import strict_load,expand_shared
from rebuild_feed import rebuild
from validate_feed import validate
from static_parser import detect_format
from incremental_fetch import accept_state,blob_sha


def initialize(root,staging,cache_path=None):
 root=Path(root).resolve();staging=Path(staging).resolve()
 if staging==root or staging.is_relative_to(root):raise ValueError('staging must be outside repository')
 if staging.exists() and any(staging.iterdir()):raise ValueError('staging must be fresh')
 state=delta.load_state(root);feed=delta.materialize(state['model']);staging.mkdir(parents=True,exist_ok=True)
 for record in feed['archive_files']:
  src=delta.safe(root,record['path']);dest=delta.safe(staging,record['path'])
  if src.stat().st_size!=record['byte_count'] or delta.file_hash(src)!=record['sha256']:raise ValueError('archive integrity failed')
  dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dest)
 delta.write_atomic(staging/'feed.json',delta.encoded(feed)+b'\n')
 delta.write_atomic(staging/'.base-state.json',delta.encoded({'state_sha256':state['state_sha256'],'sequence':state['sequence']})+b'\n')
 # Cache is mutable local execution state, never an immutable archive artifact.
 previous=Path(cache_path).resolve() if cache_path else staging/'archive/historical/fetch_state.json'
 if cache_path and previous.is_relative_to(root):raise ValueError('mutable cache must be outside repository')
 cache=strict_load(previous) if previous.exists() else {'schema_version':'source-hub-fetch-state.v1','entries':{}}
 delta.write_atomic(staging/'.fetch_state.json',delta.encoded(cache)+b'\n')
 return {'sequence':state['sequence'],'staging_initialized':True}


def restore_parse_times(old,new):
 previous={s['source_id']:s for s in old['sources']}
 expanded=expand_shared({'sources':new['sources'],'shared_values':new.get('shared_values',{})})['sources']
 for s,semantic in zip(new['sources'],expanded):
  p=previous.get(s['source_id'])
  if not p:continue
  snaps={(x['sha256'],x['path']):x for x in p['snapshots']}
  for sn,expanded_sn in zip(s['snapshots'],semantic['snapshots']):
   prior=snaps.get((sn['sha256'],sn['path']))
   if prior:
    a={k:v for k,v in prior.items() if k!='parse_time'};b={k:v for k,v in expanded_sn.items() if k!='parse_time'}
    if a==b:sn['parse_time']=prior.get('parse_time');expanded_sn['parse_time']=prior.get('parse_time')
  a={k:v for k,v in p.items() if k!='parse_time'};b={k:v for k,v in semantic.items() if k!='parse_time'}
  if a==b:s['parse_time']=p.get('parse_time')
 return new


def ingest(root,staging,report,review,generated_at=None,publish=False,cache_path=None):
 root=Path(root).resolve();staging=Path(staging).resolve()
 if staging==root or staging.is_relative_to(root):raise ValueError('staging must be outside repository')
 base=strict_load(staging/'.base-state.json');state=delta.load_state(root)
 if base['state_sha256']!=state['state_sha256']:raise ValueError('staging is stale; refresh from latest state')
 old=expand_shared(delta.materialize(state['model']));feed=copy.deepcopy(old);sources={s['source_id']:s for s in feed['sources']}
 if report.get('schema_version')!='source-hub-fetch-report.v1' or review.get('schema_version')!='source-hub-safety-review.v1':raise ValueError('wrong report/review format')
 decisions={}
 for d in review['decisions']:
  key=(d['source_id'],d['sha256'])
  if key in decisions or d['decision'] not in ('publish','quarantine') or not d.get('reason'):raise ValueError('invalid or duplicate safety decision')
  decisions[key]=d
 accepted={};outcomes=[];added=0;seen=set()
 for item in report['results']:
  sid=item['source_id']
  if sid in seen:raise ValueError('duplicate fetch result')
  seen.add(sid)
  if sid not in sources or item['url']!=sources[sid]['original_url']:raise ValueError('unregistered source or URL mismatch')
  source=sources[sid];status=item['status']
  if status!='downloaded_pending_safety_review':
   outcomes.append({'source_id':sid,'status':status});continue
  record=item['record'];decision=decisions.get((sid,record['sha256']))
  if source['fetch_status']=='sensitive_quarantined' or not decision or decision['decision']!='publish':
   outcomes.append({'source_id':sid,'status':'quarantined_or_pending_review','sha256':record['sha256']});continue
  raw=Path(item['staged_file']).read_bytes()
  if hashlib.sha256(raw).hexdigest()!=record['sha256'] or len(raw)!=record['byte_count'] or record['url']!=item['url']:raise ValueError('reviewed body integrity mismatch')
  if record.get('github_blob_sha') and blob_sha(raw)!=record['github_blob_sha']:raise ValueError('GitHub blob integrity mismatch')
  existing=next((sn for sn in source['snapshots'] if sn['sha256']==record['sha256']),None)
  if existing:accepted[sid]=existing['path'];outcomes.append({'source_id':sid,'status':'existing_snapshot_reused'});continue
  try:fmt=detect_format(raw.decode('utf-8-sig'))
  except (ValueError,UnicodeError):fmt='unsupported'
  ext={'m3u':'m3u','json_config':'jsonc','tvbox_txt':'txt'}.get(fmt,'bin')
  source_key=hashlib.sha256(sid.encode()).hexdigest()[:24]
  path=next((a["path"] for a in old["archive_files"] if a["path"].startswith("archive/sources/") and a["sha256"]==record["sha256"] and a["byte_count"]==len(raw)),None)
  path=path or f"archive/sources/{source_key}/{record['sha256']}.{ext}"
  target=delta.safe(staging,path)
  if target.exists() and target.read_bytes()!=raw:raise ValueError('immutable snapshot collision')
  if not target.exists():delta.write_atomic(target,raw)
  snapshot={'kind':'github_blob_bytes' if record.get('github_blob_sha') else 'http_response_bytes','fetch_time':item['checked_at'],'reported_sha256':record['sha256'],'format_hint':fmt,'capture_evidence':{'type':'incremental_registered_config_fetch','url':item['url'],'github_blob_sha':record.get('github_blob_sha'),'safety_review':{'decision':'publish','reviewed_sha256':record['sha256'],'reason':decision['reason']}},'path':path,'sha256':record['sha256'],'byte_count':len(raw),'parse_time':None,'encoding':'utf-8','parse_result':{},'parse_status':'not_parsed'}
  source['snapshots'].append(snapshot);source['fetch_status']='retained';source['fetch_time']=item['checked_at'];accepted[sid]=path;added+=1
  outcomes.append({'source_id':sid,'status':'snapshot_added','sha256':record['sha256'],'path':path})
 # Cache acceptance is local; blocked/unreviewed bodies never become reusable accepted archive data.
 cache=accept_state(staging,strict_load(staging/'.fetch_state.json'),report,accepted)
 delta.write_atomic(staging/'.fetch_state.json',delta.encoded(cache)+b'\n')
 if cache_path:
  cache_target=Path(cache_path).resolve()
  if cache_target.is_relative_to(root):raise ValueError('mutable cache must be outside repository')
  delta.write_atomic(cache_target,delta.encoded(cache)+b'\n')
 if added:
  delta.write_atomic(staging/'feed.json',delta.encoded(feed)+b'\n')
  new=rebuild(staging,generated_at=generated_at)
  new=restore_parse_times(old,new)
  delta.write_atomic(staging/'feed.json',delta.encoded(new)+b'\n')
 else:new=delta.compact_feed(copy.deepcopy(old));delta.write_atomic(staging/'feed.json',delta.encoded(new)+b'\n')
 validate(staging)
 candidate=delta.model(new)
 for collection in delta.KEYS:
  before=state['model']['entities'][collection];after=candidate['entities'][collection]
  if not set(before)<=set(after):raise ValueError('unrequested record removal')
  for key,row in after.items():delta.preserve_history(collection,before.get(key),row)
 result={'added_snapshot_count':added,'outcomes':outcomes,'validated':True,'published':False}
 if publish:
  for record in new['archive_files']:
   source=delta.safe(staging,record['path']);dest=delta.safe(root,record['path'])
   if dest.exists():
    if dest.stat().st_size!=record['byte_count'] or delta.file_hash(dest)!=record['sha256']:raise ValueError('immutable archive collision')
   else:delta.write_atomic(dest,source.read_bytes())
  result['publication']=delta.publish(root,staging/'feed.json');result['published']=result['publication']['changed']
 return result


def main():
 p=argparse.ArgumentParser();p.add_argument('command',choices=['init','ingest']);p.add_argument('--root',default='.');p.add_argument('--staging',required=True);p.add_argument('--cache');p.add_argument('--report');p.add_argument('--review');p.add_argument('--generated-at');p.add_argument('--publish',action='store_true');a=p.parse_args()
 result=initialize(a.root,a.staging,a.cache) if a.command=='init' else ingest(a.root,a.staging,strict_load(Path(a.report)),strict_load(Path(a.review)),a.generated_at,a.publish,a.cache)
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
