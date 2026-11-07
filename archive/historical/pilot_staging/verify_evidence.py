import json,hashlib,pathlib
p=pathlib.Path(__file__).parent
sources=json.loads((p/'sources.json').read_text());candidates=json.loads((p/'candidates.json').read_text());mapping=json.loads((p/'mapping/original_160.json').read_text());checks=0
for s in sources:
 if 'snapshot' in s:
  ref=s['snapshot'];b=(p/ref['path']).read_bytes();assert hashlib.sha256(b).hexdigest()==ref['sha256'];assert len(b)==ref['bytes'];checks+=1
for c in candidates:
 b=(p/c['raw_path']).read_bytes();assert hashlib.sha256(b).hexdigest()==c['source_snapshot_sha256'];assert b.decode('utf-8-sig').splitlines()[c['locator']['line_1_based']-1]==c['locator']['exact_line']==c['url'];checks+=1
assert len(mapping)==160 and len(set(x['original_id'] for x in mapping))==160
for m in mapping:
 r=m['workbook'];assert hashlib.sha256((p/r['path']).read_bytes()).hexdigest()==r['sha256']
for r in json.loads((p/'measurements.json').read_text()):
 for d in r['decode_runs']:
  for k in ['stdout','stderr']:
   ref=d[k];b=(p/ref['path']).read_bytes();assert hashlib.sha256(b).hexdigest()==ref['sha256'];assert len(b)==ref['bytes'];checks+=1
print(json.dumps({'passed':True,'source_and_locator_and_decode_log_checks':checks,'original_mapping_count':len(mapping),'draft2_business_acceptance':'NOT RUN: staging package'},indent=2))
