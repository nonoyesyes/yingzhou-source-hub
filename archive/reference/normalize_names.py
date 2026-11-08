"""Versioned conservative alias dictionary; hints are never content verification."""
import re,unicodedata,json
from pathlib import Path
REGISTRY={}
def add(key,name,aliases,category=None,country=None,region=None,language=None):
 REGISTRY[key]={'name':name,'aliases':aliases,'category':category,'country':country,'region':region,'language':language}
for n, label,cat in [(1,'综合','general'),(2,'财经','business'),(3,'综艺','entertainment'),(4,'中文国际','general'),(5,'体育','sports'),(6,'电影','movies'),(7,'国防军事','general'),(8,'电视剧','series'),(9,'纪录','documentary'),(10,'科教','education'),(11,'戏曲','culture'),(12,'社会与法','general'),(13,'新闻','news'),(14,'少儿','kids'),(15,'音乐','music'),(16,'奥林匹克','sports'),(17,'农业农村','general')]:
 add('cn.cctv.'+str(n),'CCTV-'+str(n),['CCTV'+str(n),'CCTV-'+str(n),'CCTV'+str(n)+label,'CCTV-'+str(n)+label,'央视'+str(n)+'套'],cat,'CN',None,None)
add('cn.cctv.5plus','CCTV-5+',['CCTV5+','CCTV-5+','CCTV5PLUS','CCTV5+体育赛事'],'sports','CN')
provinces=[('beijing','北京','Beijing'),('shanghai','东方','Dragon'),('anhui','安徽','Anhui'),('zhejiang','浙江','Zhejiang'),('jiangsu','江苏','Jiangsu'),('hunan','湖南','Hunan'),('hubei','湖北','Hubei'),('guangdong','广东','Guangdong'),('shandong','山东','Shandong'),('henan','河南','Henan'),('hebei','河北','Hebei'),('shanxi','山西','Shanxi'),('shaanxi','陕西','Shaanxi'),('sichuan','四川','Sichuan'),('chongqing','重庆','Chongqing'),('tianjin','天津','Tianjin'),('liaoning','辽宁','Liaoning'),('jilin','吉林','Jilin'),('heilongjiang','黑龙江','Heilongjiang'),('jiangxi','江西','Jiangxi'),('guizhou','贵州','Guizhou'),('yunnan','云南','Yunnan'),('guangxi','广西','Guangxi'),('hainan','海南','Hainan'),('ningxia','宁夏','Ningxia'),('qinghai','青海','Qinghai'),('gansu','甘肃','Gansu'),('xinjiang','新疆','Xinjiang'),('tibet','西藏','Tibet'),('inner-mongolia','内蒙古','Inner Mongolia')]
for key,cn,en in provinces:
 add('cn.'+key+'.satellite',cn+'卫视',[cn+'卫视',en+' Satellite TV',en+' Satellite Television'],'general','CN')
for key,name,aliases,cat,country in [('cgtn','CGTN',['CGTN','CGTN English'],'news','CN'),('phoenix-chinese','凤凰中文台',['凤凰中文','凤凰中文台','鳳凰中文台','Phoenix Chinese'],'general','HK'),('phoenix-info','凤凰资讯台',['凤凰资讯','凤凰资讯台','鳳凰資訊台','Phoenix InfoNews'],'news','HK'),('phoenix-hk','凤凰香港台',['凤凰香港','凤凰香港台','鳳凰香港台'],'general','HK'),('beautiful-life','Beautiful Life TV',['Beautiful Life TV','人間衛視','人间卫视'],'culture','TW'),('bbc-news','BBC News',['BBC News','BBC News HD'],'news','GB'),('cnn','CNN',['CNN','CNN International'],'news','US')]:add(country.lower()+'.'+key,name,aliases,cat,country)
GROUPS={'新闻':'news','News':'news','体育':'sports','Sports':'sports','电影':'movies','Movies':'movies','纪录片':'documentary','Documentary':'documentary','少儿':'kids','Kids':'kids','音乐':'music','Music':'music','教育':'education','Education':'education','文化':'culture','财经':'business','娱乐':'entertainment','Entertainment':'entertainment','综合':'general','General':'general','宗教':'religion','Religious':'religion','影视':'movies','电视剧':'series'}
CATEGORIES=['general','news','sports','movies','series','documentary','kids','music','education','culture','business','entertainment','religion','shopping','lifestyle','other']
def token(x):return re.sub(r'[\s_\-·]','',unicodedata.normalize('NFKC',x)).casefold()
ALIASES={token(a):k for k,v in REGISTRY.items() for a in v['aliases']}
def normalize(e):
 raw=e.get('name_raw');name=re.sub(r'\s+',' ',unicodedata.normalize('NFKC',raw or '')).strip();clean=re.sub(r'(?:\s*(?:HD|FHD|SD|UHD|4K|8K|高清|超清|标清))+$','',name,flags=re.I).strip()
 key=ALIASES.get(token(name)) or ALIASES.get(token(clean));status='matched' if key else 'unknown'
 if re.fullmatch(r'(?:Anhui|Beijing|Hunan|Zhejiang|Guangdong|Jiangsu)\s*TV',clean,re.I) or re.fullmatch(r'CCTV[- ]?4\s*(?:欧洲|美洲|亚洲|Europe|America|Asia).*',clean,re.I):status='ambiguous';key=None
 v=REGISTRY.get(key,{})
 e.update(name_normalized=v.get('name',name),channel_key_hint=key,name_match_status=status,content_identity_status='not_tested')
 category=v.get('category');basis='channel_alias_registry.v1' if category else None
 if not category and e.get('group_raw') in GROUPS:category=GROUPS[e['group_raw']];basis='exact_group_dictionary.v1'
 e.update(category=category,country_code=v.get('country'),region_code=v.get('region'),language_code=v.get('language'))
 e['normalization_basis']={'name':'channel_alias_registry.v1' if key else ('ambiguous_broadcaster_name' if status=='ambiguous' else 'unicode_nfkc_whitespace_only'),'category':basis,'country_code':'channel_alias_registry.v1' if v.get('country') else None,'region_code':None,'language_code':None}
 e['normalization_null_reasons']={k:'no_supported_evidence' for k in ['channel_key_hint','category','country_code','region_code','language_code'] if e.get(k) is None}
 return e
if __name__=='__main__':
 Path(__file__).parent.joinpath('archive/reference/channel_alias_registry.v1.json').write_text(json.dumps({'registry_version':'channel_alias_registry.v1','channels':REGISTRY,'group_category_dictionary':GROUPS,'categories':CATEGORIES,'note':'Name and geography hints only. No visual channel identity verification. Unknown names get no guessed channel key; language is not inferred from script.'},ensure_ascii=False,indent=2)+'\n')
