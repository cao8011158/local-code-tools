# 4B pilot review round 1: general certificate manifest correction

Fixed review baseline `aaa874708ad700a967eed437f6b0fc21606bbf89`; confirmed P2 `B4-GEN-01-CERT`. General local builds had retained the predecessor's whole-capture `simple-python-v6` marker even when a newly selected complex module invalidated that certificate. The analyzer's semantic rows matched fresh full output, but the manifest value and resulting certificate/coverage sidecar disagreed.

Only `lct/storage.py` production code changed: when `local_metrics` denotes `general-passive-component`, the manifest writes `simple_python_certificate=None`. Strict-v6 local and identical-capture branches keep their previous expression. Existing `split_graph` then emits an empty `simple_python_certificates` table and `value_flow_coverage=partial`; the bounded general analysis never claims the old v6 whole-capture proof.

The added regression starts with a full v6 capture, performs a v6 local update, adds unchanged original `_execution.py` and `errors.py` to enter general, verifies None/partial/empty strict certificate table and all semantic records against fresh full, then verifies identical-capture reuse and another general update preserve None/partial and fresh full equality. The independent 13-case controls remain untouched and compare every semantic sidecar table to full. Three older independent parameterized tests now accept the separately named general route with precise selected/reused file assertions; each retains its fresh full oracle. No parser, graph, Jedi, proof policy, or syntax acceptance changed.

Focused command: `python -m pytest -q tests/test_general_passive_incremental.py review/batch4-incremental/test_general_legacy_semantics_independent.py review/batch4-incremental/test_dictionary_flow_independent.py::test_unproved_dictionary_effects_keep_full_fallback review/batch4-incremental/test_dictionary_local_independent.py::test_new_unproved_effects_are_not_admitted review/batch4-incremental/test_mixed_dictionary_independent.py::test_context_does_not_admit_registry_escape_or_missing_exports` → **37 passed / 10.66s** (`general-passive-cert-targeted.log`). A single post-change `tests` quick run is in `general-passive-cert-fast.log`.

The post-change quick run reports **647 passed, 27 skipped / 42.92s**. Changed files and SHA-256 (diff line totals against fixed 4B pilot copy):

| File | + / - | SHA-256 |
| --- | ---: | --- |
| `lct/storage.py` | 2 / 1 | `36f4a7066cad0e6a625974056fc406c378234c7f38fb8996b87afe5533734561` |
| `tests/test_general_passive_incremental.py` | 23 / 3 | `86dd206726e1ced1d7788571e216d52a4a7f881cade280b7ae9afb835fe3233a` |
| `review/batch4-incremental/test_dictionary_flow_independent.py` | 4 / 1 | `af70cb4ee8ea872550284c5528337c98019e93075216e8d57a57cefc631d6b9b` |
| `review/batch4-incremental/test_dictionary_local_independent.py` | 4 / 1 | `2b6ead890433f1002c5b20c115c1a4e6ebd87f7f180b5440d9b682adafdf9433` |
| `review/batch4-incremental/test_mixed_dictionary_independent.py` | 5 / 1 | `97e5b763492c1f5b748572f7ea30a8228753ca1101248f92b2c903dc6391c96e` |

No push, merge, Stage report, retained draft, or root independent test edits.
