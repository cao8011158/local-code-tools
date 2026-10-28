# Batch 3 actual business Neo4j acceptance — bounded attempt

Result: **BLOCKED by the owned service's transaction memory ceiling in both bounded attempts; import and downstream read/MCP acceptance have not passed.** This is a concrete environment/resource failure, not evidence of a confirmed P0/P1 code defect or a production capacity result. No parser, importer, business repository, or paid service was changed. The second attempt used only an isolated test launcher with a 1 GiB Java heap.

## Identity and inputs

- Reviewed code checkpoint: `42b0acd95fd503551c22447613738c8d9e62bfe9` (report-only remote head `2c0df82857ce54d18ff3e0c6a92c6beb0ad5f8de` supplied by root). This isolated copy does not have a Git checkout; SHA identity is inherited from the prior independent verification.
- Authoritative validated SQLite graph: `/tmp/lct-b3-locality-fixed-20261028`, explicit version `20261028T122745-62019ae507`. The `batch3-preflight/business-config.json` data field was overridden in memory only. The source and SQLite data were neither rebuilt nor changed.
- Isolated target namespace: `batch3-business-20261028`. Owned local Neo4j Community 5.26.0 launcher `.runtime/neo4j-batch1/run_with_neo4j.py`, with 384 MiB JVM heap and its existing service configuration; Python from `lct-round5-review/.venv`.
- Reproduction: from `lct-batch3-fixes-review`, run `timeout 180s /workspace/scratch/413372d9a5a5/lct-round5-review/.venv/bin/python /workspace/scratch/413372d9a5a5/.runtime/neo4j-batch1/run_with_neo4j.py "$PWD" /workspace/scratch/413372d9a5a5/lct-round5-review/.venv/bin/python review/batch3-real-neo4j/accept_business_graph.py`. It starts/stops its owned service. Use a fresh owned database/namespace if a previous completed scope exists.

## Actual calls and observations

| Phase | Actual evidence | Result |
| --- | --- | --- |
| SQLite `load_snapshot(config, explicit_version)` | Returned in 7.135 s after manifest/artifact/SQLite validation. 5,957 nodes; 42,459 logical edges; 22,416 sites; fingerprint `69395b38de9b5b67d5f349425f4281e0189b04f9d089e5eeebca23219afebf3a`. Wrong version raised `ToolError`. | PASS |
| Import guards | `load_snapshot` passed the 50,000/500,000 and 128 MiB canonical snapshot checks. Maximum observed raw node/edge JSON was 7,843 bytes, versus the 1 MiB record bound; graph JSON was 61,164,381 bytes. This does not establish transaction memory sufficiency. | PASS for preflight |
| Evidence preservation in SQLite | `analysis_limited=true`; 10,341 UNKNOWN-origin sites and 10,376 UNKNOWN-origin edges. No completeness upgrade or candidate normalization was done. | PASS for source inspection |
| Neo4j missing scope/version | `snapshot_info` refused wrong namespace and wrong version before import, as expected. Recorded at 13.973 s. | PASS before import |
| Native full import | `Neo4jGraph.import_snapshot` reached the edge batch loop (`lct/neo4j_graph.py:207`) and Neo4j raised `Neo.TransientError.General.MemoryPoolOutOfMemoryError`: extra 2.0 MiB would exceed `dbms.memory.transaction.total.max` of 268.8 MiB, 268.0 MiB already used. Script ended after 20.975 s; launcher stopped the service. | BLOCKED |
| Idempotence, database counts, selected raw node/relationship comparisons, MCP | Script contains checks for all of these but execution never reached them. Atomic rollback of this actual transaction was not independently queried after the failure. | NOT RUN / NOT PROVEN |

The selected exact-comparison probes, if the resource issue is resolved, cover module/class/function raw nodes and repository filters; a real `_ability_scores` CALLS source with 16 expected edges including UNKNOWN evidence; one snapshot, all logical edges, and native versus boundary relation counts; idempotent reimport; wrong-scope refusal; and the four loopback HTTP MCP read-only tools with fixed namespace/version. The MCP verifier is a local synthetic test credential, not external issuer integration.

