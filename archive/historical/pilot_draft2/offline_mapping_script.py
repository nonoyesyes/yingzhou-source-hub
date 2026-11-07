import json,pathlib,copy,hashlib,shutil,sys,math,datetime
ROOT=pathlib.Path(__file__).parent;P=ROOT/'tvbox_protocol_draft';S=ROOT/'tvbox_pilot_draft2';O=ROOT/'tvbox_pilot_protocol_draft2';O.mkdir(exist_ok=True)
sys.path.insert(0,str(P));from request_revision import request_revision
B='offline-pilot-20261107'; V='0.1.0-draft.2'
def load(p):return json.loads(p.read_text())
def first(n):return json.loads((P/'sample'/n).read_text().splitlines()[0])
def common(r):
 r=copy.deepcopy(r);r.update(record_scope='production',null_reasons={},time_provenance={});
 if 'batch_id' in r:r['batch_id']=B
 return r
def req(url,ua=False):return {'method':'GET','url':url,'headers':{'user-agent':'Mozilla/5.0 (compatible; stream validation)'} if ua else {},'options':{}}
def dump(n,x):
 (O/n).parent.mkdir(parents=True,exist_ok=True)
 (O/n).write_text('\n'.join(json.dumps(r,ensure_ascii=False,separators=(',',':')) for r in x)+'\n' if n.endswith('.jsonl') else json.dumps(x,ensure_ascii=False,indent=2))
def nulls(r):
 def walk(x,p=''):
  if isinstance(x,dict):
   for k,v in list(x.items()):
    if k in ['null_reasons','time_provenance']:continue
    q=p+'/'+k
    if v is None:r['null_reasons'].setdefault(q,'Not observed or not applicable; retained evidence is authoritative. No value inferred.')
    else:walk(v,q)
  elif isinstance(x,list):
   for i,v in enumerate(x):walk(v,p+'/'+str(i))
 walk(r);return r
for d in ['raw','evidence','mapping']:
 shutil.copytree(S/d,O/d,dirs_exist_ok=True)
for f in ['sources.json','candidates.json','measurements.json','summary.json','run_pilot_executed.py']:
 shutil.copy2(S/f,O/'evidence'/('staging_'+f))
sources=[];srcs=load(S/'sources.json');cand=load(S/'candidates.json');meas=load(S/'measurements.json')
for x in srcs:
 r=common(first('sources.jsonl'));r.update(source_id='source:'+x['original_id'],name=x['url'],source_kind='live_playlist',url_original=x['url'],source_page_url=None,repository=None,legacy_refs=[],parent_source_id=None,selection_path=None,refresh_started_at=x['started_at'],refresh_finished_at=x['finished_at'],refresh_status='success',fetch_method='direct_http',http_status=x['requests'][-1]['http'],url_final=x['requests'][-1]['url'],content_type=x['requests'][-1].get('content_type'),byte_count=x['snapshot']['bytes'],error_code=None,error_message=None,snapshot_sha256=x['snapshot']['sha256'],raw_ref=x['snapshot']['path'],snapshot_fetched_at=None,snapshot_origin='fetched',snapshot_representation='http_entity_bytes',snapshot_origin_batch_id=B,snapshot_carried_forward=False,format_detected='iptv_m3u',parser_name='run_pilot_executed.py HTTP(S) line scanner',parser_version=None,parse_status='success',parse_complete=True,parse_scope={'kind':'declared_subset','selection':'All lines starting http:// or https:// only; not full TVBox semantic parsing'},withdrawal_eligible=False,counts={'raw_items':x['parsed_candidates'],'expanded_live_candidates':x['parsed_candidates'],'vod_sites':None,'placeholders':None,'invalid_items':None,'unexpanded_items':None},unexpanded_items=None,config_base_url=x['url'],dependencies=[],relationships=None,network_hints=None,extra={'source_scan_evidence':'evidence/staging_sources.json','not_full_semantic_parse':True});sources.append(nulls(r))
