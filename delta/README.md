# Incremental delivery, version 1

The existing `feed.json` is now the **frozen initial baseline**, not a continually rewritten latest feed. Its bytes and the archived material it references remain unchanged. New consumers read `delta/index.json`, import the baseline once, then apply every listed batch in sequence. Existing consumers can still read the frozen feed, but must upgrade to receive future updates. This transport is `source-hub-delta.v1`; a materialized business state is still `source-hub-feed.v1`. It is not a claim that draft.2 had this transport.

The index contains a baseline path, raw byte count/SHA-256, fixed Git commit, semantic state SHA-256, and a contiguous ordered list of manifest paths/byte counts/hashes. Batch manifests and operation parts are immutable; a new publication appends them and updates the index in the same normal Git commit. No data change means no batch and no empty Git commit. Parts are capped at 8 MiB; an oversized single entity stops publication rather than silently splitting its origins. The small index, not the baseline, is the everyday download. A client should read the index and all referenced files at one fixed commit, not mix moving-main versions.

## Mac integration contract

Python reference implementation: `delta/reference/delta_delivery.py` (Python 3.10+ and jsonschema). It uses the existing reader's shared-value expansion; new operation values are fully self-contained, with no shared-value or archive dependency for business interpretation. Archive reads are needed only for evidence validation, not to interpret the candidate.

1. On first use, download the baseline at `baseline.git_commit`, verify its raw length/hash, expand its shared values, and build entity tables. Preserve the explicit collection order. Verify `state_sha256`.
2. Read each manifest after the saved sequence. Require contiguous sequence, baseline identity, previous manifest hash and before-state hash. Verify every part length/hash before applying anything.
3. Apply `upsert` by collection/key. A value replaces a whole entity, including all retained origins; `before_sha256=null` means insertion and a non-null value is an exact precondition on the previous complete entity. An existing request with new provenance is an update, not a new duplicate line. Complete live grouping remains rr1-based; different effective conditions remain different requests. VOD identity/dependencies keep the existing assembler rules.
4. `retract` requires an explicit nonempty reason and matching prior hash. A temporary fetch failure or missing upstream item is not a retraction. Original inventory, archive references and check facts cannot be retracted or overwritten. Old source snapshots and candidate origin identities cannot be silently removed by an upsert. Explicitly retracted entities remain recoverable from immutable prior batches/baseline. A record whose old origin needs correction should be reviewed, not silently replaced.
5. Replace top-level business metadata with `metadata_after`, and collection ordering with `order_after`. These include actual summary/deduplication fields, not just counts inferred from new rows. Verify the resulting state hash, then commit the complete transaction and sequence/hash cursor atomically. Replaying an already committed batch is a no-op; never apply it twice. A gap, same sequence with changed hash, rollback, bad hash, missing dependency or bad precondition stops consumption without advancing the cursor.
6. Maintain local observations separately. Imported names and cloud checks do not establish channel identity or local playback quality. Existing incomplete checks remain incomplete.

Canonical state/hash bytes are Python-compatible strict JSON: UTF-8, sorted object keys, compact separators, unescaped Unicode, no NaN/Infinity; the model has `metadata`, `entities` and `order`. All published numeric business values use existing feed semantics. `rr1` remains a separate, unchanged request-byte rule; do not confuse it with state hashes. `delta/reference/source-hub-delta.v1.schema.json` defines index/manifest/part types. Paths are portable relative POSIX paths with no traversal, absolute components or backslashes. Entity keys use existing source-hub IDs; top-level arrays materialize in recorded order. Nulls and record field meanings remain those of the fixed feed Schema.

With a local checkout containing the referenced files:

    python delta/reference/delta_delivery.py sync --root . --checkpoint /outside/repo/mac-state.json
    python delta/reference/delta_delivery.py materialize --root . --output /outside/repo/current/feed.json
    python delta/reference/delta_delivery.py validate --root .

`sync` locks and atomically saves a complete local state/checkpoint, not just a cursor. A real Mac database implementation must transact its rows and cursor together. Stale `.lock` files require checking the process before recovery; do not blindly remove them. Network fetching and the user's Mac implementation are not performed by this reference tool.

## Producer workflow

This is the current producer workflow. The archived [INCREMENTAL_FETCH.md](../archive/reference/INCREMENTAL_FETCH.md) predates delta delivery and is itself listed, with its byte count and hash, in the frozen baseline's `archive_files`; keep it unchanged. Its statement that `feed.json` is the Mac daily input and its repository-root fetch/accept/rebuild and cache-persistence instructions are historical and superseded here. Its acquisition [fetch policy](../archive/reference/INCREMENTAL_FETCH.md#fetch-policy) remains applicable; it does not authorize the old root-based workflow. Use the staging commands and external mutable cache below, not the archived command examples.

