"""Owned acceptance-only launcher with 1 GiB heap and unchanged Neo4j configuration."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from neo4j import GraphDatabase

ROOT = Path(__file__).resolve().parents[3] / '.runtime/neo4j-batch1'
HOME_DIR = ROOT / 'neo4j-community-5.26.0'
command = ['java', '-Xms128m', '-Xmx1024m',
           '--add-opens=java.base/java.nio=ALL-UNNAMED',
           '--add-opens=java.base/java.io=ALL-UNNAMED',
           '--add-opens=java.base/sun.nio.ch=ALL-UNNAMED',
           '-cp', str(HOME_DIR / 'lib/*'), 'org.neo4j.server.CommunityEntryPoint',
           '--home-dir=' + str(HOME_DIR), '--config-dir=' + str(HOME_DIR / 'conf')]
env = dict(os.environ, LCT_TEST_NEO4J_URI='bolt://127.0.0.1:17687',
           LCT_TEST_NEO4J_USER='neo4j', LCT_TEST_NEO4J_PASSWORD='synthetic-lct-batch1-only',
           LCT_TEST_NEO4J_DATABASE='neo4j')
(Path(__file__).resolve().parents[2] / '.tmp/batch3-real-neo4j').mkdir(parents=True, exist_ok=True)
with (Path(__file__).resolve().parents[2] / '.tmp/batch3-real-neo4j/test-launch-1g.log').open('w') as log:
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + 45
        while True:
            if process.poll() is not None:
                raise RuntimeError('Neo4j exited: ' + (Path(__file__).resolve().parents[2] / '.tmp/batch3-real-neo4j/test-launch-1g.log').read_text()[-1000:])
            try:
                with GraphDatabase.driver(env['LCT_TEST_NEO4J_URI'],
                     auth=('neo4j', env['LCT_TEST_NEO4J_PASSWORD']), connection_timeout=1) as driver:
                    driver.verify_connectivity()
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.5)
        print('Owned Neo4j 5.26.0 ready; running targeted command', flush=True)
        result = subprocess.run(sys.argv[2:], cwd=sys.argv[1], env=env, timeout=540)
    finally:
        process.send_signal(signal.SIGTERM)
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    raise SystemExit(result.returncode)

