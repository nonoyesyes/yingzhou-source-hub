# Migration validation, 2026-11-08

These are offline execution results, not new source acquisition or playback measurements.

- `PYTHONDONTWRITEBYTECODE=1 python archive/reference/validate_feed.py .`: passed, fixed Schema, inventory, archive bytes, typed references, actual request variants, rr1, metrics and summary. All 300 baseline archive files verified.
- `PYTHONDONTWRITEBYTECODE=1 python archive/reference/test_parser_rebuild.py --root .`: 18/18 passed, including the four real JSONC snapshots and affected display-group records, original values/origins and fixed-reader restoration.
- `PYTHONDONTWRITEBYTECODE=1 python archive/reference/test_feed_boundaries.py`: 17/17 passed, including request-variant and duration-floor cases.
- `PYTHONDONTWRITEBYTECODE=1 python archive/reference/test_request_revision.py`: 4/4 passed, Python/Node vectors and invalid inputs.
- `PYTHONDONTWRITEBYTECODE=1 python archive/reference/test_incremental_fetch.py`: 32/32 passed, mocked acquisition/cache cases. No real source requests.
- `PYTHONDONTWRITEBYTECODE=1 python delta/reference/test_delta_delivery.py`: 57/57 passed. These isolated synthetic transport fixtures never enter the actual feed/index. Covered upserts, exact requests and origin retention, explicit retraction, protected records, schema/hash/sequence corruption, atomic checkpoints, replay, checkpoint anchoring, portable paths, multi-part batches, oversized record rejection and publisher locks.
- `PYTHONDONTWRITEBYTECODE=1 python delta/reference/test_prepare_update.py`: 44/44 passed. Tests use real local bytes/cache/delta operations with mocked full rebuild/business validation for focused ingestion and timestamp cases; the separate real-data integration below exercises those unmocked gates.
- Combined discovery of both new suites: 101/101 passed.
- `python delta/reference/delta_delivery.py validate --root .`: passed for real baseline sequence 0.
- Real materialize → staging copy of archive → offline rebuild with original `generated_at` → full business validator: passed. Every entity record, collection order and business metadata remained identical, including all 39 original checks. Baseline and archive bytes were not rewritten.

- Real no-change publication against an isolated repository copy returned `{"changed": false, "sequence": 0}`. Both baseline and index hashes stayed unchanged and no batch file was created.

An initial full-validator invocation detected Python `__pycache__` files accidentally produced by local imports under archive/reference. Those generated cache files were removed, and the actual validator was rerun successfully. Production runs use `PYTHONDONTWRITEBYTECODE=1` to keep the strict archive manifest clean. This was not ignored or treated as a successful first run.

Actual retained counts: 160 inventory IDs, 233 sources, 42,418 live groups, 39,291 distinct complete requests, 3,127 incomplete request groups, 75,853 live origins, 8,384 VOD groups, 9,153 VOD origins, 39 checks, 3 environments. Two pilot measurements remain incomplete. No new record, withdrawal, source/media request, channel-identity confirmation or playback test is claimed by this migration.

During production-path validation, fully expanded normalization_basis and over-pooled source incomplete_reasons were rejected by the frozen Schema. Both compatibility issues were fixed in deterministic materialization and covered by dedicated regressions. The gates prevented publication in each failed run. A fresh real-baseline materialization subsequently passed the complete business validator.

A complete unmocked producer integration used an isolated copy of the real baseline and a **synthetic offline change**: append an explicitly marked comment to the retained 1,568-byte M3U from source:092. This is not a fresh network capture and is not published in the real repository. `prepare_update init` passed the full validator; ingest with a hash-bound test review passed rebuild, Schema/business/history gates and published only in the isolated copy: one new snapshot, 9 operations (1 source, 7 existing live rows gaining origins, 1 archive record), one part. All 75,853 old live origins, 9,153 old VOD origins, 39 check records, original snapshot objects including parse times, 300 archive files and frozen baseline bytes remained exactly unchanged. Seven new synthetic origins did not become seven new request identities.

A fresh staging replay of the same SHA returned `added_snapshot_count=0`, `existing_snapshot_reused`, `validated=true`, `published=false`, `publication={"changed":false,"sequence":1}`. Every isolated-repository file hash stayed unchanged. The external private cache retained its accepted SHA/ETag and updated only checked_at; staging/private cache agreed. No archive/historical cache was created or modified. All synthetic bodies/batches stayed outside this delivered repository.

Not executed: user's Mac integration, real future-change acquisition, production delta batches containing new external sources, media testing, repository settings changes. Future batches must run the same business/security gates before publication; the synthetic transport tests do not substitute for them.