entries=[]
for x in cand:
 r=common(first('live_entries.jsonl'));r.update(entry_id=x['candidate_id'],source_id='source:'+x['source_original_id'],source_snapshot_sha256=x['source_snapshot_sha256'],entry_locator={'kind':'line_range','value':str(x['locator']['line_1_based'])},upstream_item_key=None,raw_entry=x['url'],raw_ref=x['raw_path'],name_raw=x['name'],request=req(x['url']),request_complete=True,request_conditions_origin=[],request_revision=request_revision(req(x['url'])),protocol_hint=x['url'].split(':')[0],unsupported_features=[],unresolved_dependencies=[],url_lifetime={'kind':'unknown','expires_at':None,'expiry_raw':None,'expiry_precision':None,'renewal_source_id':'source:'+x['source_original_id'],'basis':'Not investigated'},raw_metadata={'selection':'Selected entry blocks independently inspected offline: only EXTINF and URL, no per-entry EXTVLCOPT/header override. Request is GET with empty explicit headers; not a claim of playback compatibility.'});entries.append(nulls(r))
e=common(load(P/'sample/environments.json')[0]);env=load(S/'evidence/environment.json');e.update(env_id='env:dot-pilot',environment_kind='cloud',description=env['platform'],observed_at=env['utc'],tools=[{'name':k,'version':v.splitlines()[0],'version_evidence_ref':'evidence/environment.json'} for k,v in env['versions'].items()],proxy={'used':True,'kind':'managed HTTP(S)','description':'Inherited managed proxy; final IP and geography unknown'},network_limitations=['Not user or television network','No native IPv4/IPv6 capability inferred'],implicit_request_conditions=None);e['parameters']['concurrency']=1;e['parameters']['max_retries']=0;nulls(e)
checks=[]
for x in meas:
 c=next(q for q in cand if q['candidate_id']==x['candidate_id']);entry=next(q for q in entries if q['entry_id']==x['candidate_id']);r=common(first('checks.jsonl'));executed=x['media_request_attempted'];planned=req(c['url'],True)
 r.update(check_id='check:'+c['candidate_id'],target_id=c['candidate_id'],target_type='live_entry',source_snapshot_sha256=c['source_snapshot_sha256'],source_snapshot_ref=c['raw_path'],env_id=e['env_id'],check_type='short_decode',planned_request=planned,planned_request_revision=request_revision(planned),request_variant_of=entry['request_revision'],request_used=planned if executed else None,request_revision=request_revision(planned) if executed else None,started_at=x['started_at'],finished_at=x['finished_at'],evidence_kind='actual_measurement' if executed else 'not_run',status=x['status'],reason_code='target_duration_not_met' if executed else 'policy_blocked',reason_detail=x.get('reason',x.get('error','')),stopped_at_stage=None if executed else 'entry_request',stages=[],sample_complete=False if executed else None,warnings=None,errors=None,evidence_refs=['evidence/staging_measurements.json'],decode_runs=[],limitations=['Request UA is detector-added, not source-declared. Full source request annotations not parsed.','Coverage values in integer milliseconds are conservative floors; precise intervals remain in original evidence.','Preloaded sample, not continuous online or TVBox playback.'])
 r['metrics']={k:None for k in r['metrics']};m=r['metrics'];m['target_media_duration_ms']=10000
 if executed:
  m.update(http_requests=[{'role':'entry' if i==0 else ('media_segment' if z.get('response_evidence',{}).get('path') is None else 'media_playlist'),'url_requested':z['url'],'url_final':z['url'] if 'redirect_to' not in z else None,'status_code':z.get('http'),'body_bytes':z.get('bytes'),'elapsed_ms':math.floor(z['elapsed_seconds']*1000) if z.get('elapsed_seconds') is not None else None,'redirects':None} for i,z in enumerate(x['requests'])],ffprobe_exit_code=x['ffprobe']['exit_code'],input_mode='prefetched_offline',wall_clock_elapsed_ms=math.floor(x['wall_seconds']*1000),measurement_method='Actual framecrc PTS+duration interval union; ms floor; precise values in staging measurements; joint intersection assumes shared initial timestamp normalization and is not claimed as full proven original-media overlap.')
  r['evidence_refs'] += [x['ffprobe'][k]['path'] for k in ['stdout','stderr']]
  m['decoded_video_frames']=x['decode_runs'][0]['frame_count'];m['covered_media_duration_ms']=None
  r['null_reasons']['/metrics/covered_media_duration_ms']='Two processes reset timestamps independently; true original-media-time intersection not established. Staging intersection is only normalized-output-coordinate estimate.'
  for d in x['decode_runs']:
   kind=d['media_kind'];cov=math.floor(d['coverage_seconds']*1000);m['decoded_'+kind+'_duration_ms']=cov
   refs=[d[k]['path'] for k in ['stdout','stderr']];r['decode_runs'].append({'run_id':c['candidate_id']+':'+kind,'streams':[kind],'exit_code':d['exit_code'],'video_coverage_ms':cov if kind=='video' else None,'audio_coverage_ms':cov if kind=='audio' else None,'joint_coverage_ms':None,'log_refs':refs})
   r['stages'].append({'stage':kind+'_decode','status':'incomplete' if cov<10000 else 'pass','reason_code':'target_duration_not_met' if cov<10000 else None,'started_at':d['started_at'],'finished_at':d['finished_at'],'evidence_refs':refs});r['evidence_refs']+=refs
 else:r['stages']=[{'stage':'entry_request','status':'blocked','reason_code':'policy_blocked','started_at':x['started_at'],'finished_at':x['finished_at'],'evidence_refs':['evidence/staging_measurements.json']}]
 checks.append(nulls(r))