Never run `rebuild_feed.py` or `incremental_fetch.py` with the repository root after migration: they read or overwrite root `feed.json`. Do not modify the frozen baseline or immutable referenced archive bytes. Use an outside-repository staging root and the **materialized latest state** instead:

1. Fetch latest main normally; verify access and existing worktree. Create fresh outside-repository staging from the latest delta state with the maintained entry point:

       PYTHONDONTWRITEBYTECODE=1 python delta/reference/prepare_update.py init --root /repo --staging /work/run --cache /work/cache/fetch-state.json

   It verifies and copies exactly the retained archive files, materializes the latest state, and records the base state hash. It never changes the frozen baseline. Mutable fetch cache lives outside the repository, not in immutable `archive/historical`; missing cache safely falls back to verified archived bytes.
2. Run the existing fetcher against the staging root, using the local mutable cache and a fresh download directory outside that staging root:

       PYTHONDONTWRITEBYTECODE=1 python /repo/archive/reference/incremental_fetch.py --root /work/run --state .fetch_state.json fetch --staging /work/downloads --source-id <registered-source-id>

   Resolve the enabled entries from the saved project/entry registry and repeat `--source-id` for that authorized set; do not treat every retained historical/dependency URL as permission for a new fetch. Follow the archived [fetch policy](../archive/reference/INCREMENTAL_FETCH.md#fetch-policy): version-first GitHub blob SHA, verified-cache reuse, conditional HTTP fallback. Only registered source/config acquisition is allowed. No media/EPG/logo access or third-party code execution. Quarantined sources remain excluded.
3. Inspect newly downloaded bytes for publication safety. Create a review file bound to the exact bytes, not a blanket approval:

       {"schema_version":"source-hub-safety-review.v1","decisions":[{"source_id":"source:...","sha256":"<64 lower-case hex>","decision":"publish","reason":"reviewed_public_configuration"}]}

   `decision` is `publish` or `quarantine`; missing decisions remain pending. This is the agent's recorded safety review of already authorized source collection, not permission to disclose private credentials. Do not include secrets in reasons. Ordinary public signed URLs remain exact. Unreviewed/quarantined bodies stay outside the repo. The tool matches each result to a registered source/URL and verifies exact bytes and Git blob SHA where present.
4. Ingest and validate through the reproducible wrapper:

       PYTHONDONTWRITEBYTECODE=1 python delta/reference/prepare_update.py ingest --root /repo --staging /work/run --report /work/downloads/report.json --review /work/review.json --cache /work/cache/fetch-state.json --publish

   The wrapper appends approved new snapshots, reuses existing identical snapshots, rebuilds offline, preserves unchanged snapshot/source parse times, retains all old origins/check facts and runs the full business validator plus delta history invariants. No approved new bytes means no rebuild. Stale staging fails instead of overwriting newer published state. With `--publish`, it copies only validated new immutable archives into the repo and publishes the delta. Omit that flag to inspect the validated candidate first. Outcomes report pending/quarantined/failure states without inventing records or deleting history.
5. Run all existing offline Schema/business, JSONC/group actual-source, rr1, request-variant, duration-floor and incremental-fetch regressions against staging; run the delta/prepare regressions too. Standalone `delta_delivery.py publish --root /repo --feed /staging/feed.json` remains available for an already prepared candidate. It runs the full business validation gate. Explicit reviewed withdrawals can be supplied there as `--retractions FILE` with `{collection: {entity_id: reason}}`; no inferred withdrawals. The Python `publish()` function is a transport primitive used by synthetic tests, not a replacement for the production gates.
6. Re-read/validate the whole chain, materialize and run full business validation in staging again, then stage only the related delta/index, immutable parts/manifests and approved new archive files. Normal commit/push to main; no force/settings changes. Verify remote main contains the commit and fetch fixed-commit index/manifest/parts to verify readability and bytes. Do not claim success before this check.

Existing check linkage changes caused by a future parser migration are intentionally blocked by immutable-check admission; review and explicitly version such a migration rather than quietly rewriting historical facts. A batch part write interrupted before index publication may leave unreferenced immutable files; the index still identifies the last complete state. Inspect and quarantine only those unreferenced artifacts before retry, never edit a referenced batch. Publisher lock prevents simultaneous local writers; normal Git non-fast-forward rejection protects concurrent remote updates and requires refresh/rebase/recompute, never force.

## Initial migration

Sequence 0 contains the real current feed only, not a synthetic data batch and not a new crawl. Existing source, origin, request and check counts remain unchanged. The old baseline fixed commit and exact bytes are recorded in the index. The initial delta directory does not claim new sources or new media measurements. Fixtures/tests are isolated reference material, not published source records.
