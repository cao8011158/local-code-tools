# B4-JEDI-PARSO-CACHE: limited compatibility development

2026-10-31（北京时间）. User authorized fixing newly loaded old Parso cache entries classified as inactive, while preserving ordinary cleanup and source invalidation. Branch `feat/incremental-index-updates` remote baseline `efc90d46bdd74e74325b0460c9578a4303b11d1b`; previous production implementation `d9ecf8538b0078b30edbf0e92dd2f78b2e85bbe4`; merge target remains `feat/local-code-tools-import`. This is a local staging directory without `.git`, and the changes are neither committed nor pushed. Package-context repair already present in `lct/python_incremental.py`, `tests/test_cross_repository_python_incremental.py`, and `docs/INCREMENTAL_UPDATE.md` was preserved.

## Change and validity boundary

Parso 0.8.7 creates `_NodeCacheItem.last_used` from source mtime and restores the same timestamp from disk. Jedi can retain a tree then look up its Parso cache entry directly; at 600 entries Parso's existing age-based cleanup drops a newly inserted old-mtime entry and Jedi raises `KeyError`. `lct.parso_cache_compat.ensure_parso_cache_timestamps` installs an idempotent process-wide wrapper on the exact-version `_set_cache_item` API at `Analyzer` initialization, before Jedi scripts are constructed. It changes only the inserted item's `last_used` to current time and calls the original insertion, preserving `change_time`, source-change invalidation, and cleanup of genuinely inactive items. A different Parso version raises explicitly. `pyproject.toml` now pins Parso 0.8.7 directly; `requirements.lock.txt` already pinned it transitively, and existing `uv.lock` metadata was aligned. No site-packages, cache contents, Jedi target assertions, or analyzer exception policy changed.

| Holder / path | Dependency and maintenance | Consumer / cost |
| --- | --- | --- |
| Parso `parser_cache` entry | Cold parse or disk restore inserts with current `last_used`; hit already refreshes it; source mtime remains `change_time` and invalidates changed files | Jedi's parser cache lookup; wrapper adds one clock read and assignment O(1) per insertion |
| Parso original cleanup | At 600 entries, original cutoff still removes entries older than 600 seconds | Existing O(N) threshold scan remains; no additional global pass, unlimited retention, or index introduced |

The real Parso tests isolate the process-global `parser_cache`, parse an old-mtime file, reload from its actual pickle, change its source mtime and content, and fill the real 600-entry threshold with stale items. They show the fresh entry survives while stale ones are removed. This validates the source-file and cache path, but does not claim actual >10-minute live-tree retention or an end-to-end production workload measurement. The established contextlib/Jedi and cross-repository behavior assertions remain unchanged.

## Verification (Python `/workspace/scratch/413372d9a5a5/lct-round5-review/.venv/bin/python`)

| Check | Result | Exit / evidence |
| --- | --- | --- |
| `python -m pytest -q tests/test_parso_cache_compat.py tests/test_python_review_round3.py tests/test_python_review_regressions.py` | 84 passed, 3.87 s | 0; initial stdout |
| `python -m pytest -q tests/` | 539 passed, 25 skipped, 23.35 s | 0; `parso-cache-development-fast.log` |
| Final targeted including cross-repository tests and version guard | 94 passed, 6.42 s | 0; `parso-cache-development-targeted.log` |
| Ruff changed Python files | All checks passed | 0; `parso-cache-development-ruff.log` |
| `uv lock --offline` | Cannot resolve Jedi 0.20.1 absent from local uv cache | 1; lock metadata aligned without network resolution |

The version-guard assertion was added after the full suite, then targeted regression reran; production code was unchanged between those runs. No services, paid API, real graph, or Drive were used. Formal review round 2/3 has not started. This local development result does not close Batch 4 or authorize a merge.

## Modified-file allowlist

- `lct/parso_cache_compat.py` (new)
- `lct/python_analysis.py`
- `tests/test_parso_cache_compat.py` (new)
- `pyproject.toml`
- `uv.lock`
- `docs/INCREMENTAL_UPDATE.md` (new compatibility paragraph added to existing package-context repair)
- `review/batch4-incremental/parso-cache-development-fast.log`
- `review/batch4-incremental/parso-cache-development-targeted.log`
- `review/batch4-incremental/parso-cache-development-ruff.log`
- `review/batch4-incremental/parso-cache-development.md`
- `review/batch4-incremental/STAGE_REPORT.md`
