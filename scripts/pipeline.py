#!/usr/bin/env python3
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from datetime import datetime, timezone
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from pipeline_lib import build_http_client, load_sources, now_iso, save_sources, stable_item_uid
from skills.analyze_ai_news import analyze_item
from skills.crawl_ai_news import apply_source_rss_update, collect_source_items
from skills.generate_daily_summary import publish_run_payload, send_webhook

SUCCESS_SOURCE_STATUSES = {"ok", "empty"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run modular AI news collection pipeline.")
    parser.add_argument("--sources", default="config/sources.yaml")
    parser.add_argument("--db", default="data/ai-news.db")
    parser.add_argument("--daily-dir", default="data/daily")
    parser.add_argument("--latest-json", default="data/latest.json")
    parser.add_argument("--latest-md", default="data/latest.md")
    parser.add_argument("--web-dir", default="web")
    parser.add_argument("--max-per-source", type=int, default=20)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--update-sources", action="store_true")
    parser.add_argument("--use-codex", action="store_true")
    return parser.parse_args()


def ensure_db(path: str) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_uid TEXT UNIQUE NOT NULL,
            source_id TEXT NOT NULL,
            source_name TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            published_at TEXT,
            collected_at TEXT NOT NULL,
            source_via TEXT NOT NULL,
            relevance INTEGER NOT NULL,
            tags_json TEXT NOT NULL,
            ai_summary TEXT NOT NULL,
            key_findings_json TEXT,
            reading_priority TEXT,
            has_code_example INTEGER,
            has_api_update INTEGER,
            technical_depth INTEGER,
            estimated_reading_time INTEGER,
            raw_json TEXT NOT NULL
        )
        """
    )
    return conn


def upsert_item(conn: sqlite3.Connection, row: dict[str, Any]) -> tuple[bool, bool]:
    tags_json = json.dumps(row["tags"], ensure_ascii=False)
    key_findings_json = json.dumps(row["key_findings"], ensure_ascii=False)
    raw_json = json.dumps(row["raw"], ensure_ascii=False)
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO items (
            item_uid, source_id, source_name, title, url, published_at, collected_at,
            source_via, relevance, tags_json, ai_summary, key_findings_json, reading_priority,
            has_code_example, has_api_update, technical_depth, estimated_reading_time, raw_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            row["item_uid"],
            row["source_id"],
            row["source_name"],
            row["title"],
            row["url"],
            row["published_at"],
            row["collected_at"],
            row["source_via"],
            row["relevance"],
            tags_json,
            row["ai_summary"],
            key_findings_json,
            row["reading_priority"],
            int(bool(row["has_code_example"])),
            int(bool(row["has_api_update"])),
            row["technical_depth"],
            row["estimated_reading_time"],
            raw_json,
        ),
    )
    inserted = cursor.rowcount > 0
    if inserted:
        return True, False

    published = str(row.get("published_at", "") or "")
    update_cursor = conn.execute(
        """
        UPDATE items
        SET
            published_at = CASE
                WHEN ? <> '' AND (published_at IS NULL OR published_at = '' OR published_at < ?) THEN ?
                ELSE published_at
            END,
            collected_at = ?,
            source_via = ?,
            relevance = ?,
            tags_json = ?,
            ai_summary = ?,
            key_findings_json = ?,
            reading_priority = ?,
            has_code_example = ?,
            has_api_update = ?,
            technical_depth = ?,
            estimated_reading_time = ?,
            raw_json = ?
        WHERE item_uid = ?
        """,
        (
            published,
            published,
            published,
            row["collected_at"],
            row["source_via"],
            row["relevance"],
            tags_json,
            row["ai_summary"],
            key_findings_json,
            row["reading_priority"],
            int(bool(row["has_code_example"])),
            int(bool(row["has_api_update"])),
            row["technical_depth"],
            row["estimated_reading_time"],
            raw_json,
            row["item_uid"],
        ),
    )
    return False, update_cursor.rowcount > 0


def build_run_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": row["source_id"],
        "source_name": row["source_name"],
        "title": row["title"],
        "url": row["url"],
        "published_at": row["published_at"],
        "relevance": row["relevance"],
        "tags": row["tags"],
        "ai_summary": row["ai_summary"],
        "key_findings": row["key_findings"],
        "reading_priority": row["reading_priority"],
        "has_code_example": row["has_code_example"],
        "has_api_update": row["has_api_update"],
        "technical_depth": row["technical_depth"],
        "estimated_reading_time": row["estimated_reading_time"],
        "source_via": row["source_via"],
    }


def error_source_report(source: dict[str, Any], reason: str) -> dict[str, Any]:
    source_health = source.get("health", {})
    return {
        "source_id": source["id"],
        "source_name": source["name"],
        "homepage": source["homepage"],
        "mode": "error",
        "feed_url": None,
        "feed_status": "error",
        "check_method": "exception",
        "status": "error",
        "item_count": 0,
        "checked_at": now_iso(),
        "error": reason,
        "retry_attempted": False,
        "retry_succeeded": False,
        "retry_count": 0,
        "skip_reason": "",
        "health_level": str(source_health.get("level", "healthy") or "healthy"),
        "cooldown_until": source_health.get("cooldown_until"),
    }


def parse_iso8601(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def source_health_level(source: dict[str, Any]) -> str:
    level = str(source.get("health", {}).get("level", "")).strip().lower()
    return level if level in {"healthy", "degraded", "unhealthy"} else "healthy"


def source_retry_limit(source: dict[str, Any]) -> int:
    raw = source.get("crawl", {}).get("retry_on_failure", 1)
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        parsed = 1
    return max(0, min(3, parsed))


def source_retry_delay(source: dict[str, Any], retry_attempt: int) -> float:
    raw = source.get("crawl", {}).get("retry_delay_seconds", 2.0)
    try:
        base_delay = float(raw)
    except (TypeError, ValueError):
        base_delay = 2.0
    capped = max(0.0, min(30.0, base_delay))
    return capped * (2 ** max(0, retry_attempt - 1))


def should_skip_by_cooldown(source: dict[str, Any], now_at: datetime) -> tuple[bool, str | None]:
    cooldown_until = parse_iso8601(source.get("health", {}).get("cooldown_until"))
    if not cooldown_until:
        return False, None
    return cooldown_until > now_at, cooldown_until.isoformat()


def skipped_source_report(source: dict[str, Any], cooldown_until: str | None) -> dict[str, Any]:
    rss = source.get("rss", {})
    return {
        "source_id": source["id"],
        "source_name": source["name"],
        "homepage": source["homepage"],
        "mode": "skipped",
        "feed_url": rss.get("url"),
        "feed_status": rss.get("status", "unknown"),
        "check_method": "cooldown",
        "status": "skipped_cooldown",
        "item_count": 0,
        "checked_at": now_iso(),
        "error": "",
        "retry_attempted": False,
        "retry_succeeded": False,
        "retry_count": 0,
        "skip_reason": f"cooldown_until:{cooldown_until}" if cooldown_until else "cooldown_active",
        "health_level": source_health_level(source),
        "cooldown_until": cooldown_until,
    }


def normalize_source_report(source: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(report)
    normalized["retry_attempted"] = bool(normalized.get("retry_attempted", False))
    normalized["retry_succeeded"] = bool(normalized.get("retry_succeeded", False))
    try:
        normalized["retry_count"] = max(0, int(normalized.get("retry_count", 0)))
    except (TypeError, ValueError):
        normalized["retry_count"] = 0
    normalized["skip_reason"] = str(normalized.get("skip_reason", "") or "")
    normalized["health_level"] = str(normalized.get("health_level") or source_health_level(source))
    normalized["cooldown_until"] = normalized.get("cooldown_until") or source.get("health", {}).get(
        "cooldown_until"
    )
    return normalized


def merge_retry_failure(
    previous_report: dict[str, Any],
    retry_report: dict[str, Any],
    retry_count: int,
) -> dict[str, Any]:
    merged = dict(previous_report)
    retry_error = str(retry_report.get("error", "") or "")
    if retry_error:
        prefix = f"retry_{retry_count}:{retry_error}"
        base_error = str(merged.get("error", "") or "")
        merged["error"] = f"{base_error}; {prefix}".strip("; ")
    merged["retry_attempted"] = True
    merged["retry_succeeded"] = False
    merged["retry_count"] = retry_count
    merged["checked_at"] = retry_report.get("checked_at", merged.get("checked_at", now_iso()))
    merged["health_level"] = retry_report.get("health_level", merged.get("health_level", "healthy"))
    merged["cooldown_until"] = retry_report.get("cooldown_until", merged.get("cooldown_until"))
    return merged


def collect_sources_parallel(
    sources: list[dict[str, Any]],
    default_max_per_source: int,
    workers: int,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    items_index: dict[str, list[dict[str, Any]]] = {}
    report_index: dict[str, dict[str, Any]] = {}
    max_workers = max(1, min(16, int(workers)))
    now_at = datetime.now(timezone.utc)
    runnable_sources: list[dict[str, Any]] = []
    retry_limits: dict[str, int] = {}

    for source in sources:
        source_id = source["id"]
        skip, cooldown_until = should_skip_by_cooldown(source, now_at)
        if skip:
            items_index[source_id] = []
            report_index[source_id] = skipped_source_report(source, cooldown_until)
            continue
        runnable_sources.append(source)
        retry_limits[source_id] = source_retry_limit(source)

    def worker(
        source: dict[str, Any],
        retry_attempt: int = 0,
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        max_items = int(source.get("crawl", {}).get("max_items", default_max_per_source))
        if retry_attempt > 0:
            delay = source_retry_delay(source, retry_attempt)
            if delay > 0:
                time.sleep(delay)
        try:
            with build_http_client() as client:
                items, source_report = collect_source_items(client, source, max_items)
            return source["id"], items, normalize_source_report(source, source_report)
        except Exception as error:
            report = error_source_report(source, f"collect_failed: {error}")
            return source["id"], [], normalize_source_report(source, report)

    def run_batch(batch_sources: list[dict[str, Any]], retry_attempt: int) -> dict[str, tuple[list[dict[str, Any]], dict[str, Any]]]:
        if not batch_sources:
            return {}
        results: dict[str, tuple[list[dict[str, Any]], dict[str, Any]]] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(worker, source, retry_attempt) for source in batch_sources]
            for future in as_completed(futures):
                source_id, items, source_report = future.result()
                results[source_id] = (items, source_report)
        return results

    first_pass = run_batch(runnable_sources, retry_attempt=0)
    for source_id, (items, source_report) in first_pass.items():
        items_index[source_id] = items
        report_index[source_id] = source_report

    retry_counts: dict[str, int] = {source["id"]: 0 for source in runnable_sources}
    retry_attempt = 1
    while True:
        retry_sources = [
            source
            for source in runnable_sources
            if report_index.get(source["id"], {}).get("status") == "error"
            and retry_counts[source["id"]] < retry_limits.get(source["id"], 0)
        ]
        if not retry_sources:
            break

        retry_results = run_batch(retry_sources, retry_attempt=retry_attempt)
        for source in retry_sources:
            source_id = source["id"]
            retry_counts[source_id] += 1
            retry_items, retry_report = retry_results.get(
                source_id,
                ([], error_source_report(source, "missing_retry_source_report")),
            )
            retry_report = normalize_source_report(source, retry_report)
            retry_report["retry_attempted"] = True
            retry_report["retry_count"] = retry_counts[source_id]
            if retry_report.get("status") != "error":
                retry_report["retry_succeeded"] = True
                report_index[source_id] = retry_report
                items_index[source_id] = retry_items
                continue
            previous_report = report_index.get(source_id, error_source_report(source, "missing_source_report"))
            report_index[source_id] = merge_retry_failure(previous_report, retry_report, retry_counts[source_id])
            items_index[source_id] = []
        retry_attempt += 1
    return items_index, report_index


def main() -> None:
    args = parse_args()
    config = load_sources(args.sources)
    sources = config.get("sources", [])
    conn = ensure_db(args.db)
    today = datetime.now(timezone.utc).date().isoformat()
    collected_at = now_iso()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("AI_MODEL", "gpt-4.1-mini").strip()

    run_items: list[dict[str, Any]] = []
    new_items: list[dict[str, Any]] = []
    updated_items_count = 0
    source_results: list[dict[str, Any]] = []
    items_index, report_index = collect_sources_parallel(sources, args.max_per_source, args.workers)
    with build_http_client() as client:
        for source in sources:
            source_id = source["id"]
            source_report = report_index.get(source_id, error_source_report(source, "missing_source_report"))
            source_results.append(source_report)
            if args.update_sources:
                apply_source_rss_update(source, source_report)
                source_report["health_level"] = source.get("health", {}).get(
                    "level",
                    source_report.get("health_level", "healthy"),
                )
                source_report["cooldown_until"] = source.get("health", {}).get(
                    "cooldown_until",
                    source_report.get("cooldown_until"),
                )
            for item in items_index.get(source_id, []):
                analysis = analyze_item(
                    client=client,
                    item=item,
                    source_name=source["name"],
                    api_key=api_key,
                    model=model,
                    use_codex=args.use_codex,
                )
                row = {
                    "item_uid": stable_item_uid(source["id"], item["url"], item["title"]),
                    "source_id": source["id"],
                    "source_name": source["name"],
                    "title": item["title"],
                    "url": item["url"],
                    "published_at": item.get("published_at", ""),
                    "collected_at": collected_at,
                    "source_via": item.get("source_via", "unknown"),
                    "relevance": int(analysis["relevance"]),
                    "tags": analysis["tags"],
                    "ai_summary": analysis["ai_summary"],
                    "key_findings": analysis.get("key_findings", []),
                    "reading_priority": analysis.get("reading_priority", "medium"),
                    "has_code_example": analysis.get("has_code_example", False),
                    "has_api_update": analysis.get("has_api_update", False),
                    "technical_depth": int(analysis.get("technical_depth", 3)),
                    "estimated_reading_time": int(analysis.get("estimated_reading_time", 1)),
                    "raw": {
                        "item": item,
                        "analysis": analysis,
                    },
                }
                run_item = build_run_item(row)
                run_items.append(run_item)
                inserted, updated = upsert_item(conn, row)
                if inserted:
                    new_items.append(run_item)
                elif updated:
                    updated_items_count += 1
    conn.commit()
    conn.close()

    run_items.sort(key=lambda item: (item["relevance"], item["published_at"]), reverse=True)
    new_items.sort(key=lambda item: (item["relevance"], item["published_at"]), reverse=True)
    run_payload = {
        "date": today,
        "generated_at": collected_at,
        "sources_checked": len(sources),
        "sources_successful": sum(result["status"] in SUCCESS_SOURCE_STATUSES for result in source_results),
        "sources_with_items": sum(result["item_count"] > 0 for result in source_results),
        "sources_skipped_cooldown": sum(result["status"] == "skipped_cooldown" for result in source_results),
        "retry_attempted_sources": sum(bool(result.get("retry_attempted")) for result in source_results),
        "retry_recovered_sources": sum(bool(result.get("retry_succeeded")) for result in source_results),
        "items_fetched_count": len(run_items),
        "new_items_count": len(new_items),
        "updated_items_count": updated_items_count,
        "items": run_items,
        "sources": source_results,
    }
    if len(sources) >= 10 and run_payload["sources_successful"] < 10:
        raise RuntimeError(
            f"critical threshold not met: successful_sources={run_payload['sources_successful']} < 10"
        )

    publish_result = publish_run_payload(
        run_payload=run_payload,
        daily_dir=args.daily_dir,
        latest_json=args.latest_json,
        latest_md=args.latest_md,
        web_dir=args.web_dir,
    )

    if args.update_sources:
        save_sources(args.sources, config)

    webhook_result = send_webhook(
        {
            "event": "daily_ai_news",
            "payload": run_payload,
            "history_size": publish_result["history_size"],
        }
    )
    print(
        "Pipeline complete: "
        f"sources={len(sources)}, "
        f"new_items={len(new_items)}, "
        f"webhook={webhook_result['status']}"
    )


if __name__ == "__main__":
    main()
