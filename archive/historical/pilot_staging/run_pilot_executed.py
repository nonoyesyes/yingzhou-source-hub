import urllib.request, urllib.parse, urllib.error, ipaddress, socket, json, time, datetime, subprocess, re, hashlib, pathlib
OUT=pathlib.Path(__file__).parent
def utc(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl): return None
opener=urllib.request.build_opener(NoRedirect())
class Stop(Exception): pass
def validate(u):
 p=urllib.parse.urlsplit(u)
 if p.scheme not in ('http','https') or not p.hostname: raise Stop('SKIP: non HTTP(S) URL')
 if p.username or p.password or p.query or len(p.path)>250 or re.search(r'(token|auth_key|password|session|wssecret)',p.path,re.I): raise Stop('SKIP: credential/signed or query URL')
 host=p.hostname
 try: ips=[str(ipaddress.ip_address(host))]
 except ValueError:
  if '.' not in host or host.endswith(('.local','.internal','.localhost','.lan')): raise Stop('SKIP: non-public hostname')
  # The managed HTTP proxy resolves public hostnames upstream; local DNS is unavailable.
  return ['resolved upstream by managed proxy; IP not observable']
 if not ips or any(not ipaddress.ip_address(x).is_global for x in ips): raise Stop('SKIP: non-public DNS/IP')
 return ips
