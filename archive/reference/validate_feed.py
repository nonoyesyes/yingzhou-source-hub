"""Offline source-hub-feed.v1 admission. Never fetches sources or plays media."""
import sys,json,hashlib,re,collections
sys.dont_write_bytecode=True
from pathlib import Path,PurePosixPath
from fractions import Fraction
from math import floor
from functools import lru_cache
from jsonschema import Draft202012Validator,FormatChecker
from feed_common import strict_load,summary,expand_shared
from request_revision import request_revision
from read_feed import request_provenance

@lru_cache(maxsize=512)
def read_bytes(p):return p.read_bytes()
@lru_cache(maxsize=256)
def source_lines(raw,encoding):return raw.decode(encoding).splitlines()

def require(ok,msg):
 if not ok:raise ValueError(msg)
def path(root,p):
 q=PurePosixPath(p);require(not q.is_absolute() and '..' not in q.parts and '\\' not in p and str(q)==p,'unsafe path '+p)
 q=(root/p).resolve();require(q.is_relative_to(root.resolve()) and q.is_file(),'missing/escaped path '+p);return q

def variant(c,target):
 for reqkey,revkey in [('planned_request','planned_request_revision'),('request_used','request_revision')]:
  req,rev=c.get(reqkey),c.get(revkey);require((req is None)==(rev is None),'request/revision null mismatch')
  if req is not None:
   require(request_revision(req)==rev,'check revision mismatch')
   require(req['options']=={},'unsupported actual/planned options')
   if target and target.get('request_complete') and rev!=target['request_revision']:require(c.get('request_variant_of')==target['request_revision'],'unmarked actual/planned request variant')
 if c.get('request_variant_of') is not None and target:require(c['request_variant_of']==target.get('request_revision'),'wrong variant parent')

def interval_floor(intervals):
 merged=[]
 for a,b in sorted((Fraction(str(a)),Fraction(str(b))) for a,b in intervals):
  require(a<b,'invalid interval')
  if merged and a<=merged[-1][1]:merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
  else:merged.append((a,b))
 return floor(sum((b-a for a,b in merged),Fraction(0)))
def exact_coverage(declared,intervals,target=None,success=False):
 require(type(declared) is int and declared==interval_floor(intervals),'coverage must equal floor of interval union')
 if success:require(target is not None and declared>=target,'target not reached')

def clean_jsonc(t):
 # Strip comments/trailing commas outside strings, while preserving original bytes in archive.
 out=[];i=0;q=False;esc=False
 while i<len(t):
  c=t[i]
  if q:
   out.append(c)
   if esc:esc=False
   elif c=='\\':esc=True
   elif c=='"':q=False
   i+=1;continue
  if c=='"':q=True;out.append(c);i+=1;continue
  if t[i:i+2]=='//':
   j=t.find('\n',i);i=len(t) if j<0 else j;continue
  if t[i:i+2]=='/*':
   j=t.find('*/',i+2)
   if j<0:raise ValueError('unterminated comment')
   i=j+2;out.append(' ');continue
  if c==',':
   j=i+1
   while j<len(t) and t[j].isspace():j+=1
   if j<len(t) and t[j] in '}]':i+=1;continue
  out.append(c);i+=1
 return ''.join(out)

@lru_cache(maxsize=256)
def json_document(raw):
 text=raw.decode('utf-8-sig')
 try:return json.loads(text)
 except ValueError:return json.loads(clean_jsonc(text))
def json_located(raw,pointer):
 obj=json_document(raw)
 for tok in pointer.split('/')[1:] if pointer else []:
  tok=tok.replace('~1','/').replace('~0','~');obj=obj[int(tok)] if isinstance(obj,list) else obj[tok]
 return obj

