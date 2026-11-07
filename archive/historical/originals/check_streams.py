import urllib.request, urllib.parse, urllib.error, ipaddress, socket, json, time, datetime, subprocess, re, hashlib, pathlib
OUT=pathlib.Path('/workspace/scratch/2746d7d1c495/live_sample_20261107')
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
PL=[('old039','tvbox_100.xlsx','039','https://raw.githubusercontent.com/hujingguang/ChinaIPTV/main/cnTV_AutoUpdate.m3u8'),('old090','tvbox_100.xlsx','090','https://iptv-org.github.io/iptv/countries/cn.m3u'),('old059','tvbox_100.xlsx','059','https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u'),('new051','tvbox_expansion.xlsx','NEW-051','https://raw.githubusercontent.com/svefnz/IPTVN/Files/CNTV-IPV4.m3u')]
all_lists={}; list_results=[]
for key,book,entry,url in PL:
 logs=[];item={'key':key,'workbook':book,'entry':entry,'url':url,'request_log':logs}
 try:
  data,base=fetch(url,logs);s=data.decode('utf-8-sig'); name='';rows=[]
  for line in s.splitlines():
   line=line.strip()
   if line.startswith('#EXTINF:'):name=line.rsplit(',',1)[-1]
   elif line.startswith(('http://','https://')): rows.append({'channel':name,'url':line})
  item.update(http=logs[-1].get('http'),format='Extended M3U' if s.startswith('#EXTM3U') else 'unrecognized',entry_count=len(rows),sha256=hashlib.sha256(data).hexdigest())
  all_lists[key]=(item,rows)
 except Exception as e:item['error']=str(e)
 list_results.append(item)
 print(json.dumps({'playlist':key,'http':item.get('http'),'format':item.get('format'),'entries':item.get('entry_count'),'error':item.get('error')},ensure_ascii=False),flush=True)
