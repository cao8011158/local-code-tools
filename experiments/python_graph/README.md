# Python graph analyzer evaluation (isolated experiment)

Frozen truth was committed before candidate execution. The 39 synthetic labels and
11 real labels are independent human source reasoning, never old graph outputs.
`truth-freeze.json` protects their exact content. Do not delete failing cases.

Python 3.12 is the tested interpreter. This project's `pyproject.toml` and `uv.lock`
are independent of the official toolkit's environment and dependencies.

```powershell
# Run from the local-code-tools repository root. Use an absolute environment path.
$env:UV_PROJECT_ENVIRONMENT = Join-Path (Get-Location) '.tmp/python-graph/venv'
uv sync --locked --project experiments/python_graph
Remove-Item Env:\UV_PROJECT_ENVIRONMENT
$py = '.tmp/python-graph/venv/Scripts/python.exe'
# Harness tests: synthetic-only, no config, index, key, or business checkouts needed.
& $py -B -m pytest -q experiments/python_graph/tests
# Reproducible candidate measurements; output must NOT already exist.
& $py -B experiments/python_graph/run.py --output .tmp/python-graph/reproduce
# Optional read-only real code (three sibling repository checkouts required).
& $py -B experiments/python_graph/run.py --output .tmp/python-graph/with-real --workspace D:\Projects\agentic-trpg --timeout 180
```

On Unix set `UV_PROJECT_ENVIRONMENT` to an absolute `.tmp/.../venv` path and use
`venv/bin/python`. A different Python version/platform is not verified by this run.
No Graphviz installation is needed: use the native Python data structures.

`run.py` creates only owned temporary miniature repositories, source plans and
result JSON below its **new** output directory. It never loads a real catalog,
updates an index or imports business code. Candidate subprocess network connects
are denied and API environment values removed. PYTHONDONTWRITEBYTECODE prevents
business-source bytecode writes. Analysis uses unchanged `lct.extract`/`lct.graph`
only in memory. Official dependencies and formal MCP behavior are unchanged.

`worker.py` is a small output adapter: Graph native CALLS/IMPORTS/INHERITS;
Jedi inferred-name candidates at syntax-supplied locations; Pyan native USES/DEFINES.
Pyan aggregate USES are NOT converted to CALLS. A missing or single result never
proves absence or completeness. Source revision checks need an explicit adapter
and must not be attributed to Jedi/Pyan. No inference engine is reimplemented here.

`syntax.py` only enumerates definitions, call expressions, references and their
execution owner (defaults/decorators outside function bodies, lambdas inside their
own body). It does not guess a target, propagate values or use the truth targets.
Graph nested call mapping includes expression as well as line/column: an outer
attribute call and inner constructor can start at the same column.

Candidate failures are recorded as failures. Passing harness tests only means the
experiment runs and preserves those failures. They do not mean a candidate passed
the relationship requirements. Real sample judgments have partial/unknown target
sets; no whole-repository precision or recall is reported. Jedi measurements
include all-file definition enumeration but only annotated-position inference;
Graph/Pyan build full scoped in-memory relations. Timings are not equal-workload
benchmarks. RSS is a process-tree working-set sum sampled with 25 ms sleeps, including Windows
venv launchers and their actual worker children. It is not an exact peak, and shared
pages may be counted twice. Sampling overhead affects wall time.

The raw complete experimental graphs/plans and temporary Git repositories remain
local under .tmp and are not committed. Only selected raw evidence and compact
comparisons go into review. This is a local evaluation, not an independent review.
