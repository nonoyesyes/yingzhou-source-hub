'use strict';
// rr1: direct ordered text serialization, never reconstructed-object enumeration.
const crypto = require('crypto');
const TOKEN = /^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/;
const HEADER = /^[!#$%&'*+.^_`|~0-9a-z-]+$/;
function parseStrict(text) {
  let p = 0;
  const ws = () => { while (/[\x20\t\r\n]/.test(text[p] || '\uFFFF')) p++; };
  const fail = m => { throw new Error(m + ' at ' + p); };
  function string() {
    const start = p++;
    while (p < text.length) {
      const c = text[p++];
      if (c === '"') return JSON.parse(text.slice(start,p));
      if (c === '\\') p++;
    }
    fail('Unterminated string');
  }
  function value() {
    ws(); const c = text[p];
    if (c === '"') return string();
    if (c === '{') {
      p++; ws(); const out = Object.create(null), seen = new Set();
      if (text[p] === '}') { p++; return out; }
      while (true) {
        ws(); if (text[p] !== '"') fail('Expected key');
        const key = string(); if (seen.has(key)) fail('Duplicate JSON key'); seen.add(key);
        ws(); if (text[p++] !== ':') fail('Expected colon'); out[key] = value(); ws();
        const end = text[p++]; if (end === '}') return out; if (end !== ',') fail('Expected comma');
      }
    }
    if (c === '[') {
      p++; ws(); const out = []; if (text[p] === ']') { p++; return out; }
      while (true) { out.push(value()); ws(); const end = text[p++]; if (end === ']') return out; if (end !== ',') fail('Expected comma'); }
    }
    for (const [token,result] of [['true',true],['false',false],['null',null]]) {
      if (text.startsWith(token,p)) { p += token.length; return result; }
    }
    const m = text.slice(p).match(/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/);
    if (!m) fail('Invalid JSON value');
    if (/[.eE]/.test(m[0])) fail('Floating-point syntax forbidden');
    const n = Number(m[0]); if (!Number.isSafeInteger(n)) fail('Integer outside safe range'); p += m[0].length; return n;
  }
  const out = value(); ws(); if (p !== text.length) fail('Trailing JSON input'); return out;
}
function isObject(x) { return x !== null && typeof x === 'object' && !Array.isArray(x); }
function validate(x) {
  if (x === null || typeof x === 'boolean') return;
  if (typeof x === 'number') { if (!Number.isSafeInteger(x)) throw new Error('Unsafe or noninteger number'); return; }
  if (typeof x === 'string') {
    for (let i=0;i<x.length;i++) {
      const c=x.charCodeAt(i);
      if (c>=0xD800 && c<=0xDBFF) { const d=x.charCodeAt(++i); if (!(d>=0xDC00 && d<=0xDFFF)) throw new Error('Lone surrogate'); }
      else if (c>=0xDC00 && c<=0xDFFF) throw new Error('Lone surrogate');
    }
    return;
  }
  if (Array.isArray(x)) { for(const y of x) validate(y); return; }
  if (isObject(x)) { for (const k of Object.keys(x)) { if (!/^[\x20-\x7e]+$/.test(k)) throw new Error('Invalid key'); validate(x[k]); } return; }
  throw new Error('Non-JSON value');
}
function orderedText(x) {
  if (Array.isArray(x)) return '[' + x.map(orderedText).join(',') + ']';
  if (isObject(x)) return '{' + Object.keys(x).sort().map(k => JSON.stringify(k)+':'+orderedText(x[k])).join(',') + '}';
  return JSON.stringify(x);
}
function canonicalBytes(request) {
  if (!isObject(request) || Object.keys(request).sort().join(',') !== 'headers,method,options,url') throw new Error('Invalid request fields');
  if (typeof request.method !== 'string' || !TOKEN.test(request.method)) throw new Error('Invalid method');
  if (typeof request.url !== 'string' || !request.url) throw new Error('Invalid URL');
  if (!isObject(request.headers) || !isObject(request.options)) throw new Error('headers/options must be objects');
  for (const [k,v] of Object.entries(request.headers)) if (!HEADER.test(k) || typeof v !== 'string' || /[\r\n]/.test(v)) throw new Error('Invalid header');
  validate(request); return Buffer.from(orderedText(request),'utf8');
}
function requestRevision(request) { return 'rr1:sha256:' + crypto.createHash('sha256').update(canonicalBytes(request)).digest('hex'); }
module.exports = {parseStrict, canonicalBytes, requestRevision};
if (require.main === module) {
  try {
    const req = parseStrict(require('fs').readFileSync(0,'utf8'));
    process.stdout.write(process.argv.includes('--canonical') ? canonicalBytes(req) : requestRevision(req)+'\n');
  } catch (e) { process.stderr.write(e.message+'\n'); process.exitCode=1; }
}
