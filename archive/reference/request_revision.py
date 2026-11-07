"""rr1 reference implementation. Input is a complete effective static request only."""
import hashlib, json, re, sys
SAFE=9007199254740991
TOKEN=re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
HEADER=re.compile(r"^[!#$%&'*+.^_`|~0-9a-z-]+$")
def no_duplicate_keys(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError('Duplicate JSON key: '+key)
        result[key]=value
    return result

def validate_json(value):
    if value is None or isinstance(value,bool): return
    if isinstance(value,int):
        if not -SAFE<=value<=SAFE: raise ValueError('Integer outside safe range')
    elif isinstance(value,str):
        if any(0xD800<=ord(c)<=0xDFFF for c in value): raise ValueError('Lone surrogate')
    elif isinstance(value,list):
        for item in value: validate_json(item)
    elif isinstance(value,dict):
        for key,item in value.items():
            if not isinstance(key,str) or not key or not all(32<=ord(c)<=126 for c in key):
                raise ValueError('Keys must be nonempty printable ASCII')
            validate_json(item)
    else: raise ValueError('Floating point and non-JSON types are forbidden in rr1')

def canonical_bytes(request):
    if not isinstance(request,dict) or set(request)!={'method','url','headers','options'}:
        raise ValueError('Request must contain exactly method, url, headers, options')
    if not isinstance(request['method'],str) or not TOKEN.fullmatch(request['method']):
        raise ValueError('Invalid HTTP method token')
    if not isinstance(request['url'],str) or not request['url']:
        raise ValueError('URL must be a nonempty exact string')
    if not isinstance(request['headers'],dict) or not isinstance(request['options'],dict):
        raise ValueError('headers/options must be objects')
    for key,value in request['headers'].items():
        if not HEADER.fullmatch(key) or not isinstance(value,str) or '\r' in value or '\n' in value:
            raise ValueError('Header names must be lowercase tokens; values must be CR/LF-free exact strings')
    validate_json(request)
    return json.dumps(request,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')

def request_revision(request):
    return 'rr1:sha256:'+hashlib.sha256(canonical_bytes(request)).hexdigest()

if __name__=='__main__':
    request=json.load(sys.stdin,object_pairs_hook=no_duplicate_keys,parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))
    sys.stdout.write(request_revision(request)+'\n')
