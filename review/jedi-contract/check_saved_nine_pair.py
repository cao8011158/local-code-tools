"""Read-only recheck of retained nine-file outputs; never rebuild or call providers."""
import argparse
import json
import sqlite3
from pathlib import Path

from lct.common import config
from lct.storage import manifest
from tests.test_batch3_actual_acceptance import semantic
from tests.limited_precision_comparison import assert_limited_refinement


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--warm', required=True)
    parser.add_argument('--fresh', required=True)
    args = parser.parse_args()
    c = config(args.root / 'actual-fixture/config.json')
    # These are the original fixture's in-memory build settings.
    c['retained_versions'] = 8
    c['embedding'].update(max_requests=0, max_estimated_tokens=0, max_cost_usd=0)
    other = dict(c, data=str(args.root / 'reviewer-fresh-complete'))
    actual, expected = semantic(c, args.warm), semantic(other, args.fresh)
    folder, _ = manifest(c, args.warm, compatible=True)
    with sqlite3.connect(folder / 'catalog.sqlite') as db:
        sources = {(r, p): t for r, p, t in db.execute('select repository,path,text from files')}
    assert_limited_refinement(actual, expected, sources)
    print(json.dumps(dict(status='pass', compatible=True, tables=len(actual),
                         warm_edges=len(actual['edges']), fresh_edges=len(expected['edges']),
                         sites=len(actual['sites']), sources=len(sources))))


if __name__ == '__main__':
    main()
