# B3-002 artifact membership — local developer report

Base implementation: `7c50563cd695aed018bd451dec9d05a631792525`.
Workspace: `lct-batch3-storage-work` source snapshot, without Git metadata.
Status: local candidate, not committed or pushed. Scope: build/validation,
backup membership, focused tests, and this contract/report. Root handles
independent review and remote operations.

Root cause: build enumerated every candidate directory member when deriving
manifest checksums, including transient SQLite/atomic-write files. Backup
enumerated every file in complete version directories. The former could fail
on disappearance or unintentionally bless a non-index file; the latter could
include unrelated files in a portable archive.

The required set now derives from the catalog plus generated partition specs.
Build checks for nonempty journal/WAL after SQLite closes and before hashing;
validation checks them before opening SQLite. Required files must be regular,
not symlinks. The build streams each artifact in 1 MiB chunks, deriving
checksum and size from the same opened stream without retaining all artifacts
in memory. Backup loads each version manifest once and uses validated
membership, plus the manifest and
optional build state. Retained incompatible versions remain backed up and
restore retains its existing compatibility decision. Current publication and
failure-state behavior remain in the original transaction order.

Verification and limitations are recorded below. No API, Neo4j, business
repository, real-scale, or external storage validation was performed.

| Check | Result | Elapsed | Evidence |
| --- | --- | ---: | --- |
| `.venv/bin/python -m pytest tests/test_artifact_membership.py -q --junitxml=.tmp/batch3-artifact/focused.xml` | Exit 0; 6 passed | 1.274 s wall (pytest 0.90 s) | `.tmp/batch3-artifact/focused.log`, `focused.xml` |
| `.venv/bin/python -m pytest tests -q -k 'not neo4j' --junitxml=.tmp/batch3-artifact/offline-tests.xml` | Exit 0; 421 passed, 1 skipped, 12 deselected | 14.202 s wall (pytest 11.84 s) | `.tmp/batch3-artifact/offline-tests.log`, `offline-tests.xml` |
| `.venv/bin/python -m pytest -q -k 'not neo4j' --junitxml=.tmp/batch3-artifact/offline.xml` | Exit 2 at collection: experiment requires unavailable `psutil` | 1.326 s wall | `.tmp/batch3-artifact/offline.log`, `offline.xml` |
| `.venv/bin/python -m pytest tests/test_artifact_membership.py tests/test_portable_restore.py tests/test_lifecycle.py -q --junitxml=.tmp/batch3-artifact/stream-focused.xml` | Exit 0; 17 passed on revised streaming candidate | 3.735 s wall (pytest 3.41 s) | `.tmp/batch3-artifact/stream-focused.log`, `stream-focused.xml` |

The initial candidate passed the offline `tests/` regression before inspection
identified all-artifact byte retention during finalization. That candidate
was adjusted locally before push or formal review. Only focused artifact,
lifecycle, and portable-restore tests were rerun after this adjustment; the
previous 421-pass result does not describe the revised candidate. Root will
perform the combined regression.

The quick regression is explicitly restricted to `tests/`; repository-root
collection includes `experiments/python_graph/tests/test_experiment.py`, whose
import of `psutil` failed in this shared environment. The 12 Neo4j-selected
items were deselected. The skipped item is reported by pytest. No test had
provider access through this path; fixture builds were lexical-only.

Compared with the baseline source snapshot: five files, +262/-22 lines.
No Git SHA
exists for the local candidate; root must review the actual workspace delta.
