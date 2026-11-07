#!/usr/bin/env python3
"""Static source parser. No network, plugin execution, or source-byte mutation.

parse_snapshot(source, snapshot, data) returns parse_result, raw_live_entries,
vod_sites. IDs are deterministic from source ID, snapshot hash and original
locator. Comments are removed only outside strings; trailing commas are invalid.
"""
import json, re, hashlib
from urllib.parse import urlsplit, urljoin

def sha(b): return hashlib.sha256(b).hexdigest()
raw=[]
vod=[]
_preserve_proxy_candidates=False
attr_re=re.compile(r'([\w.-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s,]+))')
def attrs(t):return {m.group(1):next(x for x in m.groups()[1:] if x is not None) for m in attr_re.finditer(t)}
def comma_split(t):
 q=None
 for i,c in enumerate(t):
  if c in '\"\'':
   if q==c:q=None
   elif q is None:q=c
  elif c==',' and q is None:return t[:i],t[i+1:]
 return t,''
def entry(s,snap,loc,name,url,md,group=None,props=None,global_attrs=None):
 props=props or [];ga=global_attrs or {};headers={};reasons=[];deps=[];url_raw=url
 if md.get('inherited_request_conditions'):
  deps.append(md['inherited_request_conditions']);reasons.append('unresolved_json_inherited_request_conditions')
 request_sources=[{'path':snap['path'],'locator':loc,'kind':'literal_url'}]
 # Do not modify special TVBox URL suffixes or Kodi pipe syntax without proven semantics.
 if '|' in url:reasons.append('unparsed_pipe_request_syntax')
 if '$' in url:reasons.append('unparsed_dollar_suffix_or_url')
 if '#' in url and len(re.findall(r'(?:https?|rtmp|rtsp|udp|rtp|p3p)://',url))>1:reasons.append('unparsed_multi_url_syntax')
 if not re.match(r'^[A-Za-z][A-Za-z0-9+.-]*://',url):reasons.append('relative_or_non_url_request')
 if not url.startswith(('http://','https://')):reasons.append('unsupported_transport_for_http_rr1')
 for p in props:
  st=p['text'];key=st.split(':',1)[0]
  if st.startswith('#EXTVLCOPT:'):
   k,sep,v=st.split(':',1)[1].partition('=');mapping={'http-user-agent':'user-agent','http-referrer':'referer','http-referer':'referer','http-origin':'origin'}
   if k in mapping and sep:
    h=mapping[k]
    if h in headers and headers[h]!=v:reasons.append('conflicting_request_header')
    headers[h]=v;request_sources.append({'path':snap['path'],'locator':{'type':'line','line':p['line']},'kind':'extvlcopt_header'})
   else:deps.append(st);reasons.append('unsupported_vlc_option')
  elif st.startswith('#EXTHTTP:'):
   try:
    hs=json.loads(st.split(':',1)[1]);assert isinstance(hs,dict) and all(isinstance(v,str) for v in hs.values())
    for k,v in hs.items():
     k=k.lower()
     if k in headers and headers[k]!=v:reasons.append('conflicting_request_header')
     headers[k]=v
   except Exception:reasons.append('unparsed_exthttp')
  elif st.startswith(('#KODIPROP:','#EXT-X-')):deps.append(st);reasons.append('unsupported_request_directive')
 for ak,hk in [('http-referrer','referer'),('http-referer','referer'),('http-user-agent','user-agent'),('http-origin','origin')]:
  vv=md.get(ak,ga.get(ak))
  if vv is not None:
   if hk in headers and headers[hk]!=vv:reasons.append('conflicting_request_header')
   headers[hk]=vv;request_sources.append({'path':snap['path'],'locator':loc,'kind':'m3u_attribute_header','attribute':ak})
 for k,v in {**ga,**md}.items():
  if k in ['x-top-first','catchup','catchup-source','catchup-days','catchup-correction'] and v:
   if k=='x-top-first':reasons.append('unsupported_manifest_transform');deps.append({k:v})
 # Distinguish literal missing attributes from intentionally deferred parsing.
 metadata_fields={'group_raw':group or md.get('group-title'),'tvg_id_raw':md.get('tvg-id'),'tvg_name_raw':md.get('tvg-name'),'logo_url_raw':md.get('tvg-logo'),'epg_url_raw':md.get('url-tvg') or md.get('x-tvg-url') or ga.get('url-tvg') or ga.get('x-tvg-url')}
 eid='entry:'+sha((s['source_id']+'\0'+snap['sha256']+'\0'+json.dumps(loc,sort_keys=True)).encode())[:24]
 r={'entry_id':eid,'source_id':s['source_id'],'source_snapshot_sha256':snap['sha256'],'source_archive_path':snap['path'],'entry_locator':loc,'name_raw':name,'url_raw':url_raw,**metadata_fields,'metadata_status':{k:('present' if v is not None else 'absent_in_source') for k,v in metadata_fields.items()},'raw_metadata':{'attributes':md,'global_attributes':ga,'directives':props},'request':{'method':'GET','url':url,'headers':headers,'options':{}},'request_complete':not reasons,'request_incomplete_reasons':sorted(set(reasons)),'request_provenance':request_sources,'unparsed_dependencies':deps,'content_identity_status':'not_tested'}
 raw.append(r)
