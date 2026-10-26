"""Run an API-free synthetic example: python -m tests.synthetic_demo --output <new-dir>."""

import argparse
import json

from .synthetic_support import build_fixture, initialize, query_fixture


def main():
    """Keep generated fixture databases in the explicitly chosen new output directory."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    c, _ = initialize(args.output)
    m = build_fixture(c)
    results, docs = query_fixture(c)
    assert docs["results"] and all(r["results"] for r in results.values())
    print(
        json.dumps(
            dict(
                synthetic_test_vectors_only=True,
                real_retrieval_quality=False,
                index_version=m["version"],
                nodes=m["nodes"],
                api_requests=0,
                results={k: [n["qualname"] for n in v["results"]] for k, v in results.items()},
                doc_sections=len(docs["results"]),
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
