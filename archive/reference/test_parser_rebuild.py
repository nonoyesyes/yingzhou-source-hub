#!/usr/bin/env python3
"""Offline regressions for JSONC detection and display-group request semantics.

Run from a checkout: python archive/reference/test_parser_rebuild.py --root .
Optional --baseline-feed FILE avoids reading the review commit from local Git.
No command in this test fetches anything or executes third-party source code.
"""
import argparse
import copy
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.dont_write_bytecode = True
from static_parser import parse_snapshot, clean_jsonc, load_jsonc, detect_format
from read_feed import load_feed, live_origins, vod_origins
from feed_common import expand_shared, summary
from request_revision import request_revision

BASELINE = 'afd60eb69827b82b7bb562147ba480c0bb10a8ba'
EXPECTED = {'source:NEW-015': 276, 'source:NEW-016': 29,
            'source:NEW-018': 108, 'source:extra-957225aa1a904c8a': 280}
GROUP_SOURCE = 'source:extra-ac27c1ba25e4bb35'
ARGS = None
F = OLD = None

def source(sid):
    return next(s for s in F['sources'] if s['source_id'] == sid)

def parse_source(sid):
    s = source(sid); snap = s['snapshots'][0]
    return parse_snapshot(s, snap, (ARGS.root / snap['path']).read_bytes())

def synth(doc):
    text = doc if isinstance(doc, str) else json.dumps(doc, ensure_ascii=False)
    raw = text.encode('utf-8')
    s = {'source_id': 'source:regression', 'original_url': 'https://example.invalid/config/main.json'}
    snap = {'path': 'archive/sources/fixture.jsonc', 'sha256': hashlib.sha256(raw).hexdigest()}
    return parse_snapshot(s, snap, raw)

