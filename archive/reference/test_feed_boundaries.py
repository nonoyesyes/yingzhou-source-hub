import unittest,copy
from validate_feed import variant,exact_coverage
from request_revision import request_revision
from feed_common import expand_shared
from read_feed import live_origins,request_provenance
class Boundaries(unittest.TestCase):
 def test_empty_name_preserved_unknown(self):
  from normalize_names import normalize
  row=normalize({'name_raw':'','group_raw':None})
  self.assertEqual(row['name_normalized'],'');self.assertEqual(row['name_match_status'],'unknown');self.assertIsNone(row['channel_key_hint'])
 def test_shared_string_metadata_lossless(self):
  x={'shared_values':{'v1':'archive/sources/a.json','v2':'https://example.invalid/logo?a=1&b=2'},'raw_ref':{'$value_ref':'v1'},'raw_metadata':{'global_attributes':{'logo':{'$value_ref':'v2'}}}}
  y=expand_shared(x);self.assertEqual(y['raw_ref'],'archive/sources/a.json');self.assertEqual(y['raw_metadata']['global_attributes']['logo'],'https://example.invalid/logo?a=1&b=2')
 def setUp(self):
  self.r={'method':'GET','url':'https://example.invalid/live?a=1&b=2','headers':{},'options':{}};self.t={'request':self.r,'request_complete':True,'request_revision':request_revision(self.r)}
 def check(self,changed,marked):
  r=copy.deepcopy(self.r);r['headers']['user-agent']='test/1' if changed else 'test/0';return {'request_used':r,'request_revision':request_revision(r),'planned_request':self.r,'planned_request_revision':self.t['request_revision'],'request_variant_of':self.t['request_revision'] if marked else None}
 def test_actual_changed_unmarked_rejected(self):
  with self.assertRaises(ValueError):variant(self.check(True,False),self.t)
 def test_actual_changed_marked_accepted(self):variant(self.check(True,True),self.t)
 def test_actual_changed_without_plan_rejected(self):
  c=self.check(True,False);c.update(planned_request=None,planned_request_revision=None)
  with self.assertRaises(ValueError):variant(c,self.t)
 def test_original_accepted(self):variant({'planned_request':self.r,'planned_request_revision':self.t['request_revision'],'request_used':self.r,'request_revision':self.t['request_revision']},self.t)
 def test_floor_lower_bound_accepted(self):exact_coverage(9999,[[0,'9999.999999']])
 def test_rounding_to_target_rejected(self):
  with self.assertRaises(ValueError):exact_coverage(10000,[[0,'9999.999999']],10000,True)
 def test_floor_below_target_cannot_pass(self):
  with self.assertRaises(ValueError):exact_coverage(9999,[[0,'9999.999999']],10000,True)
 def test_exact_target_accepted(self):exact_coverage(10000,[[0,10000]],10000,True)
 def test_union_then_floor(self):exact_coverage(2,[[0,'1.5'],[2,'2.5']])
 def test_binary_boundary(self):exact_coverage(1,[['0.1','1.1']])
class CompactReferences(unittest.TestCase):
 def test_expand(self):self.assertEqual(expand_shared({'shared_values':{'v1':{'a':1}},'x':{'$value_ref':'v1'}})['x'],{'a':1})
 def test_unknown_rejected(self):
  with self.assertRaises(ValueError):expand_shared({'shared_values':{},'x':{'$value_ref':'v1'}})
 def test_cycle_rejected(self):
  with self.assertRaises(ValueError):expand_shared({'shared_values':{'v1':{'$value_ref':'v1'}},'x':{'$value_ref':'v1'}})
 def test_origin_overlay_null(self):
  c={'entry_id':'group','name_raw':'one','request':{'url':'https://example.invalid/a?b=2&a=1'},'origins':[{'entry_id':'original','name_raw':None,'inherits_candidate_fields':True}]}
  o=next(live_origins(c));self.assertIsNone(o['name_raw']);self.assertEqual(o['entry_id'],'original');self.assertEqual(o['url_raw'],c['request']['url'])
 def test_provenance_refs(self):
  c={'raw_ref':'archive/a','entry_locator':{'kind':'line_range','value':'2'},'request_provenance':[{'path_ref':'raw_ref','locator_ref':'entry_locator','kind':'literal_url'}]}
  self.assertEqual(next(request_provenance(c)),{'path':'archive/a','locator':c['entry_locator'],'kind':'literal_url'})
if __name__=='__main__':unittest.main()
