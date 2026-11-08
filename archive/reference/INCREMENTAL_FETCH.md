# Version-first configuration acquisition

`feed.json` remains the only Mac daily business input. This maintenance tool uses the currently registered source identities in feed; first reconcile additions/removals with the Space GitHub project register without renumbering original inventory. It never walks media, EPG, logo, proxy or JAR/JS dependencies. Never execute fetched configuration code.

## Fetch policy

- GitHub regular files: resolve the registered ref/path through Git tree metadata. Compare the returned **file blob SHA**, not repository update time or branch commit time, against a locally retained snapshot (Git blob SHA can also be derived from the verified local bytes, without changing historical custody evidence). Verify the local byte count, SHA-256 and Git blob SHA before reuse. Unchanged with verified bytes yields `reused_blob_sha` and **no blob body request**. Tree metadata is shared among paths in the same repository/ref during one run.
- Changed blobs, first acquisitions, missing/corrupt local bytes: download that exact immutable blob and verify Git SHA and metadata size. A changed repository commit alone does not force all files to download.
- Raw GitHub `/refs/heads/branch/...` and `/refs/tags/tag/...` registry URLs are recognized. URL query/fragment conditions are never dropped to construct an API URL; those entries use HTTP. Ref names containing slashes are not inferred by this URL parser: explicitly resolve them before use, or use conditional HTTP without removing URL parts.
- GitHub Pages/other HTTP config endpoints: use stored ETag and/or Last-Modified, bound to the exact URL **and verified local archived bytes**. A 304 reuses those bytes. Missing/corrupt cache causes an unconditional request. Unexpected 304 or a cache lost during the request gets one unconditional fallback; a second 304 is an error. No validators/server ignores them: obtain content and compare SHA-256. Conditional requests still incur a request; not every server supports them.
- 403, 429, auth failure and other errors remain failures; no retry loops, access bypass, guessed alternate URLs or loss of previous snapshots. Redirects are reported for review rather than silently followed. HTTP resolves destinations to public IP addresses and pins the checked address for the connection, with normal TLS certificate/hostname verification and no inherited proxy. A failed version check is never called unchanged.
- Existing `sensitive_quarantined` entries are skipped. All new bodies go to a fresh directory **outside** the repository. They remain `downloaded_pending_safety_review` until the normal publication safety gate approves them. The fetcher does not itself certify safety or playback.

## Commands

From repository root, Python 3.10+, existing authorized `gh` login (never embed a token). Keep staging private and outside Git:

    python archive/reference/incremental_fetch.py --root . fetch --staging /absolute/outside-repository/new-run

Use `--source-id source:001` (repeatable) for a bounded run. The default state is `archive/historical/fetch_state.json`. On first adoption, the tool bootstraps verified blob evidence from existing snapshots, so an ETag cache is not required for GitHub savings. Only HTTP validator metadata needs subsequent persistence. The command never modifies feed, archives, task schedule or remote Git. Outputs are `report.json` and any newly downloaded `.body` files in staging.

After safety review, accepted new bytes must be copied unchanged into their content-addressed archive path and imported into the source snapshot registry. Rejected bytes remain outside the repository. Supply a small JSON map of **approved only** source IDs to relative archive paths, e.g. `{"source:001":"archive/sources/source_001/<sha256>.json"}`. Reused records need no map entry:

    python archive/reference/incremental_fetch.py --root . accept --report /absolute/outside-repository/new-run/report.json --accepted /absolute/outside-repository/accepted.json

The acceptance command verifies hashes/lengths and refuses escaped paths. It persists only reuse/approved records to the state file, not staged credentials or body paths. Do not blindly commit the staging report: create a sanitized daily acquisition report with checked time, actual download time where applicable, outcome and version evidence. A version check/304 is not a new content acquisition and must not rewrite prior fetch or check timestamps. Update source records and rebuild only when there is actual source/parse/state change, not simply because a daily clock tick occurred. Keep previous state for failures; quarantine removes its reuse entry.

Feed assembly remains `rebuild_feed.py` and the archived ingestion workflow. Include any new accepted state/report in `archive_files` before validation. The state and reports are maintenance evidence, never additional Mac business inputs. Unchanged source bytes must not cause new snapshots or artificial checks; an all-unchanged run produces no empty Git commit.

## Regression and scope

    python archive/reference/test_incremental_fetch.py
    python archive/reference/validate_feed.py .
    python archive/reference/test_parser_rebuild.py --root .
    python archive/reference/test_feed_boundaries.py
    python archive/reference/test_request_revision.py

Acquisition regression uses fake transports: it proves request decisions and integrity checks, not actual HTTP 304 support by every registered server. This change does not run a second full collection or media test. The initial archive hashes and all business records stay unchanged; only reference implementation and the feed archive manifest are updated. Feed size compression is a separate proposed optimization, not authorized by this fetch-policy change.
