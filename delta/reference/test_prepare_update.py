#!/usr/bin/env python3
"""Offline handoff regressions with tiny fixtures and a mocked business rebuild.

Hash checks, reviewed-body handling, local caches, staging, and delta publication
are real. Only the full parser/assembler and full-feed validator are mocked;
full-repository business validation belongs to the separate integration suite.
"""
import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True

import delta_delivery as delta
import prepare_update as prepare
from feed_common import strict_load
from incremental_fetch import blob_sha
from test_delta_delivery import fixture

OLD_TIME = '2026-01-01T00:00:00Z'
NEW_TIME = '2026-02-01T00:00:00Z'
OLD_BYTES = b'original\n'
NEW_BYTES = b'#EXTM3U\n#EXTINF:-1,Offline fixture\nhttps://example.invalid/channel\n'


def snapshot(path='archive/original.txt', body=OLD_BYTES, parse_time=OLD_TIME):
    return {
        'path': path, 'sha256': hashlib.sha256(body).hexdigest(), 'byte_count': len(body),
        'parse_time': parse_time, 'parse_status': 'complete',
        'parse_result': {'live_candidate_count': 1, 'unparsed_items': []},
    }


def source(source_id='source-1'):
    return {
        'source_id': source_id, 'original_url': 'https://example.invalid/list?a=2&a=1',
        'fetch_status': 'retained', 'fetch_time': OLD_TIME, 'parse_time': OLD_TIME,
        'parse_status': 'complete', 'snapshots': [snapshot()],
        'live_candidate_count': 1, 'parse_scope': 'all_retained_snapshots',
    }


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(delta.encoded(data) + b'\n')


class RestoreParseTimesTests(unittest.TestCase):
    def setUp(self):
        self.old = {'sources': [source()]}
        self.new = copy.deepcopy(self.old)
        self.new['sources'][0]['parse_time'] = NEW_TIME
        self.new['sources'][0]['snapshots'][0]['parse_time'] = NEW_TIME

    def test_unchanged_snapshot_and_source_retain_original_times(self):
        previous = copy.deepcopy(self.old)
        result = prepare.restore_parse_times(self.old, self.new)
        self.assertIs(result, self.new)
        self.assertEqual(result, self.old)
        self.assertEqual(self.old, previous)

    def test_new_snapshot_keeps_new_time_and_existing_snapshot_keeps_old_time(self):
        self.new['sources'][0]['snapshots'].append(snapshot('archive/new.m3u', NEW_BYTES, NEW_TIME))
        result = prepare.restore_parse_times(self.old, self.new)['sources'][0]
        self.assertEqual(result['snapshots'][0]['parse_time'], OLD_TIME)
        self.assertEqual(result['snapshots'][1]['parse_time'], NEW_TIME)
        self.assertEqual(result['parse_time'], NEW_TIME)

    def test_changed_snapshot_parse_result_retains_new_times(self):
        self.new['sources'][0]['snapshots'][0]['parse_result']['live_candidate_count'] = 2
        result = prepare.restore_parse_times(self.old, self.new)['sources'][0]
        self.assertEqual(result['snapshots'][0]['parse_time'], NEW_TIME)
        self.assertEqual(result['parse_time'], NEW_TIME)

    def test_changed_source_summary_retains_new_time_only_on_source(self):
        self.new['sources'][0]['live_candidate_count'] = 2
        result = prepare.restore_parse_times(self.old, self.new)['sources'][0]
        self.assertEqual(result['snapshots'][0]['parse_time'], OLD_TIME)
        self.assertEqual(result['parse_time'], NEW_TIME)

    def test_snapshot_identity_requires_both_hash_and_path(self):
        for field, value in (('path', 'archive/relocated.txt'), ('sha256', 'a' * 64)):
            with self.subTest(field=field):
                candidate = copy.deepcopy(self.new)
                candidate['sources'][0]['snapshots'][0][field] = value
                result = prepare.restore_parse_times(self.old, candidate)['sources'][0]
                self.assertEqual(result['snapshots'][0]['parse_time'], NEW_TIME)
                self.assertEqual(result['parse_time'], NEW_TIME)

    def test_new_source_is_not_matched_by_snapshot_hash(self):
        self.new['sources'][0]['source_id'] = 'new-source'
        result = prepare.restore_parse_times(self.old, self.new)['sources'][0]
        self.assertEqual(result['parse_time'], NEW_TIME)
        self.assertEqual(result['snapshots'][0]['parse_time'], NEW_TIME)

    def test_unchanged_other_source_does_not_churn_on_one_source_change(self):
        self.old['sources'].append(source('source-2'))
        self.new = copy.deepcopy(self.old)
        for row in self.new['sources']:
            row['parse_time'] = NEW_TIME
            row['snapshots'][0]['parse_time'] = NEW_TIME
        self.new['sources'][0]['snapshots'][0]['parse_status'] = 'partial'
        result = prepare.restore_parse_times(self.old, self.new)
        self.assertEqual(result['sources'][0]['parse_time'], NEW_TIME)
        self.assertEqual(result['sources'][1], self.old['sources'][1])

    def test_original_null_times_are_preserved_for_unchanged_facts(self):
        self.old['sources'][0]['parse_time'] = None
        self.old['sources'][0]['snapshots'][0]['parse_time'] = None
        result = prepare.restore_parse_times(self.old, self.new)['sources'][0]
        self.assertIsNone(result['parse_time'])
        self.assertIsNone(result['snapshots'][0]['parse_time'])


class PrepareUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.root = self.directory / 'repository'
        self.root.mkdir()
        (self.root / 'archive').mkdir()
        (self.root / 'archive/original.txt').write_bytes(OLD_BYTES)
        self.feed = fixture()
        self.feed['sources'] = [source()]
        save_json(self.root / 'feed.json', self.feed)
        delta.initialize(self.root, baseline_commit='a' * 40)
        self.stage = self.directory / 'staging'
        self.cache = self.directory / 'cache/fetch.json'
        self.body_path = self.directory / 'download.body'
        self.body_path.write_bytes(NEW_BYTES)
        self.report = {
            'schema_version': 'source-hub-fetch-report.v1',
            'results': [{
                'source_id': 'source-1', 'url': source()['original_url'],
                'status': 'downloaded_pending_safety_review', 'checked_at': NEW_TIME,
                'staged_file': str(self.body_path),
                'record': {
                    'url': source()['original_url'], 'archive_path': None,
                    'sha256': hashlib.sha256(NEW_BYTES).hexdigest(), 'byte_count': len(NEW_BYTES),
                    'etag': '"fixture-new"', 'last_modified': None, 'github_blob_sha': None,
                },
            }],
        }
        self.review = {
            'schema_version': 'source-hub-safety-review.v1',
            'decisions': [{'source_id': 'source-1', 'sha256': hashlib.sha256(NEW_BYTES).hexdigest(),
                           'decision': 'publish', 'reason': 'Offline synthetic fixture reviewed'}],
        }
        validate_patch = patch.object(prepare, 'validate', return_value=None)
        rebuild_patch = patch.object(prepare, 'rebuild', side_effect=self.fake_rebuild)
        self.validate = validate_patch.start()
        self.addCleanup(validate_patch.stop)
        self.rebuild = rebuild_patch.start()
        self.addCleanup(rebuild_patch.stop)

    @staticmethod
    def fake_rebuild(staging, generated_at=None):
        """Simulate timestamp churn and archive enumeration, not business parsing."""
        result = strict_load(staging / 'feed.json')
        timestamp = generated_at or NEW_TIME
        result['generated_at'] = timestamp
        for row in result['sources']:
            row['parse_time'] = timestamp
            for sn in row['snapshots']:
                sn['parse_time'] = timestamp
        result['archive_files'] = [delta.descriptor(staging, str(p.relative_to(staging)))
                                   for p in sorted((staging / 'archive').rglob('*')) if p.is_file()]
        return result

    def init(self, cache_path=None):
        return prepare.initialize(self.root, self.stage, cache_path=cache_path)

    def ingest(self, **kwargs):
        return prepare.ingest(self.root, self.stage, self.report, self.review,
                              generated_at=NEW_TIME, **kwargs)

    def tree(self, root=None):
        root = self.root if root is None else root
        return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}

    def test_initialize_copies_verified_archives_and_records_base_state(self):
        before = self.tree()
        result = self.init()
        self.assertEqual(result, {'sequence': 0, 'staging_initialized': True})
        self.assertEqual((self.stage / 'archive/original.txt').read_bytes(), OLD_BYTES)
        self.assertEqual(strict_load(self.stage / 'feed.json'), self.feed)
        state = delta.load_state(self.root)
        self.assertEqual(strict_load(self.stage / '.base-state.json'),
                         {'state_sha256': state['state_sha256'], 'sequence': 0})
        self.assertEqual(strict_load(self.stage / '.fetch_state.json'),
                         {'schema_version': 'source-hub-fetch-state.v1', 'entries': {}})
        self.assertEqual(self.tree(), before)
        self.validate.assert_not_called()
        self.rebuild.assert_not_called()

    def test_initialize_rejects_repository_or_nested_staging(self):
        before = self.tree()
        for stage in (self.root, self.root / 'inside'):
            with self.subTest(stage=stage):
                with self.assertRaisesRegex(ValueError, 'outside repository'):
                    prepare.initialize(self.root, stage)
        self.assertEqual(self.tree(), before)

    def test_initialize_rejects_nonempty_staging(self):
        self.stage.mkdir()
        (self.stage / 'keep.txt').write_text('keep me', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'fresh'):
            self.init()
        self.assertEqual((self.stage / 'keep.txt').read_text('utf-8'), 'keep me')

    def test_initialize_rejects_corrupted_archive_bytes(self):
        (self.root / 'archive/original.txt').write_bytes(b'corrupt!\n')
        with self.assertRaisesRegex(ValueError, 'archive integrity'):
            self.init()
        self.assertFalse((self.stage / 'feed.json').exists())

    def test_initialize_loads_external_mutable_cache_without_archiving_it(self):
        cache = {'schema_version': 'source-hub-fetch-state.v1', 'entries': {'previous-source': {'etag': 'old'}}}
        save_json(self.cache, cache)
        self.init(cache_path=self.cache)
        self.assertEqual(strict_load(self.stage / '.fetch_state.json'), cache)
        self.assertEqual(strict_load(self.cache), cache)
        self.assertEqual([row['path'] for row in strict_load(self.stage / 'feed.json')['archive_files']],
                         ['archive/original.txt'])

    def test_initialize_missing_external_cache_starts_empty(self):
        self.init(cache_path=self.cache)
        self.assertEqual(strict_load(self.stage / '.fetch_state.json')['entries'], {})
        self.assertFalse(self.cache.exists())

    def test_initialize_rejects_mutable_cache_inside_repository(self):
        before = self.tree()
        with self.assertRaisesRegex(ValueError, 'mutable cache must be outside'):
            self.init(cache_path=self.root / 'cache.json')
        self.assertEqual(self.tree(), before)

    def test_reviewed_new_snapshot_is_staged_with_exact_review_and_cached(self):
        self.init()
        before = self.tree()
        result = self.ingest()
        self.assertEqual(result['added_snapshot_count'], 1)
        self.assertFalse(result['published'])
        self.assertTrue(result['validated'])
        outcome = result['outcomes'][0]
        self.assertEqual(outcome['status'], 'snapshot_added')
        self.assertTrue(outcome['path'].endswith('.m3u'))
        self.assertEqual((self.stage / outcome['path']).read_bytes(), NEW_BYTES)
        feed = strict_load(self.stage / 'feed.json')
        old, new = feed['sources'][0]['snapshots']
        self.assertEqual(old, self.feed['sources'][0]['snapshots'][0])
        self.assertEqual(new['parse_time'], NEW_TIME)
        self.assertEqual(new['capture_evidence']['safety_review'], {
            'decision': 'publish', 'reviewed_sha256': self.review['decisions'][0]['sha256'],
            'reason': self.review['decisions'][0]['reason']})
        self.assertEqual(strict_load(self.stage / '.fetch_state.json')['entries']['source-1']['archive_path'],
                         outcome['path'])
        self.assertEqual(self.tree(), before)
        self.rebuild.assert_called_once_with(self.stage, generated_at=NEW_TIME)
        self.validate.assert_called_once_with(self.stage)

    def test_ingest_can_publish_real_delta_without_changing_frozen_baseline(self):
        self.init()
        baseline = (self.root / 'feed.json').read_bytes()
        result = self.ingest(publish=True)
        self.assertTrue(result['published'])
        self.assertEqual(result['publication']['sequence'], 1)
        self.assertEqual((self.root / 'feed.json').read_bytes(), baseline)
        self.assertEqual((self.root / result['outcomes'][0]['path']).read_bytes(), NEW_BYTES)
        state = delta.load_state(self.root)
        self.assertEqual(state['model'], delta.model(strict_load(self.stage / 'feed.json')))
        self.assertEqual(state['model']['entities']['checks']['check-1'], self.feed['checks'][0])

    def test_missing_review_does_not_read_or_accept_downloaded_body(self):
        self.init()
        self.review['decisions'] = []
        self.body_path.unlink()
        result = self.ingest()
        self.assertEqual(result['added_snapshot_count'], 0)
        self.assertEqual(result['outcomes'][0]['status'], 'quarantined_or_pending_review')
        self.assertEqual(strict_load(self.stage / '.fetch_state.json')['entries'], {})
        self.assertEqual(strict_load(self.stage / 'feed.json'), self.feed)
        self.rebuild.assert_not_called()

    def test_review_hash_must_match_exact_downloaded_body_record(self):
        self.init()
        self.review['decisions'][0]['sha256'] = '0' * 64
        self.body_path.unlink()
        result = self.ingest()
        self.assertEqual(result['added_snapshot_count'], 0)
        self.assertEqual(result['outcomes'][0]['status'], 'quarantined_or_pending_review')
        self.assertEqual(strict_load(self.stage / '.fetch_state.json')['entries'], {})
        self.rebuild.assert_not_called()

    def test_review_is_bound_to_source_id_not_only_body_hash(self):
        self.init()
        self.review['decisions'][0]['source_id'] = 'different-source'
        result = self.ingest()
        self.assertEqual(result['added_snapshot_count'], 0)
        self.assertEqual(result['outcomes'][0]['status'], 'quarantined_or_pending_review')
        self.assertEqual(strict_load(self.stage / '.fetch_state.json')['entries'], {})

    def test_quarantine_decision_never_imports_or_caches_body(self):
        self.init()
        self.review['decisions'][0]['decision'] = 'quarantine'
        self.body_path.unlink()
        result = self.ingest(publish=True)
        self.assertEqual(result['added_snapshot_count'], 0)
        self.assertFalse(result['published'])
        self.assertEqual(strict_load(self.stage / '.fetch_state.json')['entries'], {})
        self.assertEqual(delta.load_state(self.root)['sequence'], 0)
        self.rebuild.assert_not_called()

    def test_registered_sensitive_source_cannot_be_approved_by_review(self):
        self.feed['sources'][0]['fetch_status'] = 'sensitive_quarantined'
        save_json(self.root / 'candidate.json', self.feed)
        delta.publish(self.root, self.root / 'candidate.json')
        self.init()
        self.body_path.unlink()
        result = self.ingest()
        self.assertEqual(result['added_snapshot_count'], 0)
        self.assertEqual(result['outcomes'][0]['status'], 'quarantined_or_pending_review')
        self.assertEqual(strict_load(self.stage / '.fetch_state.json')['entries'], {})

    def test_wrong_report_or_review_schema_is_rejected_before_business_work(self):
        self.init()
        for target in ('report', 'review'):
            with self.subTest(target=target):
                doc = getattr(self, target)
                previous = doc['schema_version']
                doc['schema_version'] = 'unexpected.v2'
                with self.assertRaisesRegex(ValueError, 'wrong report/review format'):
                    self.ingest()
                doc['schema_version'] = previous
        self.validate.assert_not_called()
        self.rebuild.assert_not_called()

    def test_duplicate_safety_decision_is_rejected(self):
        self.init()
        self.review['decisions'].append(copy.deepcopy(self.review['decisions'][0]))
        with self.assertRaisesRegex(ValueError, 'duplicate safety decision'):
            self.ingest()
        self.assertEqual(strict_load(self.stage / '.fetch_state.json')['entries'], {})
        self.validate.assert_not_called()

    def test_unknown_safety_decision_or_empty_reason_is_rejected(self):
        self.init()
        original = copy.deepcopy(self.review['decisions'][0])
        for field, value in (('decision', 'allow'), ('reason', '')):
            with self.subTest(field=field):
                self.review['decisions'][0] = {**original, field: value}
                with self.assertRaisesRegex(ValueError, 'invalid or duplicate safety decision'):
                    self.ingest()
        self.validate.assert_not_called()

    def test_duplicate_report_source_is_rejected_even_for_unchanged_results(self):
        self.init()
        item = {'source_id': 'source-1', 'url': source()['original_url'], 'status': 'blocked_or_failed'}
        self.report['results'] = [item, copy.deepcopy(item)]
        with self.assertRaisesRegex(ValueError, 'duplicate fetch result'):
            self.ingest()
        self.validate.assert_not_called()
        self.rebuild.assert_not_called()

    def test_unregistered_report_source_is_rejected(self):
        self.init()
        self.report['results'][0]['source_id'] = 'different-source'
        with self.assertRaisesRegex(ValueError, 'unregistered source or URL mismatch'):
            self.ingest()
        self.validate.assert_not_called()

    def test_report_source_url_must_match_registered_url_exactly(self):
        self.init()
        # Reordering query arguments is not approved as the same source URL.
        self.report['results'][0]['url'] = 'https://example.invalid/list?a=1&a=2'
        with self.assertRaisesRegex(ValueError, 'unregistered source or URL mismatch'):
            self.ingest()
        self.validate.assert_not_called()

    def test_download_record_url_must_match_report_url(self):
        self.init()
        self.report['results'][0]['record']['url'] = 'https://example.invalid/other'
        with self.assertRaisesRegex(ValueError, 'reviewed body integrity mismatch'):
            self.ingest()
        self.validate.assert_not_called()

    def test_reviewed_body_hash_mismatch_is_rejected(self):
        self.init()
        self.body_path.write_bytes(b'x' * len(NEW_BYTES))
        with self.assertRaisesRegex(ValueError, 'reviewed body integrity mismatch'):
            self.ingest()
        self.assertEqual(strict_load(self.stage / '.fetch_state.json')['entries'], {})
        self.validate.assert_not_called()

    def test_reviewed_body_byte_count_mismatch_is_rejected(self):
        self.init()
        self.report['results'][0]['record']['byte_count'] += 1
        with self.assertRaisesRegex(ValueError, 'reviewed body integrity mismatch'):
            self.ingest()
        self.validate.assert_not_called()

    def test_github_blob_hash_mismatch_is_rejected(self):
        self.init()
        self.report['results'][0]['record']['github_blob_sha'] = '0' * 40
        with self.assertRaisesRegex(ValueError, 'GitHub blob integrity mismatch'):
            self.ingest()
        self.validate.assert_not_called()

    def test_matching_github_blob_hash_is_retained_in_snapshot_evidence(self):
        self.init()
        self.report['results'][0]['record']['github_blob_sha'] = blob_sha(NEW_BYTES)
        result = self.ingest()
        self.assertEqual(result['added_snapshot_count'], 1)
        new = strict_load(self.stage / 'feed.json')['sources'][0]['snapshots'][-1]
        self.assertEqual(new['kind'], 'github_blob_bytes')
        self.assertEqual(new['capture_evidence']['github_blob_sha'], blob_sha(NEW_BYTES))

    def test_existing_snapshot_is_reused_without_rebuild_or_new_bytes(self):
        self.init()
        self.body_path.write_bytes(OLD_BYTES)
        record = self.report['results'][0]['record']
        record['sha256'] = hashlib.sha256(OLD_BYTES).hexdigest()
        record['byte_count'] = len(OLD_BYTES)
        self.review['decisions'][0]['sha256'] = record['sha256']
        result = self.ingest()
        self.assertEqual(result['added_snapshot_count'], 0)
        self.assertEqual(result['outcomes'][0]['status'], 'existing_snapshot_reused')
        self.assertEqual(strict_load(self.stage / 'feed.json'), self.feed)
        self.assertEqual(strict_load(self.stage / '.fetch_state.json')['entries']['source-1']['archive_path'],
                         'archive/original.txt')
        self.rebuild.assert_not_called()

    def test_unchanged_fetch_updates_cache_without_rebuilding_or_publishing(self):
        self.init()
        record = self.report['results'][0]['record']
        record.update({'sha256': hashlib.sha256(OLD_BYTES).hexdigest(), 'byte_count': len(OLD_BYTES),
                       'archive_path': 'archive/original.txt'})
        self.report['results'][0]['status'] = 'reused_http_304'
        result = self.ingest(publish=True)
        self.assertEqual(result['added_snapshot_count'], 0)
        self.assertFalse(result['published'])
        self.assertEqual(strict_load(self.stage / 'feed.json'), self.feed)
        self.assertEqual(strict_load(self.stage / '.fetch_state.json')['entries']['source-1']['checked_at'], NEW_TIME)
        self.assertEqual(delta.load_state(self.root)['sequence'], 0)
        self.rebuild.assert_not_called()

    def test_quarantined_fetch_removes_old_cache_entry(self):
        cache = {'schema_version': 'source-hub-fetch-state.v1', 'entries': {'source-1': {'etag': 'old'}}}
        save_json(self.cache, cache)
        self.init(cache_path=self.cache)
        self.report['results'] = [{'source_id': 'source-1', 'url': source()['original_url'],
                                  'status': 'quarantined_skipped'}]
        self.ingest(cache_path=self.cache)
        self.assertEqual(strict_load(self.cache)['entries'], {})
        self.assertEqual(strict_load(self.stage / '.fetch_state.json')['entries'], {})

    def test_stale_staging_is_rejected_before_ingesting(self):
        self.init()
        changed = copy.deepcopy(self.feed)
        changed['sources'][0]['fetch_time'] = NEW_TIME
        save_json(self.root / 'candidate.json', changed)
        delta.publish(self.root, self.root / 'candidate.json')
        before = self.tree(self.stage)
        with self.assertRaisesRegex(ValueError, 'staging is stale'):
            self.ingest()
        self.assertEqual(self.tree(self.stage), before)
        self.validate.assert_not_called()
        self.rebuild.assert_not_called()

    def test_ingest_rejects_staging_inside_repository(self):
        with self.assertRaisesRegex(ValueError, 'outside repository'):
            prepare.ingest(self.root, self.root / 'staging', self.report, self.review)

    def test_external_cache_is_updated_without_becoming_archive_content(self):
        self.init(cache_path=self.cache)
        result = self.ingest(cache_path=self.cache)
        cache = strict_load(self.cache)
        self.assertEqual(cache, strict_load(self.stage / '.fetch_state.json'))
        self.assertEqual(cache['entries']['source-1']['archive_path'], result['outcomes'][0]['path'])
        archive_paths = [row['path'] for row in strict_load(self.stage / 'feed.json')['archive_files']]
        self.assertNotIn(str(self.cache), archive_paths)
        self.assertFalse(any('fetch' in path for path in archive_paths))

    def test_ingest_rejects_external_cache_target_inside_repository(self):
        self.init()
        before = self.tree()
        with self.assertRaisesRegex(ValueError, 'mutable cache must be outside'):
            self.ingest(publish=True, cache_path=self.root / 'cache.json')
        self.assertEqual(self.tree(), before)
        self.validate.assert_not_called()

    def test_validator_failure_prevents_root_publication(self):
        self.init()
        before = self.tree()
        self.validate.side_effect = ValueError('business validation failed')
        with self.assertRaisesRegex(ValueError, 'business validation failed'):
            self.ingest(publish=True)
        self.assertEqual(self.tree(), before)
        self.assertEqual(delta.load_state(self.root)['sequence'], 0)

    def test_rebuild_cannot_implicitly_remove_prior_records(self):
        self.init()
        before = self.tree()
        def removing_rebuild(staging, generated_at=None):
            result = self.fake_rebuild(staging, generated_at)
            result['live_entries'] = []
            return result
        self.rebuild.side_effect = removing_rebuild
        with self.assertRaisesRegex(ValueError, 'unrequested record removal'):
            self.ingest(publish=True)
        self.assertEqual(self.tree(), before)

    def test_rebuild_cannot_rewrite_historical_checks(self):
        self.init()
        before = self.tree()
        def rewriting_rebuild(staging, generated_at=None):
            result = self.fake_rebuild(staging, generated_at)
            result['checks'][0]['status'] = 'pass'
            return result
        self.rebuild.side_effect = rewriting_rebuild
        with self.assertRaisesRegex(ValueError, 'protected historical record'):
            self.ingest(publish=True)
        self.assertEqual(self.tree(), before)

    def test_snapshot_path_collision_with_different_bytes_is_rejected(self):
        self.init()
        sid = self.report['results'][0]['source_id']
        digest = self.report['results'][0]['record']['sha256']
        path = self.stage / f'archive/sources/{hashlib.sha256(sid.encode()).hexdigest()[:24]}/{digest}.m3u'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'collision')
        with self.assertRaisesRegex(ValueError, 'immutable snapshot collision'):
            self.ingest()
        self.assertEqual(path.read_bytes(), b'collision')
        self.validate.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