class ParserRegressions(unittest.TestCase):
    def test_four_actual_jsonc_sites_and_lives(self):
        total = 0
        for sid, count in EXPECTED.items():
            with self.subTest(source=sid):
                result = parse_source(sid)
                self.assertEqual(result['parse_result']['format'], 'jsonc')
                self.assertEqual(len(result['vod_sites']), count)
                self.assertEqual(result['parse_result']['sites_item_count'], count)
                self.assertEqual(result['parse_result']['lives_config_count'], 1)
                lives = [d for d in result['parse_result']['config_dependencies'] if d['key'] == 'lives']
                self.assertEqual(len(lives), 1)
                self.assertEqual(len(lives[0]['value']), 1)
                self.assertTrue(result['parse_result']['unparsed_items'])
                self.assertFalse(any(e['request_complete'] for e in result['raw_live_entries']))
                total += count
        self.assertEqual(total, 693)

    def test_bom_whitespace_comments_detected(self):
        text = '\ufeff \n /* prefix */\n// heading\n{"sites": [], "lives": []}'
        self.assertEqual(detect_format(text), 'json_config')
        self.assertEqual(synth(text)['parse_result']['format'], 'jsonc')

    def test_string_comment_markers_and_escapes_exact(self):
        value = {'url': 'https://example.invalid/a//b?q=/*not-comment*/&x=1',
                 'quoted': 'a\\"//not-comment', 'slash': '\\/', 'unicode': '节目'}
        text = '\ufeff /* start */\n' + json.dumps(value, ensure_ascii=False) + '\n// end'
        self.assertEqual(load_jsonc(text)[0], value)
        self.assertEqual(json.loads(clean_jsonc(text).lstrip('\ufeff \t\r\n')), value)

    def test_trailing_comma_not_repaired(self):
        for text in ['{"sites":[],}', '/*x*/ {"sites":[1,]}']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                load_jsonc(text)

    def test_unterminated_comment_rejected(self):
        with self.assertRaises(ValueError):
            load_jsonc('/* not closed {"sites":[]}')

    def test_group_is_display_and_preserved(self):
        result = synth({'lives':[{'group':'📺央视频道','channels':[{'name':'CCTV-1','urls':['https://example.invalid/a?b=2&a=1']}]}]})
        e = result['raw_live_entries'][0]
        self.assertTrue(e['request_complete'])
        self.assertEqual(e['group_raw'], '📺央视频道')
        self.assertEqual(e['request']['url'], 'https://example.invalid/a?b=2&a=1')
        self.assertNotIn('unresolved_json_inherited_request_conditions', e['request_incomplete_reasons'])
        self.assertIn('📺央视频道', json.dumps(e['raw_metadata'], ensure_ascii=False))

    def test_actual_1230_group_records_reassessed(self):
        result = parse_source(GROUP_SOURCE)
        self.assertEqual(len(result['raw_live_entries']), 1230)
        for e in result['raw_live_entries']:
            self.assertTrue(e['request_complete'])
            self.assertEqual(e['request']['options'], {})
            self.assertIsInstance(e['group_raw'], str)
            self.assertTrue(e['group_raw'])
            self.assertTrue(request_revision(e['request']).startswith('rr1:'))

    def test_real_unknown_conditions_not_cleared(self):
        for key, value in [('headers', {'User-Agent':'required'}), ('options', {'foo': True}), ('runtime', 'plugin')]:
            with self.subTest(condition=key):
                r = synth({'lives':[{'group':'display',key:value,'channels':[{'name':'A','urls':['https://example.invalid/a']}]}]})
                e = r['raw_live_entries'][0]
                self.assertFalse(e['request_complete'])
                self.assertIn('unresolved_json_inherited_request_conditions', e['request_incomplete_reasons'])
                self.assertTrue(e['unparsed_dependencies'])

    def test_proxy_and_subscription_are_not_direct_complete_requests(self):
        r = synth({'lives':[{'group':'redirect','channels':[{'name':'live','urls':['proxy://do=live&type=txt&ext=abc']}]}]})
        self.assertFalse(any(e['request_complete'] for e in r['raw_live_entries']))
        self.assertTrue(r['parse_result']['unparsed_items'])
        r = synth({'lives':[{'name':'live','url':'../live/channels.txt'}]})
        self.assertEqual(r['raw_live_entries'], [])
        ref = next(x for x in r['parse_result']['reference_values'] if x['pointer'] == '/lives/0/url')
        self.assertEqual(ref['raw_value'], '../live/channels.txt')
        self.assertEqual(ref['base_url'], 'https://example.invalid/config/main.json')
        self.assertEqual(ref['resolved_url'], 'https://example.invalid/live/channels.txt')
        self.assertEqual(ref['status'], 'not_fetched')

    def test_actual_epg_logo_relative_dependencies(self):
        result = parse_source('source:NEW-015')['parse_result']
        refs = {r['pointer']:r for r in result['reference_values']}
        self.assertEqual(refs['/lives/0/url']['raw_value'], './sub/live/tv.txt')
        self.assertEqual(refs['/lives/0/url']['resolved_url'], 'https://raw.githubusercontent.com/liu673cn/bug/main/vod/sub/live/tv.txt')
        self.assertIn('{name}', refs['/lives/0/epg']['raw_value'])
        self.assertIn('{name}', refs['/lives/0/logo']['raw_value'])
        for r in refs.values():
            self.assertEqual(r['status'], 'not_fetched')

