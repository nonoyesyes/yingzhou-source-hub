# Offline feed rebuild

`feed.json` remains the sole daily business input. This reference directory is a reproducible maintenance tool, not another Mac consumer data feed.

Requirements: Python 3.10+, `jsonschema` for validation; Node.js for cross-language rr1 regression. Do not execute source-supplied JAR/JS. No command below fetches source, EPG, logo or media resources.

From repository root:

    python archive/reference/rebuild_feed.py --root .
    python archive/reference/validate_feed.py .
    python archive/reference/test_parser_rebuild.py --root .
    python archive/reference/test_feed_boundaries.py
    python archive/reference/test_request_revision.py

The rebuild reads the current feed's inventory, source snapshot registry, prior checks and environments, and only the referenced local source bytes. It statically reparses all retained snapshots and regenerates standardized entries, rr1 grouping and complete origins. It rewrites only feed.json, preserving archive source/evidence/history bytes. `--input-feed PATH` selects an earlier feed registry; that feed must reference the same locally available archive. `--generated-at ISO_TIME` allows exact repeatability for regression. Parse times describe this offline parse; fetch/check timestamps remain unchanged.

Format detection permits UTF-8 BOM, whitespace and legal comments outside JSON strings. The comment remover does not modify URLs, escapes or comment-like characters inside strings, does not repair trailing commas and rejects malformed documents. Invalid configuration remains unsupported rather than being silently repaired. JSON display group/name/EPG/logo metadata is kept separately from unresolved request conditions. Unknown headers/options/runtime conditions are never guessed complete.

All live subscription `url` values and newly discovered proxy configurations stay unexpanded dependencies, with original value/base URL/deterministic resolution and no media verification. Previously published proxy candidates retain original identity and incomplete state. Metadata and reference resolution do not fetch resources.

The four reviewed JSONC files contain 693 site items and four live configurations. The rebuild exposes each site origin and each unexpanded live dependency. Duplicate static site records may share a group only with their full effective dependencies and relative base preserved. Existing checks never become new observations: only candidate grouping references may migrate.

Regression `test_parser_rebuild.py` uses the review baseline commit `afd60eb69827b82b7bb562147ba480c0bb10a8ba` from local Git history (no fetch), or `--baseline-feed PATH`. It verifies all baseline live origins, original inventory, 39 check facts and original archive hashes. The fixed reader restores shared values and origins using feed.json alone.

For future updates, run these regressions after changing the parser or generator. Never treat Schema success alone as proof that JSONC and request-condition parsing are correct. Unknown channel names remain unknown; no new global dictionary coverage is implied.

Daily update 2026-11-08: empty source names remain empty strings with unknown matching status. Existing check snapshot bindings, including null, are never backfilled from newly fetched material. Repeated archive paths and logo/EPG metadata may use the existing in-document `$value_ref` representation; `read_feed.load_feed` expands these using only feed.json, without network or archive reads. Request URLs/conditions remain inline and unchanged. The schema explicitly allows these references. This limits file growth without gzip, a second business input, or dropping origins.
