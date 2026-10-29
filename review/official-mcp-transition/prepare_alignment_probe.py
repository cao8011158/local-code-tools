"""Prepare isolated test-only diagnosis; never edit the formal tests or production code."""
from pathlib import Path
root=Path(__file__).resolve().parents[2]
p=Path('/tmp/lct-official-review-probes');p.mkdir(exist_ok=True)
s=(root/'tests/test_neo4j_bulk_import.py').read_text().replace('1200 + 6000 + 4800 + 2','1200 + 6000 + 6000 + 601 + 2').replace("version='bulk-v').single()['c'] == 4800","version='bulk-v').single()['c'] == 6000")
(p/'test_bulk_probe.py').write_text(s)
s=(root/'tests/test_neo4j_staged_import.py').read_text().replace("lease_until:0, state:'writing', storage_format:'chunks-v1'})", "lease_until:0, state:'writing', storage_format:'chunks-v1', projection_schema:'native-boundary-v2'})")
(p/'test_staged_probe.py').write_text(s)
print(p)
