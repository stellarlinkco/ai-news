#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from typing import Any

from pipeline_lib import build_http_client, discover_source_feed, load_sources, save_sources


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit RSS availability for configured sources.")
    parser.add_argument(
        "--sources",
        default="config/sources.yaml",
        help="Path to source config yaml.",
    )
    parser.add_argument(
        "--out",
        default="data/rss-audit-latest.json",
        help="Path to audit report JSON.",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Persist discovered feed URL/status back to source config.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Parallel worker count for source probing.",
    )
    return parser.parse_args()


def update_source_rss(source: dict[str, Any], result: dict[str, Any]) -> None:
    source.setdefault("rss", {})
    source["rss"]["checked_at"] = result["checked_at"]
    source["rss"]["check_method"] = result["method"]
    if result["feed_url"]:
        source["rss"]["url"] = result["feed_url"]
        source["rss"]["status"] = "confirmed"
    elif source["rss"].get("candidates"):
        source["rss"]["url"] = None
        source["rss"]["status"] = "candidate"
    else:
        source["rss"]["url"] = None
        source["rss"]["status"] = "unknown"


def audit_one_source(source: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    with build_http_client() as client:
        result = discover_source_feed(client, source)
    entry = {
        "id": source["id"],
        "name": source["name"],
        "homepage": source["homepage"],
        "feed_url": result["feed_url"],
        "status": result["status"],
        "checked_at": result["checked_at"],
        "check_method": result["method"],
        "homepage_error": result["homepage_error"],
        "probe_logs": result["probe_logs"],
    }
    return source["id"], entry, result


def main() -> None:
    args = parse_args()
    config = load_sources(args.sources)
    sources = config.get("sources", [])
    report: list[dict[str, Any]] = []
    entry_index: dict[str, dict[str, Any]] = {}
    result_index: dict[str, dict[str, Any]] = {}
    workers = max(1, min(16, int(args.workers)))

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(audit_one_source, source) for source in sources]
        for future in as_completed(futures):
            source_id, entry, result = future.result()
            entry_index[source_id] = entry
            result_index[source_id] = result

    for source in sources:
        source_id = source["id"]
        if source_id not in entry_index:
            continue
        report.append(entry_index[source_id])
        if args.update:
            update_source_rss(source, result_index[source_id])

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as file:
        json.dump(
            {
                "sources_total": len(report),
                "confirmed_total": sum(item["status"] == "confirmed" for item in report),
                "checked_at": report[0]["checked_at"] if report else "",
                "results": report,
            },
            file,
            ensure_ascii=False,
            indent=2,
        )

    if args.update:
        save_sources(args.sources, config)
    print(
        f"RSS audit complete: confirmed {sum(item['status'] == 'confirmed' for item in report)}/{len(report)}"
    )


if __name__ == "__main__":
    main()