class RebuiltFeedRegressions(unittest.TestCase):
    def test_original_inventory_unchanged(self):
        self.assertEqual(F['original_inventory'], OLD['original_inventory'])
        self.assertEqual(len(F['original_inventory']), 160)

    def test_all_baseline_live_origins_values_preserved(self):
        old = {o['entry_id']:o for e in OLD['live_entries'] for o in live_origins(e)}
        new = {o['entry_id']:o for e in F['live_entries'] for o in live_origins(e)}
        self.assertTrue(old.keys() <= new.keys())
        for eid, o in old.items():
            n = new[eid]
            for key in ['request','name_raw','source_id','source_snapshot_sha256','raw_ref','entry_locator','group_raw']:
                self.assertEqual(n[key], o[key], (eid, key))

    def test_all_baseline_vod_origins_values_preserved(self):
        old = {o['vod_site_id']:o for e in OLD['vod_sites'] for o in vod_origins(e)}
        new = {o['vod_site_id']:o for e in F['vod_sites'] for o in vod_origins(e)}
        self.assertTrue(old.keys() <= new.keys())
        for eid, o in old.items():
            for key in ['site_raw','name_raw','source_id','source_snapshot_sha256','raw_ref','entry_locator']:
                self.assertEqual(new[eid][key], o[key], (eid,key))

    def test_checks_observed_facts_unchanged(self):
        old = {c['check_id']:c for c in OLD['checks']};new = {c['check_id']:c for c in F['checks']}
        self.assertEqual(old.keys(), new.keys()); self.assertEqual(len(new), 39)
        # Only deterministic target/group linkage can change during regrouping.
        mutable = {'target_id','candidate_entry_ids','request_variant_of'}
        for cid, c in old.items():
            self.assertEqual({k:v for k,v in c.items() if k not in mutable},
                             {k:v for k,v in new[cid].items() if k not in mutable}, cid)
        actual = [c for c in F['checks'] if c['evidence_kind'] != 'historical_summary']
        self.assertEqual(sum(c['status']=='incomplete' for c in actual), 2)
        self.assertEqual(sum(c['status']=='blocked' for c in actual), 3)

    def test_immutable_archives_and_snapshot_hashes(self):
        new = {x['path']:x for x in F['archive_files']}
        for old in OLD['archive_files']:
            if not old['path'].startswith('archive/reference/'):
                self.assertEqual(new[old['path']], old, old['path'])
                data = (ARGS.root / old['path']).read_bytes()
                self.assertEqual(hashlib.sha256(data).hexdigest(), old['sha256'])
        for s in F['sources']:
            for sn in s['snapshots']:
                self.assertEqual(hashlib.sha256((ARGS.root/sn['path']).read_bytes()).hexdigest(), sn['sha256'])

    def test_rebuilt_four_sources_accounted(self):
        all_origins = [o for e in F['vod_sites'] for o in vod_origins(e)]
        for sid, expected in EXPECTED.items():
            with self.subTest(source=sid):
                s = source(sid);sn=s['snapshots'][0]
                self.assertEqual(sn['parse_result']['format'], 'jsonc')
                # Published + quarantined site count must explain every original item.
                retained = [o for o in all_origins if o['source_id']==sid and o['source_snapshot_sha256']==sn['sha256']]
                quarantine = sn['parse_result'].get('quarantined_site_count',0)
                self.assertEqual(len(retained)+quarantine, expected)
                self.assertEqual(sn['parse_result']['lives_config_count'], 1)

    def test_group_fixed_origins_rr1_and_regrouping(self):
        origins = [(e,o) for e in F['live_entries'] for o in live_origins(e) if o['source_id']==GROUP_SOURCE]
        self.assertEqual(len(origins), 1230)
        old_complete = {e['request_revision'] for e in OLD['live_entries'] if e['request_complete']}
        shared_count = 0
        for e,o in origins:
            self.assertTrue(e['request_complete'])
            self.assertEqual(e['request_revision'],request_revision(o['request']))
            self.assertTrue(o['group_raw'])
            self.assertNotIn('unresolved_json_inherited_request_conditions', o['request_incomplete_reasons'])
            if e['request_revision'] in old_complete:
                self.assertGreater(len(e['origins']),1); shared_count += 1
        self.assertEqual(shared_count,243)
        revs=[e['request_revision'] for e in F['live_entries'] if e['request_complete']]
        self.assertEqual(len(revs),len(set(revs)))

    def test_reader_needs_only_feed_not_archive_business_data(self):
        feed_path=(ARGS.root/'feed.json').resolve();original=Path.open
        def guarded(path,*a,**kw):
            if Path(path).resolve()!=feed_path:
                raise AssertionError('consumer attempted extra file read: '+str(path))
            return original(path,*a,**kw)
        with patch.object(Path,'open',guarded):
            f=load_feed(feed_path)
            live_count=sum(1 for e in f['live_entries'] for _ in live_origins(e))
            vod_count=sum(1 for e in f['vod_sites'] for _ in vod_origins(e))
        self.assertEqual(live_count,F['summary']['live_origin_count'])
        self.assertEqual(vod_count,F['summary']['vod_origin_count'])
        self.assertEqual(summary(F),F['summary'])

if __name__ == '__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2]);ap.add_argument('--baseline-feed',type=Path);ap.add_argument('--parser-only',action='store_true')
    ARGS,rest=ap.parse_known_args();ARGS.root=ARGS.root.resolve();F=load_feed(ARGS.root/'feed.json')
    if not ARGS.parser_only:
        old_text=ARGS.baseline_feed.read_text('utf-8') if ARGS.baseline_feed else subprocess.check_output(['git','show',BASELINE+':feed.json'],cwd=ARGS.root).decode('utf-8')
        OLD=expand_shared(json.loads(old_text))
    suite=unittest.TestLoader().loadTestsFromTestCase(ParserRegressions)
    if not ARGS.parser_only:suite.addTests(unittest.TestLoader().loadTestsFromTestCase(RebuiltFeedRegressions))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