for n,x in [('sources.jsonl',sources),('live_entries.jsonl',entries),('vod_sites.jsonl',[]),('checks.jsonl',checks),('environments.json',[e])]:dump(n,x)
manifest=common(load(P/'sample/manifest.json'));manifest.update(batch_id=B,generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),data_kind='candidate_feed',publication_state='draft',all_sources_refreshed=True,collection_scope='3 actual source snapshots; 20 selected HTTP(S) candidates; five selected short checks',sampling_policy='5 selected, 2 media requests and independent decodes, 3 blocked before media request; no retries for status quotas',counts={'sources':3,'live_entries':20,'vod_sites':0,'unique_request_revisions':len(set(r['request_revision'] for r in entries)),'candidate_channel_hints':None,'check_records':5},source_refresh_summary={'success':3,'failed':0,'partial':0,'not_run':0},legacy_mapping={'expected_entry_count':160,'mapped_entry_count':160,'unresolved_entry_count':0,'complete':True,'evidence_ref':'mapping/original_160.json'},known_limitations=['All real measurements, no synthetic records','2 incomplete, 3 policy blocked, zero playback passes','Integer-ms floors; joint original media clock coverage unknown','No TVBox playback or continuous online verification','Production-mode validator is offline data validation, not publication authorization'],unfinished_items=['Remaining 15 candidates untested','Original-media-time aligned joint coverage not measured'],source_withdrawal_policy='No withdrawal inference; HTTP-only scanner and sampled candidates')
statuses=['not_tested','pass','pass_with_warnings','fail','blocked','unsupported','incomplete','cancelled'];manifest['check_summary']={'short_decode':{'planned_targets':5,'attempted_targets':2,'attempt_count':2,'not_attempted_targets':3,'status_counts':{s:sum(r['status']==s for r in checks) for s in statuses}}}
schema='schema/'+V+'/source-feed.schema.json';(O/schema).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(P/schema,O/schema);manifest['schema']={'path':schema,'sha256':hashlib.sha256((O/schema).read_bytes()).hexdigest()}
manifest['files']=[]
for f in sorted(O.rglob('*')):
 if f.is_file() and f.name not in ['manifest.json','business_validation.json','README.md']:
  b=f.read_bytes();name=str(f.relative_to(O));count={'sources.jsonl':3,'live_entries.jsonl':20,'vod_sites.jsonl':0,'checks.jsonl':5,'environments.json':1}.get(name);manifest['files'].append({'path':name,'byte_count':len(b),'record_count':count,'sha256':hashlib.sha256(b).hexdigest(),'git_blob_oid':None,'git_object_format':None})
dump('manifest.json',nulls(manifest))