def parse_m3u(s,snap,text):
 ga={};pending=None;previous=None;props=[];global_props=[];unknown=[];count0=len(raw);last=0
 for n,original in enumerate(text.splitlines(),1):
  line=original.strip();last=n
  if not line:continue
  if line.startswith('#EXTM3U'):ga=attrs(line);continue
  if line.startswith('#EXTINF:'):
   if pending is not None:unknown.append({'line':pending[0],'reason':'extinf_without_url'})
   a,name=comma_split(line);pending=(n,name,attrs(a));props=list(global_props);continue
  if line.startswith('#EXTBURL:'):
   if previous:
    ln,name,md=previous;entry(s,snap,{'type':'line','line':n,'name_line':ln,'role':'backup_url'},name,line[len('#EXTBURL:'):],md,props=props,global_attrs=ga)
   else:unknown.append({'line':n,'reason':'backup_without_channel'})
   continue
  if line.startswith('#'):
   if line.startswith(('#EXTVLCOPT:','#KODIPROP:','#EXTHTTP:','#EXT-X-')):
    item={'line':n,'text':line};props.append(item)
    if pending is None and previous is None:global_props.append(item)
   continue
  if pending:
   ln,name,md=pending;entry(s,snap,{'type':'line','line':n,'name_line':ln,'role':'primary_url'},name,line,md,props=props,global_attrs=ga);previous=pending;pending=None
  else:unknown.append({'line':n,'reason':'url_without_channel_metadata'})
 if pending:unknown.append({'line':pending[0],'reason':'extinf_without_url'})
 return {'format':'m3u','parsed_count':len(raw)-count0,'line_count':last,'unparsed_items':unknown}
def parse_txt(s,snap,text):
 group=None;n0=len(raw);unknown=[]
 for n,line in enumerate(text.splitlines(),1):
  line=line.strip()
  if not line or line.startswith('#'):continue
  name,sep,url=line.partition(',')
  if not sep:unknown.append({'line':n,'reason':'non_entry_text'});continue
  if url.strip()=='#genre#':group=name;continue
  if re.match(r'^(?:https?|rtmp|rtsp|rtp|udp|p3p)://',url):entry(s,snap,{'type':'line','line':n,'role':'txt_entry'},name,url,{},group)
  else:unknown.append({'line':n,'reason':'unsupported_txt_line'})
 return {'format':'tvbox_txt','parsed_count':len(raw)-n0,'line_count':len(text.splitlines()),'unparsed_items':unknown}
def clean_jsonc(text):
 """Replace legal comments outside JSON strings with whitespace, never repair JSON."""
 out=[];i=0;quoted=False;escaped=False
 while i<len(text):
  ch=text[i]
  if quoted:
   out.append(ch)
   if escaped:escaped=False
   elif ch=='\\':escaped=True
   elif ch=='"':quoted=False
   i+=1;continue
  if ch=='"':quoted=True;out.append(ch);i+=1;continue
  if text[i:i+2]=='//':
   j=i+2
   while j<len(text) and text[j] not in '\r\n':j+=1
   out.append(' '*(j-i));i=j;continue
  if text[i:i+2]=='/*':
   j=text.find('*/',i+2)
   if j<0:raise ValueError('unterminated JSONC block comment')
   out.extend(c if c in '\r\n' else ' ' for c in text[i:j+2]);i=j+2;continue
  out.append(ch);i+=1
 return ''.join(out)