plan=[('old039','湖南卫视'),('old039','澳门卫视'),('old039','Good'),('old039','Beautiful Life TV'),('old090','ABN China (720p)'),('old090','CCTV+ 1 (600p) [Not 24/7]'),('old059','CCTV-1综合'),('new051','浙江卫视'),('new051','延边卫视')]
results=[]
for idx,(key,channel) in enumerate(plan,1):
 item={'sample':idx,'playlist_key':key,'channel':channel,'started_utc':utc(),'request_log':[],'decode_target_seconds':10,'concurrency':1}
 t0=time.monotonic(); stage='selection'
 try:
  source,rows=all_lists[key];item.update(workbook=source['workbook'],workbook_entry=source['entry'],playlist_url=source['url'])
  matched=[r for r in rows if r['channel']==channel]
  if len(matched)!=1:raise Stop('Selection missing or ambiguous')
  u=matched[0]['url']; item['stream_url']=u;stage='stream HTTP';data,base=fetch(u,item['request_log'])
  for depth in range(4):
   s=data.decode('utf-8-sig'); lines=s.splitlines()
   if not s.startswith('#EXTM3U'):raise Stop('FORMAT: response is not an HLS manifest')
   if any(x.startswith(('#EXT-X-KEY:','#EXT-X-SESSION-KEY:')) and 'METHOD=NONE' not in x for x in lines):raise Stop('SKIP: encrypted HLS; no key request or DRM work attempted')
   variants=[]
   for i,l in enumerate(lines):
    if l.startswith('#EXT-X-STREAM-INF:'):
     bw=re.search(r'(?:^|,)BANDWIDTH=(\d+)',l.split(':',1)[1]); j=i+1
     while j<len(lines) and (not lines[j].strip() or lines[j].startswith('#')):j+=1
     if j<len(lines):variants.append((int(bw.group(1)) if bw else 0,urllib.parse.urljoin(base,lines[j].strip())))
   if not variants:break
   variants.sort();u=variants[0][1];stage='variant HTTP';data,base=fetch(u,item['request_log'])
  else: raise Stop('LIMIT: variant depth')
  item['media_manifest_url']=base; item['hls_live']=not any(x.startswith('#EXT-X-ENDLIST') for x in lines)
  segments=[];dur=None;init=None
  for l in lines:
   if l.startswith('#EXT-X-BYTERANGE:'):raise Stop('SKIP: byte-range HLS not implemented in short sampler')
   if l.startswith('#EXT-X-MAP:'):
    m=re.search(r'URI="([^"]+)"',l)
    if m:init=urllib.parse.urljoin(base,m.group(1))
   elif l.startswith('#EXTINF:'):dur=float(l.split(':',1)[1].split(',',1)[0])
   elif l.strip() and not l.startswith('#') and dur is not None:
    segments.append((dur,urllib.parse.urljoin(base,l.strip())));dur=None
  if not segments:raise Stop('FORMAT: no complete HLS media segments')
  chosen=[];total=0
  for seg in reversed(segments):
   if total+seg[0]>20.1:break
   chosen.insert(0,seg);total+=seg[0]
   if total>=10:break
  if total<10:raise Stop('LIMIT: not enough complete media for a 10-second sample without exceeding 20 seconds')
  item.update(selected_segment_count=len(chosen),selected_duration_seconds=total)
  stage='segment HTTP';chunks=[]
  if init:chunks.append(fetch(init,item['request_log'],limit=2*1024*1024)[0])
  for dur,u in chosen:
   if time.monotonic()-t0>45:raise Stop('LIMIT: sample acquisition exceeded 45 seconds')
   chunks.append(fetch(u,item['request_log'],limit=12*1024*1024)[0])
  media=b''.join(chunks);item['media_bytes']=len(media)
  if len(media)>30*1024*1024:raise Stop('LIMIT: combined media bytes')
  stage='ffprobe';p=subprocess.run(['ffprobe','-v','error','-protocol_whitelist','pipe','-show_entries','stream=index,codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels:format=format_name,duration','-of','json','-i','pipe:0'],input=media,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20)
  item['ffprobe']={'exit_code':p.returncode,'stderr':p.stderr.decode(errors='replace')[:3000],'metadata':json.loads(p.stdout or b'{}')}
  stage='ffmpeg decode';p=subprocess.run(['ffmpeg','-hide_banner','-v','warning','-protocol_whitelist','pipe','-i','pipe:0','-t','10','-map','0:v:0?','-map','0:a:0?','-progress','pipe:1','-nostats','-f','null','-'],input=media,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20)
  progress=p.stdout.decode(errors='replace'); item['ffmpeg']={'exit_code':p.returncode,'progress':progress[-2500:],'stderr':p.stderr.decode(errors='replace')[:4000]}
  times=re.findall(r'out_time_us=(\d+)',progress); frames=re.findall(r'frame=(\d+)',progress)
  item['decoded_seconds']=round(max([int(x) for x in times] or [0])/1000000,3);item['decoded_frames']=max([int(x) for x in frames] or [0]);item['status']='decoded_10s' if p.returncode==0 and item['decoded_seconds']>=9.8 and item['decoded_frames']>0 else 'decode_incomplete'
 except Exception as e:
  item['failed_stage']=stage;item['error']=str(e)
  if isinstance(e,Stop):item['status']='skipped' if str(e).startswith('SKIP:') else 'not_verified'
  elif isinstance(e,urllib.error.HTTPError):item['status']='http_error'
  elif isinstance(e,socket.gaierror):item['status']='dns_failure'
  elif isinstance(e,subprocess.TimeoutExpired):item['status']='decoder_timeout'
  else:item['status']='network_or_transport_failure'
 item.update(ended_utc=utc(),wall_seconds=round(time.monotonic()-t0,3));results.append(item)
 (OUT/'results.json').write_text(json.dumps({'environment':'dot cloud computer, inherited HTTP(S) proxy; not user device/network','scope':'one-time sample; 10-second local decode target, at most 20 seconds of complete HLS media, serial requests; no account, no keys, no private targets','playlists':list_results,'samples':results},ensure_ascii=False,indent=2))
 print(json.dumps({k:item.get(k) for k in ('sample','channel','status','failed_stage','error','decoded_seconds','decoded_frames','wall_seconds')},ensure_ascii=False),flush=True)
print('RESULTS '+str(OUT/'results.json'),flush=True)
