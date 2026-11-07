"""Offline assembly, stable rr1 grouping and lossless origin overlays."""
import json,sys,hashlib,re,collections
from datetime import datetime,timezone
from request_revision import request_revision
from feed_common import summary
from normalize_names import normalize,CATEGORIES

def assemble(x,checks,env,batch_id,generated_at):
 live=[]
 for e in x['raw_live_entries']:
  e['raw_ref']=e.pop('source_archive_path');loc=e['entry_locator']
  if loc['type']=='line':e['entry_locator']={'kind':'line_range','value':str(loc['line']),'source_locator':loc}
  else:e['entry_locator']={'kind':'json_pointer','value':loc['pointer'],'source_locator':loc}
  if loc['type']=='json_pointer':
   attrs=e['raw_metadata'].get('attributes',{});item=attrs.get('json_item',{});inherited=attrs.get('inherited_request_conditions',{})
   for field,aliases in {'group_raw':['group','group-title'],'epg_url_raw':['epg','url-tvg','x-tvg-url'],'logo_url_raw':['logo','tvg-logo'],'tvg_id_raw':['tvg-id'],'tvg_name_raw':['tvg-name']}.items():
    if e.get(field) is None:
     found=[(k,v) for k,v in inherited.items() if k.rsplit('/',1)[-1] in aliases and isinstance(v,str)]
     vals=[item[a] for a in aliases if isinstance(item,dict) and isinstance(item.get(a),str)]
     if vals or found:e[field]=vals[0] if vals else sorted(found,key=lambda kv:len(kv[0]),reverse=True)[0][1];e['metadata_status'][field]='present'
  e['raw_entry']=e['url_raw']
  e['request_revision']=request_revision(e['request']) if e['request_complete'] else None
  live.append(normalize(e))
 for e in x['vod_sites']:
  e['vod_site_id']=e.pop('site_id');e['raw_ref']=e.pop('source_archive_path');e['entry_locator']={'kind':'json_pointer','value':e['entry_locator']['pointer']}
 by={}
 for e in live:by.setdefault((e['source_id'],e['source_snapshot_sha256'],e['request']['url']),[]).append(e)
 for c in checks:
  hint=c.get('entry_match_hint') or {};matches=by.get((hint.get('source_id'),hint.get('source_snapshot_sha256'),hint.get('url')),[])
  if c['target_type']=='live_entry':
   loc=hint.get('entry_locator');exact=[e for e in matches if e['entry_locator']['kind']==loc['kind'] and e['entry_locator']['value']==loc['value']]
   if len(exact)!=1:raise ValueError('ambiguous/missing pilot map '+c['check_id']+' '+str(len(exact)))
   c['target_id']=exact[0]['entry_id'];c['prior_target_id']=hint['prior_entry_id']
   # Static extraction may recover conditions absent from pilot extraction. The same
   # actual check retains original request bytes; recompute only its lineage marker.
   target=exact[0]
   if target['request_complete'] and any(c.get(k) and request_revision(c[k])!=target['request_revision'] for k in ['planned_request','request_used']):c['request_variant_of']=target['request_revision']
  c['candidate_entry_ids']=[e['entry_id'] for e in matches]
 # Remap preserved checks to content-addressed, deduplicated retained snapshot files.
 snapshot_paths={}
 for source in x['sources']:
  for snap in source['snapshots']:snapshot_paths[snap['sha256']]=snap['path']
 for c in checks:
  if c.get('source_snapshot_sha256') in snapshot_paths:c['source_snapshot_ref']=snapshot_paths[c['source_snapshot_sha256']]
 # Explicit machine-readable not-tested scope, without inventing check records.
 linked=collections.defaultdict(list)
 for c in checks:
  if c['target_type']=='live_entry':linked[c['target_id']].append(c['check_id'])
 for e in live:
  e['check_ids']=linked[e['entry_id']];e['check_status']='not_tested' if not e['check_ids'] else next(c['status'] for c in checks if c['check_id']==e['check_ids'][-1])
 # Latest user instruction: deduplicate identical effective requests, retaining all origins.
 original_live_count=len(live);groups={};mapping={}
 for e in live:
  key=e['request_revision'] if e['request_complete'] else e['entry_id']
  if key not in groups:
   base=dict(e);base['origins']=[];base['entry_id']='live:'+hashlib.sha256(key.encode()).hexdigest()[:24];groups[key]=base
  base=groups[key];base['origins'].append({k:v for k,v in e.items() if k not in ['request','request_revision','request_complete','check_ids','check_status']});mapping[e['entry_id']]=base['entry_id']
  base['check_ids']=list(dict.fromkeys(base['check_ids']+e['check_ids']))
 live=list(groups.values())
 for e in live:
  keys={o['channel_key_hint'] for o in e['origins'] if o['channel_key_hint']}
  if len(keys)>1:e['name_match_status']='ambiguous';e['channel_key_hint']=None;e['normalization_null_reasons']['channel_key_hint']='conflicting_names_on_same_effective_request'
  e['check_status']='not_tested' if not e['check_ids'] else next(c['status'] for c in checks if c['check_id']==e['check_ids'][-1])
  e['origin_count']=len(e['origins']);e['deduplication_basis']='identical_complete_rr1' if e['request_complete'] else 'incomplete_not_merged'
 for c in checks:
  if c['target_type']=='live_entry':c['target_id']=mapping[c['target_id']]
  c['candidate_entry_ids']=list(dict.fromkeys(mapping[z] for z in c['candidate_entry_ids']))
 # Origins are deterministic field overlays; identical primary values are inherited.
 for e in live:
  e['origins']=[{'entry_id':o['entry_id'],'inherits_candidate_fields':True,**{k:v for k,v in o.items() if k!='entry_id' and e.get(k)!=v}} for o in e['origins']]
 # VOD identity includes complete static site payload and configuration dependencies.
 source_map={s['source_id']:s for s in x['sources']};vgroup={}
 for e in x['vod_sites']:
  snap=next(s for s in source_map[e['source_id']]['snapshots'] if s['sha256']==e['source_snapshot_sha256'])
  deps=snap['parse_result'].get('config_dependencies',[])
  identity=json.dumps({'site':e['site_raw'],'dependencies':deps,'base_url':source_map[e['source_id']]['original_url'] if re.search(r'(?<![A-Za-z])\.\.?/',json.dumps({'site':e['site_raw'],'dependencies':deps})) else None},sort_keys=True,ensure_ascii=False,separators=(',',':'))
  key=hashlib.sha256(identity.encode()).hexdigest()
  if key not in vgroup:vgroup[key]={**e,'vod_site_id':'vod:'+key[:24],'origins':[],'deduplication_basis':'identical_static_site_dependencies_and_relative_base'}
  vgroup[key]['origins'].append({k:v for k,v in e.items() if k not in ['site_raw']})
 x['vod_sites']=list(vgroup.values())
 for e in x['vod_sites']:
  e['origin_count']=len(e['origins'])
  e['origins']=[{'vod_site_id':o['vod_site_id'],'inherits_site_fields':True,**{k:v for k,v in o.items() if k!='vod_site_id' and e.get(k)!=v}} for o in e['origins']]
 # Request provenance can refer directly to already-present fields of its owning
 # candidate/origin. This is a typed reference, not an omitted evidence assertion.
 def compact_record(e):
  e.pop('raw_entry',None) # exactly identical to url_raw by construction
  if 'normalization_basis' in e:e['normalization_basis']={k:v for k,v in e['normalization_basis'].items() if v is not None}
  if 'normalization_null_reasons' in e:
   grouped={}
   for k,v in e['normalization_null_reasons'].items():grouped.setdefault(v,[]).append(k)
   e['normalization_null_reasons']=[{'reason':k,'fields':v} for k,v in grouped.items()]
  if 'request_provenance' in e:
   for p in e['request_provenance']:
    if p.get('path')==e.get('raw_ref'):p.pop('path');p['path_ref']='raw_ref'
    loc=e.get('entry_locator',{}).get('source_locator')
    if p.get('locator')==loc:p.pop('locator');p['locator_ref']='entry_locator.source_locator'
 for e in live:
  # Resolve each origin first, compact using its own referenced fields, then retain
  # only resulting differences from the compact primary candidate.
  resolved=[{**e,**o} for o in e['origins']]
  compact_record(e)
  out=[]
  for o in resolved:
   compact_record(o)
   out.append({'entry_id':o['entry_id'],'inherits_candidate_fields':True,**{k:v for k,v in o.items() if k not in ['entry_id','origins','inherits_candidate_fields'] and e.get(k)!=v}})
  e['origins']=out

 f={'schema_version':'source-hub-feed.v1','batch_id':batch_id,'generated_at':generated_at,'original_inventory':x['original_inventory'],'sources':x['sources'],'live_entries':live,'vod_sites':x['vod_sites'],'checks':checks,'environments':env,'archive_files':[],'summary':{}}
 # Remove byte-identical URL aliases and duplicate locator representations.
 def location_compact(obj):
  if isinstance(obj,dict):
   obj.pop('url_raw',None) # request.url is the exact same string, including query order
   if isinstance(obj.get('entry_locator'),dict):
    loc=obj['entry_locator'];old=loc.pop('source_locator',None)
    if old:
     for k,v in old.items():
      if k not in ['type','line','pointer']:loc[k]=v
   if obj.get('locator_ref')=='entry_locator.source_locator':obj['locator_ref']='entry_locator'
   for v in obj.values():location_compact(v)
  elif isinstance(obj,list):
   for v in obj:location_compact(v)
 location_compact(f)
 for row in f['live_entries']+f['vod_sites']:row.pop('deduplication_basis',None)
 f['deduplication']={'live':'identical_complete_rr1; incomplete_requests_never_merged','vod':'identical_static_site_dependencies_and_relative_base','origins':'field_overlay_on_primary; explicit_values_override; absent_fields_inherit'}
 # Intern repeated non-request objects within this same JSON document. Core
 # playback, naming and identity fields remain inline; no archive lookup needed.
 POOL_FIELDS={'raw_metadata','metadata_status','normalization_basis','normalization_null_reasons','request_provenance','unparsed_dependencies','request_incomplete_reasons','site_raw','incomplete_reasons'}
 counts=collections.Counter();values={}
 def gather(obj):
  if isinstance(obj,dict):
   for k,v in obj.items():
    if k in POOL_FIELDS and isinstance(v,(dict,list)):
     text=json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
     if len(text.encode())>60:counts[text]+=1;values[text]=v
    else:gather(v)
  elif isinstance(obj,list):
   for v in obj:gather(v)
 gather(f);shared={};mapping={}
 for text,count in counts.items():
  key='v'+hashlib.sha256(text.encode()).hexdigest()[:16]
  if count>1 and (len(text.encode())-36)*(count-1)>len(text.encode())+len(key)+8:shared[key]=values[text];mapping[text]=key
 def intern(obj):
  if isinstance(obj,dict):
   for k,v in list(obj.items()):
    if k in POOL_FIELDS and isinstance(v,(dict,list)):
     text=json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
     if text in mapping:obj[k]={'$value_ref':mapping[text]}
    else:intern(v)
  elif isinstance(obj,list):
   for v in obj:intern(v)
 intern(f);f['shared_values']=shared
 f['summary']=summary(f)
 return f
