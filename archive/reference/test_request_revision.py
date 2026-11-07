"""Executed cross-language rr1 regression tests. No network requests."""
import copy, hashlib, json, pathlib, subprocess, unittest
from request_revision import canonical_bytes, request_revision, no_duplicate_keys
P=pathlib.Path(__file__).resolve().parent
V=json.loads((P/'request_revision_test_vectors.json').read_text())['test_vectors']
class RR1Tests(unittest.TestCase):
    def test_positive_vectors(self):
        for v in V:
            with self.subTest(vector=v['name']):
                raw=canonical_bytes(v['input'])
                self.assertEqual(raw.decode(),v['canonical_utf8_text'])
                self.assertEqual(len(raw),v['canonical_utf8_byte_count'])
                self.assertEqual(hashlib.sha256(raw).hexdigest(),v['sha256'])
                payload=json.dumps(v['input'],ensure_ascii=True).encode()
                node=subprocess.check_output(['node',str(P/'request_revision.js'),'--canonical'],input=payload)
                self.assertEqual(node,raw)
                self.assertEqual(subprocess.check_output(['node',str(P/'request_revision.js')],input=payload).decode().strip(),v['request_revision'])
                self.assertEqual(subprocess.check_output(['sha256sum'],input=raw).decode().split()[0],v['sha256'])
    def test_invalid_raw_inputs(self):
        cases=json.loads((P/'request_revision_invalid_vectors.json').read_text())
        for v in cases:
            with self.subTest(vector=v['name']):
                with self.assertRaises((ValueError,TypeError)):
                    r=json.loads(v['input_text'],object_pairs_hook=no_duplicate_keys,parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))
                    canonical_bytes(r)
                result=subprocess.run(['node',str(P/'request_revision.js')],input=v['input_text'].encode(),capture_output=True)
                self.assertNotEqual(result.returncode,0)
    def test_url_is_not_normalized(self):
        a=V[0]['input']
        for url in [a['url'].replace('%2F','%2f'),a['url'].replace('&b=2&a=1','&a=1&b=2')]:
            self.assertNotEqual(request_revision(a),request_revision(dict(a,url=url)))
    def test_object_order_does_not_matter(self):
        a=V[0]['input']; self.assertEqual(request_revision(a),request_revision(dict(reversed(list(a.items())))))
if __name__=='__main__': unittest.main(verbosity=2)