def _strict_loads(text):
 def pairs(items):
  d={}
  for key,value in items:
   if key in d:raise ValueError('duplicate JSON object key: '+key)
   d[key]=value
  return d
 def reject(x):raise ValueError('non-JSON number: '+x)
 return json.loads(text,object_pairs_hook=pairs,parse_constant=reject)

def load_jsonc(text):
 text=text.lstrip('\ufeff \t\r\n')
 try:return _strict_loads(text),'json'
 except (ValueError,json.JSONDecodeError):return _strict_loads(clean_jsonc(text)),'jsonc'

def resolve_reference(value,base,pointer):
 """Record literal and safe RFC URL resolution without requesting the resource."""
 item={'pointer':pointer,'raw_value':value,'base_url':base,'resolved_url':None,'resolution_status':'not_a_url_reference','status':'not_fetched'}
 if not isinstance(value,str):return item
 if value.startswith(('http://','https://')):
  item.update(resolved_url=value,resolution_status='absolute')
 elif value.startswith(('//','./','../','/')):
  item.update(resolved_url=urljoin(base,value),resolution_status='relative_resolved')
 elif urlsplit(value).scheme:
  item['resolution_status']='unsupported_scheme_or_runtime_reference'
 elif re.search(r'\.(?:jar|js|json|jsonc|txt|m3u8?|xml|png|jpg)(?:$|[?;])',value):
  item.update(resolved_url=urljoin(base,value),resolution_status='relative_resolved')
 return item

def _ptr(key):return str(key).replace('~','~0').replace('/','~1')