def validate(root):
 root=Path(root);f=strict_load(root/'feed.json');schema=strict_load(root/'archive/reference/source-hub-feed.v1.schema.json');Draft202012Validator.check_schema(schema);Draft202012Validator(schema,format_checker=FormatChecker()).validate(f)
 f=expand_shared(f)
 require(f['schema_version']=='source-hub-feed.v1','version mismatch')
 inv=f['original_inventory'];expected={f'{n:03}' for n in range(1,101)}|{f'NEW-{n:03}' for n in range(1,61)};require(len(inv)==160 and {i['original_id'] for i in inv}==expected,'160 original mapping mismatch')
 tables={k:{x[idkey]:x for x in f[k]} for k,idkey in [('sources','source_id'),('live_entries','entry_id'),('vod_sites','vod_site_id'),('checks','check_id'),('environments','env_id')]}
 for k,t in tables.items():require(len(t)==len(f[k]),'duplicate typed ID '+k)
 manifest={x['path']:x for x in f['archive_files']};require(len(manifest)==len(f['archive_files']),'duplicate archive path')
 actual={str(p.relative_to(root)) for p in (root/'archive').rglob('*') if p.is_file()};require(actual==set(manifest),'archive manifest actual set mismatch')
 for p,a in manifest.items():
  raw=path(root,p).read_bytes();require(len(raw)==a['byte_count'] and hashlib.sha256(raw).hexdigest()==a['sha256'],'archive mismatch '+p)
 def evidence(o):
  if isinstance(o,dict):
   for k,v in o.items():
    if k in ['evidence_refs','log_refs']:
     for p in v or []:require(p in manifest,'unmanifested evidence '+p)
    elif k in ['raw_ref','source_snapshot_ref'] and v is not None:require(v in manifest,'unmanifested material '+v)
    else:evidence(v)
  elif isinstance(o,list):
   for x in o:evidence(x)
 evidence(f)
 snapshots=collections.defaultdict(list)
 for p,a in manifest.items():snapshots[a['sha256']].append(p)
 for source in f['sources']:
  for sn in source['snapshots']:
   require(sn['path'] in manifest and manifest[sn['path']]['sha256']==sn['sha256'] and manifest[sn['path']]['byte_count']==sn['byte_count'],'source snapshot bytes mismatch')
 for e in f['live_entries']:
  require(e['source_id'] in tables['sources'],'unknown source')
  require(e['raw_ref'] in manifest and manifest[e['raw_ref']]['sha256']==e['source_snapshot_sha256'],'candidate snapshot bytes mismatch')
  req=e['request'];require(e['content_identity_status']=='not_tested','unproved channel identity')
  if e['request_complete']:require(req is not None and req['options']=={} and request_revision(req)==e['request_revision'],'candidate request mismatch')
  else:require(e['request_revision'] is None,'incomplete revision claim')
  raw=read_bytes(path(root,e['raw_ref']));loc=e['entry_locator']
  if loc['kind']=='line_range':
   a,*b=re.split('[-:]',loc['value']);lines=source_lines(raw,e.get('source_encoding','utf-8-sig'));a=int(a);b=int(b[0]) if b else a;require(1<=a<=b<=len(lines),'bad line locator');segment='\n'.join(lines[a-1:b]);require(req is not None and req['url'] in segment,'locator mismatch')
  elif loc['kind']=='json_pointer':
   require(loc['value']=='' or loc['value'].startswith('/'),'invalid pointer');require(json_located(raw,loc['value'])==e['request']['url'],'JSON candidate URL locator mismatch')
  else:require(False,'unknown locator')
 seen=set()
 for e in f['live_entries']:
  if e['request_complete']:require(e['request_revision'] not in seen,'duplicate complete request');seen.add(e['request_revision'])
  require(e['origin_count']==len(e['origins']),'origin count mismatch')
  for delta in e['origins']:
   origin={**e,**delta}
   for p in request_provenance(origin):
    require('path_ref' not in p and 'locator_ref' not in p and p.get('path') in manifest and isinstance(p.get('locator'),dict),'unresolved request provenance')
   require(origin['source_id'] in tables['sources'],'origin missing source');require(origin['raw_ref'] in manifest and manifest[origin['raw_ref']]['sha256']==origin['source_snapshot_sha256'],'origin snapshot mismatch')
 for v in f['vod_sites']:
  require(v['source_id'] in tables['sources'],'unknown VOD source');require(v['raw_ref'] in manifest and manifest[v['raw_ref']]['sha256']==v['source_snapshot_sha256'],'VOD snapshot mismatch');require(json_located(read_bytes(path(root,v['raw_ref'])),v['entry_locator']['value'])==v['site_raw'],'VOD source locator mismatch')
 for c in f['checks']:
  kind={'source':'sources','live_entry':'live_entries','vod_site':'vod_sites'}[c['target_type']];require(c['target_id'] in tables[kind],'mistyped target');require(c['env_id'] in tables['environments'],'mistyped environment')
  variant(c,tables['live_entries'].get(c['target_id']) if kind=='live_entries' else None)
  if c.get('source_snapshot_ref'):require(manifest[c['source_snapshot_ref']]['sha256']==c['source_snapshot_sha256'],'check snapshot mismatch')
  if c['evidence_kind']=='not_run':require(c['status'] not in ['pass','pass_with_warnings'] and c.get('request_used') is None,'unexecuted check success')
  if c['evidence_kind']=='historical_summary':continue
  runs=c.get('decode_runs',[]);m=c['metrics'];success=c['status'] in ['pass','pass_with_warnings']
  if len(runs)>1:require(m.get('ffmpeg_exit_code') is None,'single exit code on multiple processes')
  for r in runs:
   require(r['log_refs'],'missing decode log')
   for stream in r['streams']:
    if stream not in ['video','audio']:continue
    crc=[p for p in r['log_refs'] if p.endswith('.framecrc')]
    if crc:
     text=path(root,crc[0]).read_text();tb=re.search(r'#tb\s+0:\s+(\d+)/(\d+)',text);require(tb,'missing frame timebase');scale=Fraction(int(tb[1])*1000,int(tb[2]));ints=[]
     for line in text.splitlines():
      if line.startswith('#') or not line.strip():continue
      parts=[x.strip() for x in line.split(',')];ints.append([Fraction(int(parts[2]))*scale,Fraction(int(parts[2])+int(parts[3]))*scale])
     exact_coverage(r[stream+'_coverage_ms'],ints,m.get('target_media_duration_ms'),success)
     require(m['decoded_'+stream+'_duration_ms']==r[stream+'_coverage_ms'],'metrics/run coverage mismatch')
  if success and c['check_type']=='short_decode':
   require(c['sample_complete'] and runs,'decode pass missing sample');require((m.get('covered_media_duration_ms') or 0)>=m['target_media_duration_ms'],'joint coverage missing')
   for st in ['video','audio']:require(any(r['exit_code']==0 and st in r['streams'] and r[st+'_coverage_ms']>=m['target_media_duration_ms'] for r in runs),'decode stage missing')
 require(summary(f)==f['summary'],'summary mismatch')
 return {'valid':True,'schema_version':f['schema_version'],'archive_file_count':len(manifest),'summary':f['summary']}
if __name__=='__main__':print(json.dumps(validate(Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[2]),ensure_ascii=False,indent=2))
