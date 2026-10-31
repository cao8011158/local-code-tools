"""Source-only full-analysis oracle; run from the chosen implementation root."""
import argparse
import json
import sqlite3
from pathlib import Path

from lct.common import config, canonical, digest
from lct.storage import build, manifest
from tests.synthetic_support import initialize

SOURCES = {'consumer.py': 'from provider import get_callback\ndef one():\n fn=get_callback()\n fn()\ndef two():\n fn=get_callback()\n fn()\n', 'driver.py': 'from provider import first,second\nfrom worker import execute\ndef run(): execute(first,two=second)\n', 'instance.py': "from provider import first,second\nclass Box:\n def __init__(self,cb): self.handlers={'go':cb}\none=Box(first)\ntwo=Box(second)\ndef left(): one.handlers['go']()\ndef right(): two.handlers['go']()\n", 'provider.py': "def first(): pass\ndef second(): pass\nregistry={'go':first}\ndef get_callback(): return registry['go']\n", 'worker.py': 'from provider import first\ndef execute(one,*,two=first):\n one()\n two()\n', 'writer.py': "from provider import registry,second\nregistry['go']=second\n"}

def main():
    parser=argparse.ArgumentParser()
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prepare")
    group.add_argument("--config")
    parser.add_argument("--data")
    parser.add_argument("--output")
    args=parser.parse_args()
    if args.prepare:
        _,repo=initialize(Path(args.prepare))
        (repo/"src/weights.py").unlink()
        (repo/"docs/guide.md").unlink()
        for name,text in SOURCES.items():
            (repo/"src"/name).write_text(text)
        print(Path(args.prepare).resolve()/"config.json")
        return
    if not args.data:
        parser.error("--data is required with --config")
    c=config(args.config)
    c["data"]=args.data
    built=build(c,offline=True,lexical_only=True)
    folder,meta=manifest(c,built["version"])
    result={}
    for name,tables in (("catalog.sqlite",("nodes","edges")),("graph-sites.sqlite",("sites","query_observations","import_requests","import_dependencies","analysis_reads","analysis_watches","analysis_input_scopes","analysis_input_members","analysis_input_consumers","value_nodes","value_edges","value_reads","simple_python_certificates","passive_python_certificates"))):
        with sqlite3.connect(folder/name) as db:
            for table in tables:
                columns={r[1] for r in db.execute(f"pragma table_info({table})")}
                if "data" in columns:
                    rows=sorted(canonical(json.loads(raw)) for (raw,) in db.execute(f"select data from {table}"))
                else:
                    rows=sorted(tuple(row) for row in db.execute(f"select * from {table}"))
                result[table]=dict(count=len(rows),sha256=digest(canonical(rows)))
    result["meta"]={k:meta.get(k) for k in ("simple_python_certificate","value_flow_coverage","analysis_input_coverage")}
    raw=json.dumps(result,sort_keys=True,indent=2)
    if args.output:
        Path(args.output).write_text(raw+"\n")
    print(raw)

if __name__ == "__main__":
    main()
