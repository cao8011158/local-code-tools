"""Compare the captured original/fixed public results, without executing sources."""
import json
from pathlib import Path

root = Path(__file__).parent
old = json.loads((root / 'source-origins-old-semantics.json').read_text())
new = json.loads((root / 'source-origins-review2-semantics.json').read_text())
assert old == new
before = (root / 'source-origins-review2-root-old-sites.json').read_bytes()
after = (root / 'source-origins-review2-root-new-sites.json').read_bytes()
assert before == after
print(json.dumps(dict(head='d2ac250bd4f6563415a7a77a6645d47e7154a7e9',
    legacy_tables_and_meta_equal=True, unpacking_and_missing_sites_byte_equal=True,
    variants=3, legacy_node_count=new['nodes']['count'],
    legacy_edge_count=new['edges']['count'], legacy_site_count=new['sites']['count'])))
