# Offline parser correction results

Review and fetched main baseline: afd60eb69827b82b7bb562147ba480c0bb10a8ba. Remote main was read before work and matched that commit. No rollback, source/EPG/logo/media request or third-party JAR/JS execution occurred.

## Actual source reconciliation

- source:NEW-015: tvbox_txt -> jsonc; 276 original sites retained as origins, associated with 275 distinct site groups; one unexpanded live configuration; 518 structured reference values.
- source:NEW-016: tvbox_txt -> jsonc; 29 sites retained, 29 groups; one unexpanded proxy live configuration; 55 reference values.
- source:NEW-018: tvbox_txt -> jsonc; 108 sites retained, 108 groups; one unexpanded live configuration; 227 reference values.
- source:extra-957225aa1a904c8a: tvbox_txt -> jsonc; 280 sites retained, 279 groups; one unexpanded proxy live configuration; 520 reference values.

All 693 original sites are accounted for. The four configurations yield no new media candidates and remain partial because the live dependencies are not fetched. Their exact source bytes were unchanged. Recursive credential-key and literal credential pattern inspection of these four snapshots found no new suspected private values; the original three quarantined sources remain quarantined. This is not copyright or service availability certification.

source:extra-ac27c1ba25e4bb35: all 1,230 HTTP(S) origins are reassessed by the corrected generator. Plain group is retained as display metadata, not a request condition. All 1,230 have complete requests and correct rr1; 243 match already-complete request groups. No hardcoded count-based boolean edits were made. There remain 220 genuinely incomplete primary candidates across all sources. Their reasons include unsupported transport, unknown directives, multi-URL syntax, manifest transforms, relative/non-URL values, proxies and dollar suffix syntax.

One other malformed JSON snapshot (source:extra-6a4fbc81a20ce0ad) previously fell through to TXT with zero candidates. It now remains unsupported rather than being repaired. Previously parsed valid JSONC files still parse successfully without trailing-comma repair.

## Final arrays

160 original inventory items; 233 sources; 23,638 live primary candidates; 23,418 distinct complete requests; 220 incomplete candidates; 27,287 live origins; 3,909 VOD primary records and 3,929 VOD origins. Names: matched 5,197; ambiguous 9; unknown 18,432. No bulk matching upgrade was applied.

39 checks preserved: 34 historical summaries and five pilot records. Status totals remain incomplete 11, blocked 10, fail 18. The two actual measurements remain incomplete. All observed facts and timestamps are unchanged; only deterministic grouping references may move. All non-reference archive bytes and the complete original inventory were compared against the baseline.

## Executed commands and results

From repository root, with PYTHONDONTWRITEBYTECODE=1:

- `python archive/reference/rebuild_feed.py --root .`: completed offline, using only feed registry and archive source bytes.
- `python archive/reference/validate_feed.py .`: full fixed Schema, references, bytes/hashes, snapshot locations, rr1, check conditions and statistics passed.
- `python archive/reference/test_parser_rebuild.py --root .`: 18/18 passed; see parser_rebuild_results.txt.
- `python archive/reference/test_feed_boundaries.py`: 15/15 passed, including actual request variant, exact integer-millisecond floor and single-file shared-value/origin handling.
- `python archive/reference/test_request_revision.py`: four test methods passed, covering seven cross-language valid vectors and 21 invalid inputs.
- A second `rebuild()` with identical generated_at produced byte-identical feed.json. Source fetching and check times were never synthesized.

During development, full validation exposed two inferred Schema gaps (JSON-pointer origin locators incorrectly requiring line-only role, and missing diagnostic/reference fields). These were fixed with explicit types rather than bypassing validation. A generated Python cache was removed from the working publication directory before final manifest validation.

No media/quality test, source fetch, EPG/logo fetch, runtime plugin execution or global channel-dictionary expansion was performed. Existing unavailable source bodies and historical evidence gaps remain recorded. Relative references are resolved syntactically only, never asserted available. Git publication is performed separately after this local report.
