# Jedi authority: corrected implementation boundary

2026-11-02 Asia/Shanghai. User's latest instruction and SESSION_HANDOFF.md supersede earlier PR-2 header repair and PR-3 solver proposals.

## Fixed state and ownership

- Remote implementation baseline: `1e265a9a6e087b87299940c6815f9957b8ceac37`, tree `b550b2a5cf0785c3a28fc956b9220e1f56657a05`, feature `feat/local-only-updates`.
- Merge target: `feat/local-code-tools-import`, last pinned `e3db45fcf1362f0a26e0ab7760b12b4fd408ce64`. No merge authorization.
- New working directory is a **materialization**, with a local Git checkpoint for diff only. It is not remote ancestry and must not be pushed as a replacement history. All 733 materialized remote blobs matched; preserve 653 unmaterialized historical paths when publishing.
- Preserve the paused header patch as evidence only. No automatic continuation of it.
- Root owns architecture, independent tests and review. Developer: `/root/jedi_refactor_developer`, actual `gpt-6-sol`, medium reasoning. Apply batch-dev-review and locality-review.

## Retain / remove / authority

| Responsibility | Owner and decision |
| --- | --- |
| Python target inference (names, aliases, attributes, callbacks, return values, containers, bases and references) | Jedi 0.20.1 public API. Select `get_signatures` for an explicit call context and `infer` for expression values, bases, references and implicit decorator results. Consume applicable tool observations without a second target resolver. |
| Captured sources, safe project paths, UTF-8 positions, catalog mapping, repository version/pin boundary | LCT adapter. Mapping verifies source identity; it must not resolve an assignment RHS. |
| No result, multiple results, unmappable result, external result, query exception | Preserve each observation and original location. No result stays unknown. Observation mapping completeness is not a runtime exhaustiveness claim. |
| Sites and execution phases | AST inventory. Implicit protocol/decorator behavior needs an appropriate Jedi query; unsupported target semantics stay unknown. |
| Provenance, lexical/argument/return dependencies, container writes/reads/negative subscriptions | Source recorder using source positions, binding references and observed Jedi call relations. It records dependencies and uncertainty; it does not evaluate stored callable values, select latest/reaching targets or certify target alternatives. |
| Local updates | Existing indexed owner worklist, reverse supports, negative/prospective writes, immutable snapshot rebinding/publication. Expand relevant dependency closure safely; no whitelist admission or automatic full fallback. |
| Target comparison and override | Remove `resolve/_resolve/adjudicate` and downstream lexical/parameter/field/container target inference; no renamed equivalent. Remove hidden `map_name(statement)` RHS solving, classmethod custom proof and `value_flow` expected/latest target certification. |
| Reuse | Keep one-capture raw observations and dependency-safe reuse. Separate indexing/preparation from per-consumer evidence. |

## Whole production path audit

`Graph.build` currently leaks custom targets through CALLS, implicit decorators, CONTEXT_ENTERS, REFERENCES, IMPORTS and INHERITS. `Analyzer.query -> map_name(statement)` and classmethod preparation also leak into `resolve`. `value_flow.evidence` reconstructs a latest target and compares it to selected targets. All must leave the production decision path together; merely bypassing CALLS' outer adjudication is insufficient.

## Implementation and acceptance sequence

1. Replace the target bridge and graph consumers; remove old inference/certification and introduce a strictly source-only recorder. Migrate persisted evidence contract/version where meaning changes. Keep source indices and function-level scheduling active under the new contract.
2. Validate all target-producing public paths, raw API positions, unknown/error/boundary/multiple outcomes, the first/third counterexample, and the registered callback gap. Inspect source and instrument entry points to prove old methods cannot execute. Review old tests by requirement; do not preserve custom conclusions merely to keep them green.
3. Validate public storage local updates, argument/container subscriptions including negative reads, new/changed/deleted writers, relevant/unrelated edits, old versions, failure without publication, and indexed reads under unrelated growth. Run fast regression with explicit classification of obsolete expectations and any real remaining failures.
4. After architectural and locality gates, run newly built nine-file lifecycle and pinned 83-file cold/warm/query acceptance with phase counters. No reuse of prior runtime snapshots as new evidence. Do not blindly increase the former 20k association budget or repeat identical timed-out runs.

This is one corrected architectural scope within the existing refactor, not a reset of PR-2 review. Preserve PR-1 round2 pass and PR-2 round1 changes_required. PR2-DEFINITION-HEADER-ORIGIN is closed only when independent public-flow evidence proves the correct Jedi target is retained and source identity does not decide target selection. Next PR-2 formal review is round2/3.

Development-time independent API check additionally found that `get_signatures` directly supplies a captured classmethod declaration where callee-value `infer` reports `classmethod.__get__`. It also supplies the contextmanager factory declaration. Query at the actual opening parenthesis, handling UTF-8 and split calls. This is correct API selection, not custom override of a tool result. An inferred `instance` is not a `class` constructor target; retain unsupported call-protocol information instead of changing its kind. See `authority-api-positions.json` and the independent acceptance cases. Empty/error injection covers both semantic Jedi APIs.

## Documented tool boundary

Official API: https://jedi.readthedocs.io/en/latest/docs/api.html . `infer` supplies inferred definitions; `goto` locates a binding, and `get_references` can stop when a search is complicated. Binding/reference output is provenance rather than a complete heap or allocation analysis. The observed registration→callback example returns no Jedi targets; preserve this gap and report it without implementing a solver.
