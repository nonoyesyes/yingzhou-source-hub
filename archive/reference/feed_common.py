import hashlib,json,collections
STATUSES=['not_tested','blocked','unsupported','incomplete','fail','pass','pass_with_warnings','cancelled']
def strict_load(path):
 def pairs(items):
  out={}
  for k,v in items:
   if k in out:raise ValueError('duplicate JSON key: '+k)
   out[k]=v
  return out
 return json.loads(path.read_text('utf-8'),object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('nonfinite '+x)))
def summary(f):
 live=f['live_entries'];sources=f['sources'];checks=f['checks'];tested={c['target_id'] for c in checks if c['target_type']=='live_entry' and c['evidence_kind']=='actual_measurement' and c.get('request_used') is not None}
 return {'original_inventory_count':len(f['original_inventory']),'source_count':len(sources),'live_candidate_count':len(live),'vod_site_count':len(f['vod_sites']),'live_origin_count':sum(e.get('origin_count',1) for e in live),'vod_origin_count':sum(e.get('origin_count',1) for e in f['vod_sites']),'distinct_complete_request_count':len({e['request_revision'] for e in live if e['request_revision'] is not None}),'incomplete_request_candidate_count':sum(not e['request_complete'] for e in live),'check_count':len(checks),'check_status_counts':{s:sum(c['status']==s for c in checks) for s in STATUSES},'check_evidence_kind_counts':dict(sorted(collections.Counter(c['evidence_kind'] for c in checks).items())),'name_match_counts':{s:sum(e['name_match_status']==s for e in live) for s in ['matched','ambiguous','unknown']},'live_candidates_without_actual_media_request':len(live)-len(tested),'fetch_status_counts':dict(sorted(collections.Counter(s['fetch_status'] for s in sources).items())),'parse_status_counts':dict(sorted(collections.Counter(s['parse_status'] for s in sources).items())),'scope':'all_retained_understandable_static_material; no_new_media_network; not_all_inventory_fetched; identity_and_playback_quality_unconfirmed'}

def expand_shared(feed):
 """Resolve exact {$value_ref: key} markers using only this feed's shared_values."""
 shared=feed.get('shared_values',{})
 def walk(value,stack=()):
  if isinstance(value,dict):
   if set(value)=={'$value_ref'}:
    key=value['$value_ref']
    if key not in shared or key in stack:raise ValueError('unknown/cyclic shared value reference')
    return walk(shared[key],stack+(key,))
   return {k:walk(v,stack) for k,v in value.items()}
  if isinstance(value,list):return [walk(v,stack) for v in value]
  return value
 return walk(feed)