def fetch(u,logs,limit=1024*1024,timeout=12):
 for n in range(4):
  ips=validate(u); start=time.monotonic(); log={'utc':utc(),'url':u,'resolved_ips':ips,'network':'dot cloud, inherited HTTP(S) proxy; not user network'}; logs.append(log)
  try:
   with opener.open(urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0 (compatible; stream validation)'}),timeout=timeout) as r:
    log.update(http=r.status,content_type=r.headers.get('content-type'),declared_length=r.headers.get('content-length'))
    data=r.read(limit+1); log.update(bytes=len(data),elapsed_seconds=round(time.monotonic()-start,3))
    if len(data)>limit: raise Stop('LIMIT: response too large')
    return data,u
  except urllib.error.HTTPError as e:
   log.update(http=e.code,elapsed_seconds=round(time.monotonic()-start,3))
   if e.code in (301,302,303,307,308) and e.headers.get('location'):
    nxt=urllib.parse.urljoin(u,e.headers['location']); validate(nxt); log['redirect_to']=nxt;u=nxt;continue
   log['error']=str(e); raise
  except Exception as e:
   log.update(error=str(e),elapsed_seconds=round(time.monotonic()-start,3));raise
 raise Stop('LIMIT: redirect depth')
import shutil,openpyxl,platform
from fractions import Fraction

def save(name,data):
 p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True)
 if not isinstance(data,bytes):data=json.dumps(data,ensure_ascii=False,indent=2).encode()
 p.write_bytes(data);return {'path':name,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
# Retain exact original identifiers and byte-identical historical JSON separately.
mapping=[]
for fn,sheet,start,end in [('tvbox_100.xlsx','100条链接',7,106),('tvbox_expansion.xlsx','新增清单',6,65)]:
 data=pathlib.Path('/workspace/shared',fn).read_bytes();ref=save('mapping/'+fn,data)
 w=openpyxl.load_workbook('/workspace/shared/'+fn,read_only=True,data_only=True)
 for n,row in enumerate(w[sheet].iter_rows(min_row=start,max_row=end,values_only=True),start):
  mapping.append({'original_id':str(row[0]).zfill(3),'category':row[1],'name':row[2],'original_url':row[3],'workbook':ref,'sheet':sheet,'row_1_based':n})
save('mapping/original_160.json',mapping)
for fn in ['results.json','results_round2.json','check_streams.py','run_round2.py']:
 save('historical/'+fn,(OUT.parent/'live_sample_20261107'/fn).read_bytes())
save('historical/caveats.json',{'evidence_kind':'historical_summary','upgraded_to_actual_measurement':False,'missing':['original source bytes','complete untruncated stderr/progress','independent audio and video timing'],'truncation':{'ffprobe_stderr_chars':3000,'ffmpeg_stderr_chars':4000,'ffmpeg_progress_tail_chars':2500},'warning':'JSON contains historical measurements, not a draft.2 complete measurement record. Original source bytes cannot be recreated from hashes.'})
versions={k:subprocess.run([k,'-version'],capture_output=True,text=True).stdout for k in ['ffprobe','ffmpeg']}
save('evidence/environment.json',{'utc':utc(),'platform':platform.platform(),'versions':versions,'network':'dot managed HTTP(S) proxy; upstream DNS and egress location unknown; user network not tested','parallelism':1,'media_retention':'temporary memory only; programme media omitted from delivery'})
# Add evidence preservation to each HTTP response, including playlist bytes.
oldfetch=fetch
counter=0
def fetch(u,logs,limit=1024*1024,timeout=12,keep=True):
 global counter
 start=len(logs)
 try:
  data,base=oldfetch(u,logs,limit,timeout)
  counter+=1
  ref=save('raw/http_%03d.bin'%counter,data) if keep else {'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'path':None,'retention':'media bytes discarded after local decoding'}
  logs[-1]['response_evidence']=ref
  return data,base
 finally:
  for l in logs[start:]:l['request_headers']={'User-Agent':'Mozilla/5.0 (compatible; stream validation)'}
PL=[('039','https://raw.githubusercontent.com/hujingguang/ChinaIPTV/main/cnTV_AutoUpdate.m3u8'),('090','https://iptv-org.github.io/iptv/countries/cn.m3u'),('NEW-051','https://raw.githubusercontent.com/svefnz/IPTVN/Files/CNTV-IPV4.m3u')]
sources=[];candidates=[];results=[]
for key,url in PL:
 logs=[];src={'original_id':key,'url':url,'requests':logs,'started_at':utc()};sources.append(src)
 try:
  data,base=fetch(url,logs);src['snapshot']=logs[-1]['response_evidence'];rows=[];name=''
  for n,line in enumerate(data.decode('utf-8-sig').splitlines(),1):
   if line.startswith('#EXTINF:'):name=line.rsplit(',',1)[-1]
   elif line.startswith(('http://','https://')):rows.append({'source_original_id':key,'name':name,'url':line,'source_snapshot_sha256':src['snapshot']['sha256'],'raw_path':src['snapshot']['path'],'locator':{'line_1_based':n,'exact_line':line}})
  src['parsed_candidates']=len(rows);src['status']='pass';src['all_rows']=rows
 except Exception as e:src.update(status='fail',error=str(e))
 src['finished_at']=utc();print('SOURCE',key,src['status'],flush=True)
# Deterministic selection includes first rows plus previously working names, no state quota.
for src in sources:
 rows=src.pop('all_rows',[]);budget=7 if src['original_id']!='NEW-051' else 6
 preferred=[r for r in rows if r['name'] in ['Beautiful Life TV','ABN China (720p)','浙江卫视','CCTV-13新闻','东方卫视']]
 for r in preferred+rows:
  if r not in candidates and sum(x['source_original_id']==src['original_id'] for x in candidates)<budget:candidates.append(r)
for i,r in enumerate(candidates,1):r['candidate_id']='pilot-%02d'%i
save('sources.json',sources);save('candidates.json',candidates)
plan=[r for r in candidates if r['name'] in ['Beautiful Life TV','ABN China (720p)','浙江卫视','CCTV-13新闻','东方卫视']][:5]
for item in plan:
 r={'candidate_id':item['candidate_id'],'name':item['name'],'request_url':item['url'],'source_snapshot_sha256':item['source_snapshot_sha256'],'started_at':utc(),'requests':[],'decode_runs':[],'target_seconds':10,'input_mode':'preloaded_complete_segments','status':'incomplete'};results.append(r);stage='entry_request';t0=time.monotonic()
 try:
  data,base=fetch(item['url'],r['requests'])
  for depth in range(4):
   lines=data.decode('utf-8-sig').splitlines()
   if not lines or not lines[0].startswith('#EXTM3U'):raise Stop('Unsupported non-HLS')
   if any(x.startswith(('#EXT-X-KEY:','#EXT-X-SESSION-KEY:')) and 'METHOD=NONE' not in x for x in lines):raise Stop('Unsupported encrypted HLS, no keys requested')
   variants=[]
   for i,line in enumerate(lines):
    if line.startswith('#EXT-X-STREAM-INF:'):
     bw=re.search(r'BANDWIDTH=(\d+)',line);j=i+1
     while j<len(lines) and (not lines[j] or lines[j].startswith('#')):j+=1
     if j<len(lines):variants.append((int(bw.group(1)) if bw else 0,urllib.parse.urljoin(base,lines[j])))
   if not variants:break
   stage='variant_request';data,base=fetch(sorted(variants)[0][1],r['requests'])
  segs=[];dur=None
  for line in lines:
   if line.startswith(('#EXT-X-MAP:','#EXT-X-BYTERANGE:')):raise Stop('Unsupported fMP4 or byte-range')
   if line.startswith('#EXTINF:'):dur=float(line.split(':',1)[1].split(',')[0])
   elif line and not line.startswith('#') and dur is not None:segs.append((dur,urllib.parse.urljoin(base,line)));dur=None
  chosen=[];seconds=0
  for seg in reversed(segs):
   if seconds+seg[0]>20.1:break
   chosen.insert(0,seg);seconds+=seg[0]
   if seconds>=10:break
  if seconds<10:raise Stop('Insufficient segments within 20 sec acquisition cap')
  stage='media_segment';chunks=[]
  for dur,u in chosen:chunks.append(fetch(u,r['requests'],12*1024*1024,keep=False)[0])
  media=b''.join(chunks);r['input_bytes']=len(media);r['advertised_seconds']=seconds
  if len(media)>30*1024*1024:raise Stop('30 MB cap exceeded')
  stem='evidence/'+item['candidate_id'];stage='media_probe'
  cmd=['ffprobe','-v','warning','-protocol_whitelist','pipe','-show_streams','-show_format','-of','json','-i','pipe:0']
  p=subprocess.run(cmd,input=media,capture_output=True,timeout=25)
  r['ffprobe']={'command':cmd,'exit_code':p.returncode,'stdout':save(stem+'_probe.json',p.stdout),'stderr':save(stem+'_probe.stderr',p.stderr)}
  for kind in ['video','audio']:
   stage=kind+'_decode';started=utc();cmd=['ffmpeg','-hide_banner','-v','warning','-protocol_whitelist','pipe','-i','pipe:0','-t','10','-map','0:'+('v' if kind=='video' else 'a')+':0','-f','framecrc','pipe:1'];p=subprocess.run(cmd,input=media,capture_output=True,timeout=25)
   log=p.stdout.decode(errors='replace');tb=re.search(r'#tb 0: (\d+)/(\d+)',log);intervals=[];frames=0
   for line in log.splitlines():
    if line.startswith('#'):continue
    fields=line.split(',')
    if len(fields)>=6 and tb:
     pts=int(fields[2]);d=int(fields[3]);t=Fraction(int(tb[1]),int(tb[2]));intervals.append((float(pts*t),float((pts+d)*t)));frames+=1
   intervals.sort();merged=[]
   for a,b in intervals:
    if merged and a<=merged[-1][1]+1e-6:merged[-1][1]=max(merged[-1][1],b)
    else:merged.append([a,b])
   covered=sum(b-a for a,b in merged) if intervals else None
   r['decode_runs'].append({'media_kind':kind,'command':cmd,'exit_code':p.returncode,'started_at':started,'finished_at':utc(),'frame_count':frames,'time_base':tb.group(0) if tb else None,'coverage_seconds':covered,'coverage_intervals':merged,'duration_method':'union of actual output frame PTS plus frame duration; not frame count / nominal FPS','stdout':save(stem+'_'+kind+'.framecrc',p.stdout),'stderr':save(stem+'_'+kind+'.stderr',p.stderr)})
  v,a=r['decode_runs'];r['joint_coverage_seconds']=sum(max(0,min(y,w)-max(x,z)) for x,y in v['coverage_intervals'] for z,w in a['coverage_intervals'])
  complete=all(d['exit_code']==0 and d['coverage_seconds'] is not None and d['coverage_seconds']>=9.999 for d in r['decode_runs']) and r['joint_coverage_seconds']>=9.999
  warnings=any((OUT/d['stderr']['path']).stat().st_size for d in r['decode_runs']) or p.returncode!=0
  r['status']=('pass_with_warnings' if warnings else 'pass') if complete else 'incomplete'
  del media,chunks
 except Exception as e:r.update(status='incomplete',stopped_at_stage=stage,error=str(e))
 r['finished_at']=utc();r['wall_seconds']=time.monotonic()-t0;save('measurements.json',results);print('MEASURE',r['name'],r['status'],r.get('error'),flush=True)
save('measurements.json',results)
save('summary.json',{'source_count':len(sources),'candidate_count':len(candidates),'attempted_candidate_count':len(results),'independent_decode_process_count':sum(len(r['decode_runs']) for r in results),'status_counts':{s:sum(r['status']==s for r in results) for s in set(r['status'] for r in results)},'network_response_bytes':sum(l.get('bytes',0) for r in sources+results for l in r['requests']),'synthetic_records':0,'schema_status':'Evidence staging package, not yet mapped to draft.2 protocol record schema','limitations':['Preloaded sample decoding does not establish continuous online playback, TVBox device playback, legal distribution rights, or future availability.','Actual IP and egress geography unknown under managed proxy.','Programme bytes omitted; input SHA/length and complete probe/decode logs retained.']})
