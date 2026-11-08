"""Deterministic, offline baseline + immutable delta delivery. Python 3.10+."""
import argparse, copy, hashlib, json, os, tempfile
from pathlib import Path
import sys
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"archive/reference"))
from feed_common import strict_load, expand_shared

VERSION='source-hub-delta.v1'
KEYS={'original_inventory':'original_id','sources':'source_id','live_entries':'entry_id','vod_sites':'vod_site_id','checks':'check_id','environments':'env_id','archive_files':'path'}
MAX_PART=8*1024*1024

def encoded(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
def digest(x):return hashlib.sha256(encoded(x)).hexdigest()
def file_hash(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def safe(root,relative):
 p=Path(relative)
 if not isinstance(relative,str) or not relative or '\\' in relative or p.is_absolute() or '..' in p.parts or str(p)!=relative:raise ValueError('unsafe path')
 r=Path(root).resolve(); t=(r/p).resolve()
 if not t.is_relative_to(r):raise ValueError('path escapes root')
 return t

def write_atomic(p,data):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 fd,tmp=tempfile.mkstemp(dir=p.parent,prefix='.'+p.name+'.')
 try:
  with os.fdopen(fd,'wb') as h:h.write(data);h.flush();os.fsync(h.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)

def descriptor(root,path):
 p=safe(root,path);return {'path':path,'byte_count':p.stat().st_size,'sha256':file_hash(p)}
def verified(root,d):
 p=safe(root,d['path'])
 if p.stat().st_size!=d['byte_count'] or file_hash(p)!=d['sha256']:raise ValueError('artifact hash mismatch: '+d['path'])
 return strict_load(p)

def model(feed):
 f=expand_shared(copy.deepcopy(feed))
 if f.get('schema_version')!='source-hub-feed.v1':raise ValueError('unsupported feed')
 entities={};order={}
 for c,key in KEYS.items():
  rows=f.pop(c); m={}
  for row in rows:
   k=row[key]
   if not isinstance(k,str) or not k or k in m:raise ValueError('invalid or duplicate '+c+' key')
   m[k]=row
  entities[c]=m;order[c]=list(m)
 f.pop('shared_values',None)
 return {'metadata':f,'entities':entities,'order':order}

def compact_feed(feed):
 """Encode expanded state using the existing feed's in-document shared values."""
 pool={'raw_metadata','metadata_status','normalization_basis','normalization_null_reasons','request_provenance','unparsed_dependencies','request_incomplete_reasons','site_raw','global_attributes','epg_url_raw','logo_url_raw','raw_ref'}
 shared={}
 def walk(obj):
  if isinstance(obj,dict):
   for k,v in list(obj.items()):
    if k in pool and isinstance(v,(dict,list,str)) and (len(encoded(v))>60 or (k=='normalization_basis' and isinstance(v,dict) and set(v)-{'name'})):
     key='v'+hashlib.sha256(encoded(v)).hexdigest()[:16]
     if key in shared and shared[key]!=v:raise ValueError('shared value collision')
     shared[key]=v;obj[k]={'$value_ref':key}
    else:walk(v)
  elif isinstance(obj,list):
   for v in obj:walk(v)
 feed.pop('shared_values',None)
 # Source/check/inventory inline fields are not all ref-capable in the frozen schema.
 for collection in ('live_entries','vod_sites'):walk(feed.get(collection,[]))
 feed['shared_values']=shared;return feed

def materialize(m):
 f=copy.deepcopy(m['metadata'])
 for c in KEYS:f[c]=[copy.deepcopy(m['entities'][c][k]) for k in m['order'][c]]
 return compact_feed(f)

def initial(root,index):
 if index['schema_version']!=VERSION:raise ValueError('unsupported index')
 f=verified(root,index['baseline']); m=model(f)
 if digest(m)!=index['baseline']['state_sha256']:raise ValueError('baseline state mismatch')
 return {'schema_version':VERSION,'baseline_id':index['baseline']['baseline_id'],'sequence':0,'last_batch_sha256':None,'state_sha256':digest(m),'model':m}

def shape(value,kind):
 from jsonschema import Draft202012Validator
 schema=strict_load(Path(__file__).with_name('source-hub-delta.v1.schema.json'))
 schema['oneOf']=[{'$ref':'#/$defs/'+kind}]
 Draft202012Validator(schema).validate(value)

def validate_index(index):
 shape(index,'index')
 if index.get('schema_version')!=VERSION:raise ValueError('unsupported index')
 bs=index['batches']
 if index['latest_sequence']!=len(bs):raise ValueError('index sequence count mismatch')
 seen=set()
 for n,d in enumerate(bs,1):
  if d['sequence']!=n or d['path'] in seen:raise ValueError('non-contiguous index')
  seen.add(d['path'])

def preserve_history(collection,old,new):
 if old is None:return
 if collection in ('checks','original_inventory','archive_files') and old!=new:
  raise ValueError('protected historical record cannot be changed')
 if collection=='sources':
  retained={(x['sha256'],x['path']) for x in new.get('snapshots',[])}
  if any((x['sha256'],x['path']) not in retained for x in old.get('snapshots',[])):
   raise ValueError('source snapshot history cannot be dropped')
 if collection=='live_entries' and old.get('request_complete') and new.get('request')!=old.get('request'):
  raise ValueError('complete request change requires a new request identity')
 if collection in ('live_entries','vod_sites'):
  key='entry_id' if collection=='live_entries' else 'vod_site_id'
  def origins(row):
   return {x[key]:{**row,**x} for x in row.get('origins',[])}
  prior=origins(old);current=origins(new)
  if not set(prior)<=set(current):raise ValueError('origin history cannot be dropped')
  for k,a in prior.items():
   for field in ('source_id','source_snapshot_sha256','raw_ref','entry_locator','name_raw','url_raw'):
    if a.get(field)!=current[k].get(field):raise ValueError('original identity cannot be rewritten')

def apply_batch(root,state,d):
 if d['sequence']!=state['sequence']+1:raise ValueError('missing batch')
 b=verified(root,d);shape(b,'manifest')
 if b['schema_version']!=VERSION or b['sequence']!=d['sequence'] or b['baseline_id']!=state['baseline_id']:raise ValueError('batch identity mismatch')
 if b['previous_batch_sha256']!=state['last_batch_sha256'] or b['before_state_sha256']!=state['state_sha256']:raise ValueError('chain mismatch')
 m=copy.deepcopy(state['model']);seen=set(); count=0; touched=set()
 for part in b['parts']:
  if part['path'] in seen:raise ValueError('duplicate part')
  seen.add(part['path']); doc=verified(root,part);shape(doc,'part')
  if doc.get('schema_version')!=VERSION or doc.get('sequence')!=b['sequence']:raise ValueError('part identity mismatch')
  if len(doc['operations'])!=part['operation_count']:raise ValueError('part count mismatch')
  for op in doc['operations']:
   count+=1;c=op['collection'];k=op['key']
   if c not in KEYS or (c,k) in touched:raise ValueError('unknown collection or repeated operation')
   touched.add((c,k)); old=m['entities'][c].get(k)
   if (digest(old) if old is not None else None)!=op['before_sha256']:raise ValueError('record precondition mismatch')
   if op['operation']=='upsert':
    v=op['value']
    if v.get(KEYS[c])!=k:raise ValueError('record identity mismatch')
    preserve_history(c,old,v)
    m['entities'][c][k]=v
   elif op['operation']=='retract':
    if not op.get('reason') or old is None:raise ValueError('invalid retraction')
    if c in ('checks','original_inventory','archive_files'):raise ValueError('protected historical record cannot be retracted')
    del m['entities'][c][k]
   else:raise ValueError('unknown operation')
 if count!=b['operation_count']:raise ValueError('batch count mismatch')
 m['metadata']=b['metadata_after'];m['order']=b['order_after']
 for c in KEYS:
  if len(m['order'][c])!=len(set(m['order'][c])) or set(m['order'][c])!=set(m['entities'][c]):raise ValueError('collection order mismatch')
 if digest(m)!=b['after_state_sha256']:raise ValueError('result state mismatch')
 return {'schema_version':VERSION,'baseline_id':state['baseline_id'],'sequence':b['sequence'],'last_batch_sha256':d['sha256'],'state_sha256':digest(m),'model':m}

def load_state(root,index_path='delta/index.json',checkpoint=None):
 index=strict_load(safe(root,index_path));validate_index(index)
 if checkpoint is None:state=initial(root,index)
 else:
  state=copy.deepcopy(checkpoint)
  if state.get('schema_version')!=VERSION or state['baseline_id']!=index['baseline']['baseline_id']:raise ValueError('checkpoint baseline mismatch')
  if digest(state['model'])!=state['state_sha256']:raise ValueError('checkpoint corrupted')
  n=state['sequence']
  if n<0 or n>len(index['batches']):raise ValueError('index rollback or invalid checkpoint')
  if n==0:
   if state['last_batch_sha256'] is not None or state['state_sha256']!=index['baseline']['state_sha256']:raise ValueError('checkpoint zero mismatch')
  else:
   anchor=index['batches'][n-1]
   if anchor['sha256']!=state['last_batch_sha256']:raise ValueError('same sequence changed hash')
   manifest=verified(root,anchor);shape(manifest,'manifest')
   previous_hash=index['batches'][n-2]['sha256'] if n>1 else None
   if manifest['baseline_id']!=state['baseline_id'] or manifest['sequence']!=n or manifest['previous_batch_sha256']!=previous_hash:raise ValueError('checkpoint manifest chain mismatch')
   if manifest['after_state_sha256']!=state['state_sha256']:raise ValueError('checkpoint state does not match committed batch')
 for d in index['batches'][state['sequence']:]:state=apply_batch(root,state,d)
 return state

def initialize(root,feed='feed.json',baseline_commit=None):
 index_path=safe(root,'delta/index.json')
 if index_path.exists():raise ValueError('index already exists')
 f=strict_load(safe(root,feed));m=model(f);d=descriptor(root,feed)
 d.update({'baseline_id':'baseline:'+d['sha256'],'state_sha256':digest(m),'git_commit':baseline_commit,'feed_schema_version':'source-hub-feed.v1'})
 idx={'schema_version':VERSION,'baseline':d,'latest_sequence':0,'batches':[]}
 write_atomic(index_path,encoded(idx)+b'\n');return idx

def _publish(root,feed,retractions=None,max_part_bytes=MAX_PART):
 """Candidate feed must pass the existing full business validator before publish."""
 idx=strict_load(safe(root,'delta/index.json'));state=load_state(root);new=model(strict_load(Path(feed)))
 # A generated_at-only or batch_id-only reassembly is not a business change.
 a=copy.deepcopy(state['model']);z=copy.deepcopy(new)
 for x in (a,z):
  x['metadata'].pop('generated_at',None);x['metadata'].pop('batch_id',None)
 if a==z:return {'changed':False,'sequence':state['sequence']}
 for artifact in new['entities']['archive_files'].values():
  p=safe(root,artifact['path'])
  if p.stat().st_size!=artifact['byte_count'] or file_hash(p)!=artifact['sha256']:raise ValueError('archive bytes mismatch')
 retractions=retractions or {}; ops=[]
 for c in KEYS:
  old=state['model']['entities'][c]; nxt=new['entities'][c]
  for k in sorted(set(old)-set(nxt)):
   reason=retractions.get(c,{}).get(k)
   if not reason:raise ValueError('missing old record requires explicit retraction reason: '+c+'/'+k)
   if c in ('checks','original_inventory','archive_files'):raise ValueError('protected historical record cannot be retracted')
   ops.append({'operation':'retract','collection':c,'key':k,'before_sha256':digest(old[k]),'reason':reason})
  for k,v in sorted(nxt.items()):
   if k not in old or v!=old[k]:
    preserve_history(c,old.get(k),v)
    ops.append({'operation':'upsert','collection':c,'key':k,'before_sha256':digest(old[k]) if k in old else None,'value':v})
 n=state['sequence']+1;chunks=[];current=[]
 empty_size=len(encoded({'schema_version':VERSION,'sequence':n,'operations':[]}))+1
 current_size=empty_size
 for op in ops:
  size=len(encoded(op))
  if empty_size+size>max_part_bytes:raise ValueError('single record exceeds part limit')
  addition=size+(1 if current else 0)
  if current_size+addition>max_part_bytes:
   chunks.append(current);current=[];current_size=empty_size;addition=size
  current.append(op);current_size+=addition
 if current:chunks.append(current)
 # Compute full batch in memory before writing any artifact. Use content hashes in names.
 prefix=f'delta/batches/{n:08d}';artifacts={};parts=[]
 for i,ch in enumerate(chunks):
  raw=encoded({'schema_version':VERSION,'sequence':n,'operations':ch})+b'\n';h=hashlib.sha256(raw).hexdigest();p=f'{prefix}/part-{i:04d}-{h[:16]}.json'
  artifacts[p]=raw;parts.append({'path':p,'byte_count':len(raw),'sha256':h,'operation_count':len(ch)})
 manifest={'schema_version':VERSION,'baseline_id':state['baseline_id'],'sequence':n,'previous_batch_sha256':state['last_batch_sha256'],'before_state_sha256':state['state_sha256'],'after_state_sha256':digest(new),'metadata_after':new['metadata'],'order_after':new['order'],'operation_count':len(ops),'parts':parts}
 raw=encoded(manifest)+b'\n';h=hashlib.sha256(raw).hexdigest();path=f'{prefix}/manifest-{h[:16]}.json';artifacts[path]=raw
 for p in artifacts:
  if safe(root,p).exists():raise ValueError('immutable artifact already exists: '+p)
 for p,raw in artifacts.items():write_atomic(safe(root,p),raw)
 d={'sequence':n,'path':path,'byte_count':len(artifacts[path]),'sha256':h};out=apply_batch(root,state,d)
 if out['model']!=new:raise ValueError('round trip mismatch')
 idx['batches'].append(d);idx['latest_sequence']=n
 write_atomic(safe(root,'delta/index.json'),encoded(idx)+b'\n')
 return {'changed':True,'sequence':n,'operations':len(ops),'parts':len(parts),'state_sha256':out['state_sha256']}

def publish(root,feed,retractions=None,max_part_bytes=MAX_PART):
 lock=safe(root,'delta/.publish.lock');lock.parent.mkdir(parents=True,exist_ok=True)
 try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 except FileExistsError:raise ValueError('publisher locked; verify other process before recovery')
 try:
  os.close(fd)
  return _publish(root,feed,retractions,max_part_bytes)
 finally:lock.unlink()

def sync(root,checkpoint):
 p=Path(checkpoint);p.parent.mkdir(parents=True,exist_ok=True);lock=Path(str(p)+'.lock')
 try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 except FileExistsError:raise ValueError('checkpoint locked; verify other process before recovery')
 try:
  os.close(fd);previous=strict_load(p) if p.exists() else None;state=load_state(root,checkpoint=previous)
  if state!=previous:write_atomic(p,encoded(state)+b'\n')
  return state['sequence']
 finally:lock.unlink()

def main():
 p=argparse.ArgumentParser();p.add_argument('command',choices=['init','publish','validate','sync','materialize']);p.add_argument('--root',default='.');p.add_argument('--feed');p.add_argument('--baseline-commit');p.add_argument('--retractions');p.add_argument('--checkpoint');p.add_argument('--output');a=p.parse_args()
 if a.command=='init':r=initialize(a.root,a.feed or 'feed.json',a.baseline_commit)
 elif a.command=='publish':
  if not a.feed or Path(a.feed).name!='feed.json':raise ValueError('validated candidate must be named feed.json in a staging root')
  from validate_feed import validate
  validate(Path(a.feed).resolve().parent)
  r=publish(a.root,a.feed,strict_load(Path(a.retractions)) if a.retractions else None)
 elif a.command=='sync':r={'sequence':sync(a.root,a.checkpoint)}
 else:
  s=load_state(a.root)
  if a.command=='materialize':
   if not a.output:raise ValueError('--output required')
   if Path(a.output).resolve()==safe(a.root,'feed.json'):raise ValueError('cannot overwrite frozen baseline')
   write_atomic(a.output,encoded(materialize(s['model']))+b'\n')
  r={'sequence':s['sequence'],'state_sha256':s['state_sha256'],'counts':{c:len(v) for c,v in s['model']['entities'].items()}}
 print(json.dumps(r,ensure_ascii=False))
if __name__=='__main__':main()