Raw log: `.tmp/batch3-real-neo4j/run.log` (SHA-256 `f8a759994f1ef51488119343d9829d34b8884858952a8bb02a50812fc171f026`). Structured measurements: `.tmp/batch3-real-neo4j/measurements.json`. Acceptance script: `review/batch3-real-neo4j/accept_business_graph.py` (SHA-256 `b2e17b3bb70c882837cf4bdba39c10f2e85f2c9650918322fb68f30ffcf481aa`). The launcher log contains no additional useful textual diagnosis in this attempt.

## Boundary and next step

The existing one-transaction importer has a fixed 300-second transaction timeout; both attempts failed first on Neo4j transaction memory. See the second attempt below. The root should evaluate an appropriately resourced owned service or an explicitly scoped design change, then independently review this script and rerun the remaining acceptance. A larger service succeeding would establish that configuration's observed behavior, not a universal production throughput guarantee. The business graph remains partial by design because `analysis_limited=true`. The main agent interpreted the user's instruction to continue after the documented recommendation as proceeding with the five external-candidate variations while retaining UNKNOWN; this was not an explicit user waiver of the limitation.

## Authorized isolated 1 GiB retry

Root reviewed the first failure and authorized one bounded test-only run with Java `-Xmx1024m` while retaining the 128 MiB page cache. `review/batch3-real-neo4j/run_with_neo4j_1g.py` is a separate launcher; the original launcher and Neo4j configuration were untouched. Command from the same repository directory:

`LCT_BUSINESS_ACCEPTANCE_OUTPUT=measurements-1g.json timeout 180s /workspace/scratch/413372d9a5a5/lct-round5-review/.venv/bin/python review/batch3-real-neo4j/run_with_neo4j_1g.py "$PWD" /workspace/scratch/413372d9a5a5/lct-round5-review/.venv/bin/python review/batch3-real-neo4j/accept_business_graph.py > .tmp/batch3-real-neo4j/run-1g.log 2>&1`

The revised acceptance script prepares the node ID set and CALLS counts once, checks the previously failed namespace directly before import, and calls `graph_status` in its MCP phase if reached. It retains the first logs and writes separate second-attempt measurements.

| Phase | Actual evidence | Result |
| --- | --- | --- |
| Validated SQLite graph | Same counts/fingerprint/UNKNOWN evidence as above; 6.774 s. | PASS |
| Rollback of first failed transaction | Cypher `MATCH (x) WHERE x.namespace=$ns AND x.version=$v RETURN labels(x), count(x)` returned no records. Therefore zero snapshot, node, or edge records remained in this namespace; checked at 8.658 s. | PASS for first failure |
| Scope guard | Wrong namespace and version were refused at 8.917 s. | PASS |
| Effective service settings | `SHOW SETTINGS` returned `dbms.memory.transaction.total.max=716.80MiB` and page cache `128.00MiB`. It reported configured `server.memory.heap.max_size=384.00MiB`, which reflects the unchanged conf file; the Java `-Xmx1024m` command and derived 716.8 MiB transaction ceiling show the effective Java heap override for this process. | OBSERVED |
| Import | The single transaction reached its commit, then Neo4j raised `Neo.TransientError.General.MemoryPoolOutOfMemoryError`: another 2.0 MiB would exceed the 716.8 MiB transaction ceiling, with 715.0 MiB already used. Elapsed 19.308 s, command exit 1; launcher terminated service. Post-second-failure rollback was not queried because the service was stopped and another start was outside the one-run authorization. | BLOCKED |
| Idempotence, raw comparisons, counts, HTTP MCP | Still not reached. The HTTP `graph_status` probe in the script would compare complete raw site/source evidence but did not run. | NOT RUN |

Second raw log: `.tmp/batch3-real-neo4j/run-1g.log` (SHA-256 `93ee52a7b44c6a10a6a4221484bc827c609811d1cdca2628da47311e472c5bf7`); structured record: `.tmp/batch3-real-neo4j/measurements-1g.json`. Revised script SHA-256 `64cc4f308e3bdeb35324449014356809dc7a5de47eaa7c44897f63b39b4c162e`; isolated launcher SHA-256 `bb0343f71acc3885d276116e06e9aa9816cd7c2dd578f91907b642c20e7986bb`. Syntax compilation passed. No Neo4j Java process remained after launcher exit.
