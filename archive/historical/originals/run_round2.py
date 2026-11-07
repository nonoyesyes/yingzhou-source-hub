import pathlib,json,re,urllib.parse
P=pathlib.Path('/workspace/scratch/2746d7d1c495/live_sample_20261107')
s=(P/'check_streams.py').read_text();head=s[:s.index('PL=[')]
candidates=json.load(open(P/'round2_candidates.json'))
all_lists={p['key']:(p,p.get('eligible_rows',[])) for p in candidates}
requested=[
('old041','CCTV13','http://ali-m-l.cztv.com/channels/lantian/channel21/1080p.m3u8'),
('old041','东方卫视','http://bp-resource-dfl.bestv.cn/148/3/video.m3u8'),
('old041','东南卫视','http://live.zohi.tv/video/s10001-fztv-3/index.m3u8'),
('old041','山西卫视','http://m3u8.channel.wsrtv.com.cn/cms/videos/nmip-media/channellive/channel7/playlist.m3u8'),
('old041','黑龙江卫视','https://idclive.hljtv.com:4430/live/hljws_own.m3u8'),
('old041','内蒙古卫视','http://play1-qk.nmtv.cn/live/1769652018126032.m3u8'),
('old041','安多卫视','https://liveout.xntv.tv/a65jur/96iln2.m3u8'),
('old041','苏州4K','https://tylive.kan0512.com/norecord/csztv4k_4k.m3u8'),
('old041','山东教育','https://test1.live.sdetv.com.cn/live/dianshizhibo/playlist.m3u8'),
('old078','CCTV-2 财经','http://liveop.cctv.cn/hls/CCTV28bee868714f04ea2af79947bb9b46fc3H/playlist.m3u8'),
('old078','CCTV-6 电影','http://mobilelive-ds.ysp.cctv.cn/ysp/2013693901.m3u8'),
('old078','宁夏卫视','https://hls.ningxiahuangheyun.com/live/nxws1M.m3u8'),
('old078','山东卫视','http://lives.jnnews.tv/video/s10001-SDTV/index.m3u8'),
('old078','兵团卫视','https://liveout.btzx.com.cn/62ds9e/yil08g.m3u8'),
('old090','Guangdong Satellite TV','https://h5cul1yar48um3t.wcetv.com/hls/gdsatellite.m3u8'),
('old090','Hebei TV (2160p)','https://event.pull.hebtv.com/live/live101.m3u8'),
('old090','Shenzhen Satellite TV (2160p)','https://livepull-tcms.sztv.com.cn/live/sz4Kpgm.m3u8'),
('old090','Yunnan Satellite TV (1080p)','https://hwapi.yunshicloud.com/8xughf/e0bx15.m3u8'),
('old090','Jiangsu Satellite TV (1080p)','http://39.134.24.166/dbiptv.sn.chinamobile.com/PLTV/88888890/224/3221226200/index.m3u8'),
('old090','Anhui TV','https://restream.pdtvhd.com/memfs/c1cd2ed0-3b2b-4c25-af98-a7fb0b1eb130.m3u8'),
('new049','CCTV3','https://piccpndali.v.myalicdn.com/audio/cctv3_2.m3u8'),
('new049','CCTV4','https://play.kankanlive.com/live/1698234936258960.m3u8'),
('new049','CCTV5','http://gmxw.7766.org:808/hls/93/index.m3u8'),
('new049','CCTV7','http://8.138.7.223/tv/cctv7.m3u8'),
('new049','CCTV10','https://play.kankanlive.com/live/1698423445959919.m3u8')]
def norm(u):
 p=urllib.parse.urlsplit(u);return urllib.parse.urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path,p.query,''))
old=json.load(open(P/'results.json'));used={norm(x['stream_url']) for x in old['samples']};plan=[]
for key,ch,u in requested:
 if norm(u) in used:raise ValueError('Duplicate line '+ch)
 matches=[x for x in all_lists[key][1] if x['channel'].strip()==ch and x['url']==u]
 if not matches:raise ValueError('No observed source row '+ch)
 used.add(norm(u));plan.append((key,ch,u))
assert len(plan)==25
(P/'round2_selected.json').write_text(json.dumps([{'key':k,'channel':c,'url':u} for k,c,u in plan],ensure_ascii=False,indent=2))
list_results=[{k:v for k,v in p.items() if k!='eligible_rows'} for p in candidates if p['key'] in {x[0] for x in plan}]
code=s[s.index('\nresults=[]')+1:]
code=code.replace('for idx,(key,channel) in enumerate(plan,1):','for idx,(key,channel,selected_url) in enumerate(plan,10):')
code=code.replace("matched=[r for r in rows if r['channel']==channel]", "matched=[r for r in rows if r['channel'].strip()==channel and r['url']==selected_url][:1]")
code=code.replace("OUT/'results.json'", "OUT/'results_round2.json'")
code=code.replace("item['hls_live']=not any(x.startswith('#EXT-X-ENDLIST') for x in lines)", "item['hls_endlist_absent']=not any(x.startswith('#EXT-X-ENDLIST') for x in lines)")
oldstatus="item['status']='decoded_10s' if p.returncode==0 and item['decoded_seconds']>=9.8 and item['decoded_frames']>0 else 'decode_incomplete'"
newstatus="item['status']=('decoded_10s' if item.get('hls_endlist_absent') else 'decoded_vod_10s') if p.returncode==0 and item['decoded_seconds']>=9.8 and item['decoded_frames']>0 else ('decoded_audio_10s' if p.returncode==0 and item['decoded_seconds']>=9.8 else 'decode_incomplete')"
code=code.replace(oldstatus,newstatus)
exec(compile(head+'\n'+code,'round2 generated sampler','exec'))
