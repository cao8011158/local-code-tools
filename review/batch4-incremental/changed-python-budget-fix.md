# B4-LOCAL-BUDGET development correction

The first candidate compared the previous generation's
`association_evaluations` with local work. That metric records actual work in
the current generation, so after one local build it no longer bounds retained
analysis from the original full build. A later local generation could have
passed the 20,000 association gate incorrectly.

The graph summary now separately stores `association_bound`. Full analysis sets
it to its actual association count; local analysis retains the previous bound
and adds the current local count; identical-capture reuse preserves the bound
while reporting zero actual association executions. The local gate requires a
valid previous bound and falls back to complete analysis when its conservative
sum plus the candidate's local count exceeds 20,000. This metadata is a budget
guard for the supported syntax subset, not proof of arbitrary Python global
candidate interactions. The original `association_evaluations` meaning is
unchanged.

Targeted test covers full → local → identical-capture reuse → local and checks
the retained/growing bound, then invokes the local gate near 20,000 and
asserts a fallback. Together with existing independent callback and import
controls: 6 passed (`changed-python-budget-targeted.log`). Final fast suite
`tests/` plus independent controls: 518 passed, 25 skipped, 18.53 seconds,
exit 0 (`changed-python-budget-fast.log`). Ruff on touched files passed
(`changed-python-budget-ruff.log`). No API, Neo4j or real index was used.
