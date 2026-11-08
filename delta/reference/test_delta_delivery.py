#!/usr/bin/env python3
"""Offline transport regressions using tiny synthetic feeds, never live sources.

These fixtures exercise delta serialization/replay, not the separate full feed
business validator. All files are created under TemporaryDirectory.
"""
import copy
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

import delta_delivery as delta
from jsonschema.exceptions import ValidationError
from feed_common import strict_load


def fixture():
    feed = {
        'schema_version': 'source-hub-feed.v1',
        'generated_at': '2026-01-01T00:00:00Z',
        'batch_id': 'fixture-0',
        'scope': {'offline': True},
        'shared_values': {},
    }
    feed.update({name: [] for name in delta.KEYS})
    feed['original_inventory'] = [{'original_id': 'original-1', 'text': '原始来源'}]
    feed['sources'] = [{'source_id': 'source-1', 'original_url': 'https://example.invalid/list?a=2&a=1'}]
    feed['live_entries'] = [{
        'entry_id': 'entry-1', 'name': '频道一', 'origin_count': 2,
        'origins': [
            {'entry_id': 'origin-1', 'source_id': 'source-1', 'original_id': 'original-1', 'line': 2,
             'original_name': '频道一', 'request': {'url': 'https://example.invalid/a?b=2&b=1',
                'headers': {'Referer': 'https://example.invalid/full/path?a=1', 'X-Example': '甲'},
                'redirects': ['https://example.invalid/start', 'https://example.invalid/end']}},
            {'entry_id': 'origin-2', 'source_id': 'source-1', 'original_id': 'original-1', 'line': 8,
             'original_name': 'Channel 1', 'raw': '#EXTINF:-1,Channel 1\nhttps://example.invalid/a'},
        ],
    }]
    feed['vod_sites'] = [{'vod_site_id': 'vod-1', 'name': 'Example VOD'}]
    feed['checks'] = [{'check_id': 'check-1', 'target_id': 'entry-1', 'status': 'not_tested',
                       'evidence': {'kind': 'offline_only', 'request_used': None}}]
    feed['environments'] = [{'env_id': 'environment-1', 'name': 'fixture'}]
    feed['archive_files'] = [{'path': 'archive/original.txt', 'sha256': hashlib.sha256(b'original\n').hexdigest(), 'byte_count': 9}]
    return feed


class DeltaDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'repository'
        self.root.mkdir()
        self.feed = fixture()
        (self.root / 'archive').mkdir()
        (self.root / 'archive/original.txt').write_bytes(b'original\n')
        self.write_json(self.root / 'feed.json', self.feed)
        self.index = delta.initialize(self.root, baseline_commit='a' * 40)
        self.baseline_bytes = (self.root / 'feed.json').read_bytes()
        self.candidate = Path(self.tmp.name) / 'candidate.json'

    @staticmethod
    def write_json(path, obj):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(delta.encoded(obj) + b'\n')

    def publish(self, feed=None, **kwargs):
        self.write_json(self.candidate, self.feed if feed is None else feed)
        return delta.publish(self.root, self.candidate, **kwargs)

    def read_index(self):
        return strict_load(self.root / 'delta/index.json')

    def tree(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file()}

    def changed_feed(self, label='changed'):
        feed = copy.deepcopy(self.feed)
        feed['live_entries'][0]['name'] = label
        return feed

    def manifest(self, index=None, sequence=-1):
        index = self.read_index() if index is None else index
        return strict_load(self.root / index['batches'][sequence]['path'])

    def rewrite_manifest(self, manifest, sequence=-1):
        index = self.read_index()
        desc = index['batches'][sequence]
        self.write_json(self.root / desc['path'], manifest)
        desc.update(delta.descriptor(self.root, desc['path']))
        self.write_json(self.root / 'delta/index.json', index)

    def forged_batch(self, operations, after_model):
        """Build an internally hash-consistent artifact to test replay defenses."""
        state = delta.load_state(self.root)
        sequence = state['sequence'] + 1
        path = f'delta/batches/{sequence:08d}/fixture-part.json'
        doc = {'schema_version': delta.VERSION, 'sequence': sequence, 'operations': operations}
        self.write_json(self.root / path, doc)
        part = delta.descriptor(self.root, path)
        part['operation_count'] = len(operations)
        manifest = {
            'schema_version': delta.VERSION, 'baseline_id': state['baseline_id'],
            'sequence': sequence, 'previous_batch_sha256': state['last_batch_sha256'],
            'before_state_sha256': state['state_sha256'], 'after_state_sha256': delta.digest(after_model),
            'metadata_after': after_model['metadata'], 'order_after': after_model['order'],
            'operation_count': len(operations), 'parts': [part],
        }
        path = f'delta/batches/{sequence:08d}/fixture-manifest.json'
        self.write_json(self.root / path, manifest)
        desc = delta.descriptor(self.root, path)
        desc['sequence'] = sequence
        index = self.read_index()
        index['batches'].append(desc)
        index['latest_sequence'] = sequence
        self.write_json(self.root / 'delta/index.json', index)
        return state, desc

    def test_baseline_reconstructs_all_collections_and_metadata(self):
        state = delta.load_state(self.root)
        self.assertEqual(state['sequence'], 0)
        self.assertIsNone(state['last_batch_sha256'])
        self.assertEqual(state['model'], delta.model(self.feed))
        self.assertEqual(delta.materialize(state['model']), self.feed)
        self.assertEqual(state['state_sha256'], self.index['baseline']['state_sha256'])
        self.assertEqual(self.index['baseline']['git_commit'], 'a' * 40)
        self.assertEqual(self.index['baseline']['sha256'], delta.file_hash(self.root / 'feed.json'))

    def test_initialize_refuses_to_replace_existing_index(self):
        before = self.tree()
        with self.assertRaisesRegex(ValueError, 'already exists'):
            delta.initialize(self.root)
        self.assertEqual(self.tree(), before)

    def test_model_rejects_duplicate_or_empty_entity_keys(self):
        for collection, key in delta.KEYS.items():
            with self.subTest(collection=collection):
                feed = copy.deepcopy(self.feed)
                feed[collection].append(copy.deepcopy(feed[collection][0]))
                with self.assertRaises(ValueError):
                    delta.model(feed)
                feed[collection] = [{key: ''}]
                with self.assertRaises(ValueError):
                    delta.model(feed)

    def test_upsert_new_and_changed_records_in_one_batch(self):
        feed = self.changed_feed()
        feed['sources'].append({'source_id': 'source-2', 'original_url': 'https://example.invalid/new'})
        feed['checks'].append({'check_id': 'check-2', 'status': 'not_tested'})
        result = self.publish(feed)
        self.assertTrue(result['changed'])
        self.assertEqual(result['sequence'], 1)
        self.assertEqual(result['operations'], 3)
        self.assertEqual(delta.load_state(self.root)['model'], delta.model(feed))
        self.assertEqual((self.root / 'feed.json').read_bytes(), self.baseline_bytes)
        manifest = self.manifest()
        operations = [op for part in manifest['parts']
                      for op in strict_load(self.root / part['path'])['operations']]
        changed = next(op for op in operations if op['key'] == 'entry-1')
        added = next(op for op in operations if op['key'] == 'source-2')
        self.assertEqual(changed['before_sha256'], delta.digest(self.feed['live_entries'][0]))
        self.assertIsNone(added['before_sha256'])

    def test_upsert_preserves_full_origins_and_request_details(self):
        feed = self.changed_feed()
        feed['live_entries'][0]['origins'].append({
            'entry_id': 'origin-3', 'source_id': 'source-1', 'line': 99, 'custom_evidence': {'segments': [0, False, None, '原文']},
            'request': {'url': 'https://example.invalid/x?token=a%2Fb&x=1&x=2', 'headers': {'A': 'B'}}})
        feed['live_entries'][0]['origin_count'] = 3
        self.publish(feed)
        materialized = delta.materialize(delta.load_state(self.root)['model'])
        self.assertEqual(materialized['live_entries'][0], feed['live_entries'][0])
        self.assertEqual(len(materialized['live_entries'][0]['origins']), 3)

    def test_noop_and_timestamp_only_reassembly_write_nothing(self):
        before = self.tree()
        self.assertEqual(self.publish(), {'changed': False, 'sequence': 0})
        feed = copy.deepcopy(self.feed)
        feed['generated_at'] = '2026-02-01T00:00:00Z'
        feed['batch_id'] = 'fixture-reassembled'
        self.assertEqual(self.publish(feed), {'changed': False, 'sequence': 0})
        self.assertEqual(self.tree(), before)

    def test_shared_values_expand_without_losing_origins(self):
        compact = copy.deepcopy(self.feed)
        compact['shared_values'] = {'origins': compact['live_entries'][0]['origins']}
        compact['live_entries'][0]['origins'] = {'$value_ref': 'origins'}
        self.assertEqual(delta.model(compact), delta.model(self.feed))
        self.assertFalse(self.publish(compact)['changed'])
        self.assertEqual(delta.materialize(delta.model(compact))['shared_values'], {})

    def test_order_only_batch_preserves_candidate_collection_order(self):
        feed = copy.deepcopy(self.feed)
        feed['sources'].append({'source_id': 'source-0', 'label': 'first after sorting'})
        self.publish(feed)
        feed['sources'].reverse()
        result = self.publish(feed)
        self.assertTrue(result['changed'])
        self.assertEqual(result['operations'], 0)
        self.assertEqual(result['parts'], 0)
        self.assertEqual([s['source_id'] for s in delta.materialize(delta.load_state(self.root)['model'])['sources']],
                         ['source-0', 'source-1'])

    def test_missing_records_never_implicitly_delete(self):
        before = self.tree()
        for collection in delta.KEYS:
            with self.subTest(collection=collection):
                feed = copy.deepcopy(self.feed)
                feed[collection] = []
                with self.assertRaisesRegex(ValueError, 'explicit retraction reason'):
                    self.publish(feed)
                self.assertEqual(self.tree(), before)

    def test_explicit_retraction_retains_tombstone_reason(self):
        feed = copy.deepcopy(self.feed)
        feed['live_entries'] = []
        result = self.publish(feed, retractions={'live_entries': {'entry-1': 'publisher withdrew entry'}})
        self.assertEqual(result['operations'], 1)
        self.assertEqual(delta.materialize(delta.load_state(self.root)['model'])['live_entries'], [])
        part = self.manifest()['parts'][0]
        op = strict_load(self.root / part['path'])['operations'][0]
        self.assertEqual(op['operation'], 'retract')
        self.assertEqual(op['reason'], 'publisher withdrew entry')
        self.assertEqual(op['before_sha256'], delta.digest(self.feed['live_entries'][0]))
        self.assertEqual((self.root / 'feed.json').read_bytes(), self.baseline_bytes)

    def test_protected_history_cannot_be_retracted_even_with_reason(self):
        before = self.tree()
        for collection in ('checks', 'original_inventory', 'archive_files'):
            with self.subTest(collection=collection):
                feed = copy.deepcopy(self.feed)
                key = feed[collection][0][delta.KEYS[collection]]
                feed[collection] = []
                with self.assertRaisesRegex(ValueError, 'protected historical record'):
                    self.publish(feed, retractions={collection: {key: 'explicit reason'}})
                self.assertEqual(self.tree(), before)

    def test_existing_check_facts_are_immutable_at_publish(self):
        feed = copy.deepcopy(self.feed)
        feed['checks'][0]['status'] = 'pass'
        before = self.tree()
        with self.assertRaisesRegex(ValueError, 'historical record'):
            self.publish(feed)
        self.assertEqual(self.tree(), before)

    def test_consumer_rejects_modification_of_existing_check(self):
        model = delta.model(self.feed)
        old = model['entities']['checks']['check-1']
        new = {**old, 'status': 'pass'}
        model['entities']['checks']['check-1'] = new
        op = {'operation': 'upsert', 'collection': 'checks', 'key': 'check-1',
              'before_sha256': delta.digest(old), 'value': new}
        self.forged_batch([op], model)
        with self.assertRaises(ValueError):
            delta.load_state(self.root)

    def test_consumer_rejects_retraction_of_protected_history(self):
        for collection in ('checks', 'original_inventory', 'archive_files'):
            with self.subTest(collection=collection):
                # Reset only this fixture's index, leaving irrelevant artifacts unreferenced.
                self.write_json(self.root / 'delta/index.json', self.index)
                model = delta.model(self.feed)
                key = self.feed[collection][0][delta.KEYS[collection]]
                old = model['entities'][collection].pop(key)
                op = {'operation': 'retract', 'collection': collection, 'key': key,
                      'before_sha256': delta.digest(old), 'reason': 'not permitted'}
                self.forged_batch([op], model)
                with self.assertRaises(ValueError):
                    delta.load_state(self.root)

    def test_baseline_bytes_must_match_descriptor(self):
        (self.root / 'feed.json').write_bytes(self.baseline_bytes + b' ')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            delta.load_state(self.root)

    def test_baseline_state_hash_must_match(self):
        index = self.read_index()
        index['baseline']['state_sha256'] = '0' * 64
        self.write_json(self.root / 'delta/index.json', index)
        with self.assertRaisesRegex(ValueError, 'baseline state mismatch'):
            delta.load_state(self.root)

    def test_manifest_bytes_must_match_descriptor(self):
        self.publish(self.changed_feed())
        path = self.root / self.read_index()['batches'][0]['path']
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            delta.load_state(self.root)

    def test_part_bytes_must_match_descriptor(self):
        self.publish(self.changed_feed())
        path = self.root / self.manifest()['parts'][0]['path']
        raw = path.read_bytes()
        # Same-length corruption exercises SHA-256 independently of byte_count.
        path.write_bytes(raw.replace(b'changed', b'altered'))
        self.assertEqual(path.stat().st_size, len(raw))
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            delta.load_state(self.root)

    def test_part_byte_count_must_match(self):
        self.publish(self.changed_feed())
        manifest = self.manifest()
        manifest['parts'][0]['byte_count'] += 1
        self.rewrite_manifest(manifest)
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            delta.load_state(self.root)

    def test_result_state_hash_must_match(self):
        self.publish(self.changed_feed())
        manifest = self.manifest()
        manifest['after_state_sha256'] = '0' * 64
        self.rewrite_manifest(manifest)
        with self.assertRaisesRegex(ValueError, 'result state mismatch'):
            delta.load_state(self.root)

    def test_noncontiguous_or_reordered_batches_are_rejected(self):
        self.publish(self.changed_feed('first'))
        self.publish(self.changed_feed('second'))
        valid = self.read_index()
        for broken in (list(reversed(valid['batches'])), [valid['batches'][1]]):
            with self.subTest(sequences=[d['sequence'] for d in broken]):
                index = copy.deepcopy(valid)
                index['batches'] = broken
                index['latest_sequence'] = len(broken)
                self.write_json(self.root / 'delta/index.json', index)
                with self.assertRaisesRegex(ValueError, 'non-contiguous'):
                    delta.load_state(self.root)

    def test_index_latest_sequence_must_equal_batch_count(self):
        index = self.read_index()
        index['latest_sequence'] = 1
        self.write_json(self.root / 'delta/index.json', index)
        with self.assertRaisesRegex(ValueError, 'sequence count mismatch'):
            delta.load_state(self.root)

    def test_previous_batch_hash_is_a_required_chain(self):
        self.publish(self.changed_feed('first'))
        self.publish(self.changed_feed('second'))
        manifest = self.manifest()
        manifest['previous_batch_sha256'] = '0' * 64
        self.rewrite_manifest(manifest)
        with self.assertRaisesRegex(ValueError, 'chain mismatch'):
            delta.load_state(self.root)

    def test_apply_requires_exact_next_batch(self):
        self.publish(self.changed_feed('first'))
        self.publish(self.changed_feed('second'))
        index = self.read_index()
        state = delta.initial(self.root, index)
        with self.assertRaisesRegex(ValueError, 'missing batch'):
            delta.apply_batch(self.root, state, index['batches'][1])

    def test_duplicate_part_or_wrong_operation_count_is_rejected(self):
        self.publish(self.changed_feed())
        original = self.manifest()
        for duplicate in (True, False):
            with self.subTest(duplicate=duplicate):
                manifest = copy.deepcopy(original)
                if duplicate:
                    manifest['parts'].append(copy.deepcopy(manifest['parts'][0]))
                else:
                    manifest['parts'][0]['operation_count'] += 1
                self.rewrite_manifest(manifest)
                with self.assertRaises(ValueError):
                    delta.load_state(self.root)

    def test_record_precondition_is_checked(self):
        model = delta.model(self.changed_feed())
        op = {'operation': 'upsert', 'collection': 'live_entries', 'key': 'entry-1',
              'before_sha256': '0' * 64, 'value': model['entities']['live_entries']['entry-1']}
        self.forged_batch([op], model)
        with self.assertRaisesRegex(ValueError, 'record precondition mismatch'):
            delta.load_state(self.root)

    def test_repeated_operation_for_same_key_is_rejected(self):
        model = delta.model(self.changed_feed())
        value = model['entities']['live_entries']['entry-1']
        first = {'operation': 'upsert', 'collection': 'live_entries', 'key': 'entry-1',
                 'before_sha256': delta.digest(self.feed['live_entries'][0]), 'value': value}
        second = {**first, 'before_sha256': delta.digest(value)}
        self.forged_batch([first, second], model)
        with self.assertRaisesRegex(ValueError, 'repeated operation'):
            delta.load_state(self.root)

    def test_sync_is_idempotent_and_does_not_rewrite_checkpoint(self):
        checkpoint = Path(self.tmp.name) / 'consumer/state.json'
        self.assertEqual(delta.sync(self.root, checkpoint), 0)
        self.publish(self.changed_feed())
        self.assertEqual(delta.sync(self.root, checkpoint), 1)
        before = checkpoint.read_bytes()
        os.utime(checkpoint, ns=(1_000_000_000, 1_000_000_000))
        self.assertEqual(delta.sync(self.root, checkpoint), 1)
        self.assertEqual(checkpoint.read_bytes(), before)
        self.assertEqual(checkpoint.stat().st_mtime_ns, 1_000_000_000)
        self.assertFalse(Path(str(checkpoint) + '.lock').exists())
        self.assertEqual(strict_load(checkpoint), delta.load_state(self.root))

    def test_incremental_checkpoint_resume_matches_full_replay(self):
        self.publish(self.changed_feed('first'))
        previous = delta.load_state(self.root)
        self.publish(self.changed_feed('second'))
        self.assertEqual(delta.load_state(self.root, checkpoint=previous), delta.load_state(self.root))
        self.assertEqual(previous['sequence'], 1)  # Replay does not mutate caller state.
        self.assertEqual(previous['model']['entities']['live_entries']['entry-1']['name'], 'first')

    def test_failed_sync_keeps_previous_checkpoint_and_releases_lock(self):
        checkpoint = Path(self.tmp.name) / 'checkpoint.json'
        delta.sync(self.root, checkpoint)
        before = checkpoint.read_bytes()
        self.publish(self.changed_feed())
        part = self.root / self.manifest()['parts'][0]['path']
        part.write_bytes(b'corrupted')
        with self.assertRaises(ValueError):
            delta.sync(self.root, checkpoint)
        self.assertEqual(checkpoint.read_bytes(), before)
        self.assertFalse(Path(str(checkpoint) + '.lock').exists())

    def test_sync_does_not_remove_an_existing_lock(self):
        checkpoint = Path(self.tmp.name) / 'checkpoint.json'
        lock = Path(str(checkpoint) + '.lock')
        lock.write_text('another consumer', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'checkpoint locked'):
            delta.sync(self.root, checkpoint)
        self.assertEqual(lock.read_text('utf-8'), 'another consumer')
        self.assertFalse(checkpoint.exists())

    def test_corrupted_checkpoint_model_is_rejected(self):
        checkpoint = delta.load_state(self.root)
        checkpoint['model']['metadata']['scope']['offline'] = False
        with self.assertRaisesRegex(ValueError, 'checkpoint corrupted'):
            delta.load_state(self.root, checkpoint=checkpoint)

    def test_checkpoint_cannot_change_baseline_or_claim_future_sequence(self):
        state = delta.load_state(self.root)
        for field, value in (('baseline_id', 'other-baseline'), ('sequence', 10)):
            with self.subTest(field=field):
                broken = {**state, field: value}
                with self.assertRaises(ValueError):
                    delta.load_state(self.root, checkpoint=broken)

    def test_checkpoint_batch_hash_cannot_change_at_same_sequence(self):
        self.publish(self.changed_feed())
        checkpoint = delta.load_state(self.root)
        checkpoint['last_batch_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'same sequence changed hash'):
            delta.load_state(self.root, checkpoint=checkpoint)

    def test_index_rollback_is_rejected_for_advanced_checkpoint(self):
        self.publish(self.changed_feed())
        checkpoint = delta.load_state(self.root)
        self.write_json(self.root / 'delta/index.json', self.index)
        with self.assertRaisesRegex(ValueError, 'rollback'):
            delta.load_state(self.root, checkpoint=checkpoint)

    def test_checkpoint_state_hash_is_anchored_to_its_batch(self):
        self.publish(self.changed_feed())
        checkpoint = delta.load_state(self.root)
        checkpoint['model']['entities']['checks']['check-1']['status'] = 'pass'
        checkpoint['state_sha256'] = delta.digest(checkpoint['model'])
        with self.assertRaises(ValueError):
            delta.load_state(self.root, checkpoint=checkpoint)

    def test_safe_rejects_absolute_parent_and_symlink_escapes(self):
        outside = Path(self.tmp.name) / 'outside.json'
        outside.write_text('{}', encoding='utf-8')
        (self.root / 'escape.json').symlink_to(outside)
        for path in ('../outside.json', str(outside), 'delta/../../outside.json', 'escape.json'):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    delta.safe(self.root, path)
        self.assertEqual(delta.safe(self.root, 'delta/index.json'), self.root / 'delta/index.json')

    def test_baseline_descriptor_cannot_escape_root(self):
        index = self.read_index()
        index['baseline']['path'] = '../candidate.json'
        self.write_json(self.root / 'delta/index.json', index)
        with self.assertRaisesRegex(ValueError, 'unsafe path'):
            delta.load_state(self.root)

    def test_part_descriptor_cannot_escape_root(self):
        self.publish(self.changed_feed())
        manifest = self.manifest()
        manifest['parts'][0]['path'] = '../candidate.json'
        self.rewrite_manifest(manifest)
        with self.assertRaisesRegex(ValueError, 'unsafe path'):
            delta.load_state(self.root)

    def test_multiple_parts_respect_limit_and_replay_every_operation_once(self):
        feed = copy.deepcopy(self.feed)
        feed['sources'].extend({'source_id': f'source-{i:02d}', 'payload': 'x' * 180} for i in range(2, 15))
        limit = 750
        result = self.publish(feed, max_part_bytes=limit)
        self.assertGreater(result['parts'], 1)
        self.assertEqual(result['operations'], 13)
        manifest = self.manifest()
        keys = []
        for part in manifest['parts']:
            self.assertLessEqual(part['byte_count'], limit)
            raw = (self.root / part['path']).read_bytes()
            self.assertEqual(len(raw), part['byte_count'])
            self.assertEqual(delta.file_hash(self.root / part['path']), part['sha256'])
            operations = strict_load(self.root / part['path'])['operations']
            self.assertEqual(len(operations), part['operation_count'])
            keys.extend(op['key'] for op in operations)
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(delta.load_state(self.root)['model'], delta.model(feed))

    def test_oversized_record_fails_before_writing_any_artifacts(self):
        before = self.tree()
        with self.assertRaisesRegex(ValueError, 'single record exceeds part limit'):
            self.publish(self.changed_feed(), max_part_bytes=100)
        self.assertEqual(self.tree(), before)

    def test_later_publish_never_changes_prior_artifact_bytes(self):
        self.publish(self.changed_feed('first'))
        first = {path: data for path, data in self.tree().items() if path != 'delta/index.json'}
        self.publish(self.changed_feed('second'))
        after = self.tree()
        self.assertEqual({path: after[path] for path in first}, first)
        self.assertEqual(self.read_index()['latest_sequence'], 2)

    def test_original_inventory_and_archive_metadata_are_immutable(self):
        before = self.tree()
        for collection in ('original_inventory', 'archive_files'):
            with self.subTest(collection=collection):
                feed = copy.deepcopy(self.feed)
                feed[collection][0]['extra'] = 'historical rewrite'
                with self.assertRaisesRegex(ValueError, 'historical record'):
                    self.publish(feed)
                self.assertEqual(self.tree(), before)

    def test_consumer_rejects_rewriting_inventory_and_archive_records(self):
        for collection in ('original_inventory', 'archive_files'):
            with self.subTest(collection=collection):
                self.write_json(self.root / 'delta/index.json', self.index)
                model = delta.model(self.feed)
                key = self.feed[collection][0][delta.KEYS[collection]]
                old = model['entities'][collection][key]
                new = {**old, 'extra': 'historical rewrite'}
                model['entities'][collection][key] = new
                op = {'operation': 'upsert', 'collection': collection, 'key': key,
                      'before_sha256': delta.digest(old), 'value': new}
                self.forged_batch([op], model)
                with self.assertRaisesRegex(ValueError, 'historical record'):
                    delta.load_state(self.root)

    def test_origin_history_cannot_be_dropped_or_rewritten(self):
        before = self.tree()
        missing = self.changed_feed()
        missing['live_entries'][0]['origins'].pop()
        rewritten = self.changed_feed()
        rewritten['live_entries'][0]['origins'][0]['source_id'] = 'different-source'
        for feed in (missing, rewritten):
            with self.subTest(origins=feed['live_entries'][0]['origins']):
                with self.assertRaisesRegex(ValueError, 'origin|identity'):
                    self.publish(feed)
                self.assertEqual(self.tree(), before)

    def test_consumer_rejects_removal_of_an_existing_origin(self):
        feed = self.changed_feed()
        feed['live_entries'][0]['origins'].pop()
        model = delta.model(feed)
        op = {'operation': 'upsert', 'collection': 'live_entries', 'key': 'entry-1',
              'before_sha256': delta.digest(self.feed['live_entries'][0]),
              'value': model['entities']['live_entries']['entry-1']}
        self.forged_batch([op], model)
        with self.assertRaisesRegex(ValueError, 'origin history'):
            delta.load_state(self.root)

    def test_source_snapshot_history_is_append_only(self):
        feed = copy.deepcopy(self.feed)
        feed['sources'][0]['snapshots'] = [{'sha256': 'a' * 64, 'path': 'archive/one.txt'}]
        self.publish(feed)
        before = self.tree()
        dropped = copy.deepcopy(feed)
        dropped['sources'][0]['snapshots'] = []
        with self.assertRaisesRegex(ValueError, 'snapshot history'):
            self.publish(dropped)
        self.assertEqual(self.tree(), before)
        feed['sources'][0]['snapshots'].append({'sha256': 'b' * 64, 'path': 'archive/two.txt'})
        self.assertTrue(self.publish(feed)['changed'])
        self.assertEqual(delta.materialize(delta.load_state(self.root)['model'])['sources'], feed['sources'])

    def test_new_archive_record_requires_matching_local_bytes(self):
        feed = copy.deepcopy(self.feed)
        path = self.root / 'archive/new.txt'
        path.write_bytes(b'new archive')
        feed['archive_files'].append(delta.descriptor(self.root, 'archive/new.txt'))
        result = self.publish(feed)
        self.assertEqual(result['operations'], 1)
        self.assertEqual(delta.load_state(self.root)['model'], delta.model(feed))
        feed['archive_files'].append({'path': 'archive/bad.txt', 'byte_count': 3, 'sha256': '0' * 64})
        (self.root / 'archive/bad.txt').write_bytes(b'bad')
        before = self.tree()
        with self.assertRaisesRegex(ValueError, 'archive bytes mismatch'):
            self.publish(feed)
        self.assertEqual(self.tree(), before)

    def test_publisher_respects_existing_lock(self):
        lock = self.root / 'delta/.publish.lock'
        lock.write_text('another publisher', encoding='utf-8')
        before = self.tree()
        with self.assertRaisesRegex(ValueError, 'publisher locked'):
            self.publish(self.changed_feed())
        self.assertEqual(self.tree(), before)
        self.assertEqual(lock.read_text('utf-8'), 'another publisher')

    def test_safe_rejects_noncanonical_paths(self):
        for path in ('./feed.json', 'delta//index.json', 'delta/./index.json',
                     'delta/../feed.json', 'delta\\index.json', ''):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    delta.safe(self.root, path)

    def test_manifest_descriptor_cannot_escape_root(self):
        self.publish(self.changed_feed())
        index = self.read_index()
        index['batches'][0]['path'] = '../candidate.json'
        self.write_json(self.root / 'delta/index.json', index)
        with self.assertRaisesRegex(ValueError, 'unsafe path'):
            delta.load_state(self.root)

    def test_order_descriptor_must_list_each_record_exactly_once(self):
        self.publish(self.changed_feed())
        original = self.manifest()
        for order in ([], ['entry-1', 'entry-1'], ['nonexistent']):
            with self.subTest(order=order):
                manifest = copy.deepcopy(original)
                manifest['order_after']['live_entries'] = order
                self.rewrite_manifest(manifest)
                with self.assertRaises((ValueError, ValidationError)):
                    delta.load_state(self.root)

    def test_batch_failure_does_not_mutate_supplied_state(self):
        self.publish(self.changed_feed())
        index = self.read_index()
        state = delta.initial(self.root, index)
        before = copy.deepcopy(state)
        manifest = self.manifest()
        manifest['after_state_sha256'] = '0' * 64
        self.rewrite_manifest(manifest)
        with self.assertRaises(ValueError):
            delta.apply_batch(self.root, state, self.read_index()['batches'][0])
        self.assertEqual(state, before)

    def test_duplicate_json_keys_are_rejected(self):
        (self.root / 'delta/index.json').write_text('{"schema_version":"x","schema_version":"y"}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
            delta.load_state(self.root)

    def test_materialize_compacts_normalization_basis_without_losing_semantics(self):
        feed = fixture()
        feed['live_entries'][0]['normalization_basis'] = {
            'name': 'channel_alias_registry.v1',
            'category': 'channel_alias_registry.v1',
            'country_code': 'channel_alias_registry.v1',
        }
        state = delta.model(feed)
        result = delta.materialize(state)
        self.assertIn('$value_ref', result['live_entries'][0]['normalization_basis'])
        self.assertEqual(delta.model(result), state)

    def test_materialize_keeps_non_ref_capable_source_and_vod_arrays_inline(self):
        feed = fixture()
        reason = ['not_understood_' * 20]
        feed['sources'][0]['incomplete_reasons'] = reason
        feed['vod_sites'] = [{'vod_site_id': 'vod-1', 'incomplete_reasons': reason}]
        result = delta.materialize(delta.model(feed))
        self.assertEqual(result['sources'][0]['incomplete_reasons'], reason)
        self.assertEqual(result['vod_sites'][0]['incomplete_reasons'], reason)

    def test_complete_request_changes_need_new_identity(self):
        old = {'entry_id': 'one', 'request_complete': True,
               'request': {'url': 'https://example.invalid/a', 'headers': {}, 'options': {}},
               'origins': []}
        new = copy.deepcopy(old)
        new['request']['headers']['Referer'] = 'https://example.invalid/other'
        with self.assertRaisesRegex(ValueError, 'new request identity'):
            delta.preserve_history('live_entries', old, new)


if __name__ == '__main__':
    unittest.main(verbosity=2)