def parse_config(s,snap,text):
 d,fmt=load_jsonc(text)
 if not isinstance(d,dict):return {'format':fmt,'parsed_count':0,'vod_count':0,'unparsed_items':[{'reason':'top_level_not_object'}]}
 n0=len(vod);l0=len(raw);deps=[];unresolved=[];refs=[]
 # Config values are retained structurally, not executed. Lives are not channels.
 for k in ['spider','parses','lives','flags','rules','wallpaper','doh','ads','epg','logo']:
  if k in d:deps.append({'key':k,'value':d[k],'status':'preserved_not_executed'})
 def find_refs(x,p=''):
  if isinstance(x,dict):
   for k,v in x.items():
    pp=p+'/'+_ptr(k)
    if k in {'url','urls','api','ext','spider','epg','logo','wallpaper','tvg-logo','url-tvg','x-tvg-url'}:
     values=v if isinstance(v,list) else [v]
     for j,z in enumerate(values):
      if isinstance(z,str):refs.append(resolve_reference(z,s['original_url'],pp+('/'+str(j) if isinstance(v,list) else '')))
    if isinstance(v,(dict,list)):find_refs(v,pp)
  elif isinstance(x,list):
   for j,v in enumerate(x):find_refs(v,p+'/'+str(j))
 find_refs(d)
 sites=d.get('sites',[])
 if not isinstance(sites,list):unresolved.append({'pointer':'/sites','reason':'sites_not_array'});sites=[]
 for i,r in enumerate(sites):
  vod.append({'site_id':'vod:'+sha((s['source_id']+'\0'+snap['sha256']+'\0/sites/'+str(i)).encode())[:24],'source_id':s['source_id'],'source_snapshot_sha256':snap['sha256'],'source_archive_path':snap['path'],'entry_locator':{'type':'json_pointer','pointer':'/sites/'+str(i)},'name_raw':r.get('name') if isinstance(r,dict) else None,'site_raw':r,'config_dependencies_ref':{'source_id':s['source_id'],'snapshot_sha256':snap['sha256']},'execution_status':'not_tested','request_complete':False,'incomplete_reasons':['plugin_or_site_runtime_not_executed']})
 def walk(x,p,group=None,inherited=None,metadata=None):
  inherited=dict(inherited or {});metadata=dict(metadata or {})
  if isinstance(x,dict):
   for kk,vv in x.items():
    # Only known display metadata is excluded. Unknown conditions stay unresolved.
    if kk in ['group','name','epg','logo','tvg-id','tvg-name','tvg-logo','group-title','url-tvg','x-tvg-url']:
     metadata[p+'/'+_ptr(kk)]=vv
    elif kk not in ['channels','groups','urls','url']:inherited[p+'/'+_ptr(kk)]=vv
   local_group=x.get('group') if isinstance(x.get('group'),str) else group
   md={'json_item':x,'inherited_request_conditions':inherited,'inherited_display_metadata':metadata}
   if 'urls' in x and isinstance(x['urls'],list):
    for j,u in enumerate(x['urls']):
     pp=p+'/urls/'+str(j)
     if not isinstance(u,str):unresolved.append({'pointer':pp,'reason':'non_string_live_url'});continue
     if u.startswith('proxy://') or local_group=='redirect':
      unresolved.append({'pointer':pp,'url':u,'reason':'proxy_or_subscription_not_expanded','reference':resolve_reference(u,s['original_url'],pp),'display_metadata':metadata,'request_conditions':inherited})
     # Preserve literal urls-array candidates, including unsupported proxy schemes.
     if not (u.startswith('proxy://') or local_group=='redirect') or _preserve_proxy_candidates:
      entry(s,snap,{'type':'json_pointer','pointer':pp},x.get('name'),u,md,local_group)
      e=raw[-1]
      if u.startswith('proxy://') or local_group=='redirect':
       e['request_complete']=False;e['request_incomplete_reasons'].append('proxy_or_subscription_not_expanded');e['unparsed_dependencies'].append(unresolved[-1])
      for field,aliases in {'epg_url_raw':['epg','url-tvg','x-tvg-url'],'logo_url_raw':['logo','tvg-logo'],'tvg_id_raw':['tvg-id'],'tvg_name_raw':['tvg-name']}.items():
       found=[(k,v) for k,v in metadata.items() if k.rsplit('/',1)[-1] in aliases and isinstance(v,str)]
       if found:e[field]=sorted(found,key=lambda kv:len(kv[0]),reverse=True)[0][1];e['metadata_status'][field]='present'
   elif isinstance(x.get('url'),str):
    pp=p+'/url';unresolved.append({'pointer':pp,'url':x['url'],'reason':'external_live_dependency_not_fetched','reference':resolve_reference(x['url'],s['original_url'],pp),'display_metadata':metadata,'request_conditions':inherited})
   for k,v in x.items():
    if k in ['channels','groups']:walk(v,p+'/'+k,local_group or x.get('name') or group,inherited,metadata)
  elif isinstance(x,list):
   for i,v in enumerate(x):walk(v,p+'/'+str(i),group,inherited,metadata)
  elif x is not None:unresolved.append({'pointer':p,'reason':'unsupported_live_configuration_shape'})
 walk(d.get('lives',[]),'/lives')
 return {'format':fmt,'parsed_count':len(raw)-l0,'vod_count':len(vod)-n0,'sites_item_count':len(sites),'lives_config_count':len(d['lives']) if isinstance(d.get('lives'),list) else int('lives' in d),'config_dependencies':deps,'reference_values':refs,'unparsed_items':unresolved,'keys_preserved_in_source':list(d)}

def detect_format(text):
 text=text.lstrip('\ufeff \t\r\n')
 if text.startswith('#EXTM3U'):return 'm3u'
 # Detect commented JSON before TXT. Invalid JSON remains unsupported, not TXT.
 probe=clean_jsonc(text).lstrip() if text.startswith(('//','/*')) else text
 if probe.startswith(('{','[')):return 'json_config'
 return 'tvbox_txt'

def parse_snapshot(source,snapshot,data,preserve_proxy_candidates=False):
 """Parse one retained UTF-8 snapshot. Exceptions identify unsupported input."""
 global raw,vod,_preserve_proxy_candidates
 raw=[];vod=[];_preserve_proxy_candidates=preserve_proxy_candidates
 try:
  text=data.decode('utf-8-sig') if isinstance(data,bytes) else data
  fmt=detect_format(text)
  if fmt=='m3u':result=parse_m3u(source,snapshot,text)
  elif fmt=='json_config':result=parse_config(source,snapshot,text)
  else:result=parse_txt(source,snapshot,text)
  status='partial' if result.get('unparsed_items') else 'complete'
 except (ValueError,UnicodeError,TypeError) as exc:
  raw=[];vod=[];status='unsupported'
  result={'format':'unsupported','parsed_count':0,'vod_count':0,'unparsed_items':[{'reason':'static_parse_failed','error':type(exc).__name__+': '+str(exc)}]}
 return {'parse_result':result,'parse_status':status,'raw_live_entries':raw,'vod_sites':vod}
