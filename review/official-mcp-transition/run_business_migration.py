"""Acceptance invocation of the terminal/offline projection maintenance API."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lct.common import canonical
from lct.neo4j_graph import Neo4jGraph

with Neo4jGraph(os.environ['LCT_TEST_NEO4J_URI'], os.environ['LCT_TEST_NEO4J_USER'],
                os.environ['LCT_TEST_NEO4J_PASSWORD'], os.environ['LCT_TEST_NEO4J_DATABASE']) as graph:
    result = graph.migrate_projection('batch3-real-staged-20261029-7a235bf36f',
        '20261029T111748-7a235bf36f',
        'db11a1db19ed3f524ba8309184ce6ccc27f44531830f83a0a467736d5150d568')
print(canonical(result))
