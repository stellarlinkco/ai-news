from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from pipeline_lib import (
    build_http_client,
    discover_source_feed,
    load_sources,
    now_iso,
    parse_feed_entries,
    parse_html_entries,
    save_sources,
)


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


def parse_int(value: Any, default: int, minimum: int = 0, maximum: int = 10_000) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def resolve_health_policy(source: dict[str, Any]) -> dict[str, int]:
    crawl = source.get("crawl", {})
    health = crawl.get("health", {})
    thresholds = crawl.get("health_thresholds", {})
    cooldown = crawl.get("cooldown_minutes", {})
    if isinstance(health.get("thresholds"), dict):
        thresholds = health["thresholds"]
    if isinstance(health.get("cooldown_minutes"), dict):
        cooldown = health["cooldown_minutes"]
    degraded_after = parse_int(thresholds.get("degraded_after_failures"), 2, minimum=1, maximum=10)
    unhealthy_after = parse_int(
        thresholds.get("unhealthy_after_failures"),
        4,
        minimum=degraded_after,
        maximum=20,
    )
    degraded_cooldown = parse_int(cooldown.get("degraded"), 60, minimum=0, maximum=7 * 24 * 60)
    unhealthy_cooldown = parse_int(cooldown.get("unhealthy"), 360, minimum=0, maximum=14 * 24 * 60)
    return {
        "degraded_after": degraded_after,
        "unhealthy_after": unhealthy_after,
        "degraded_cooldown": degraded_cooldown,
        "unhealthy_cooldown": unhealthy_cooldown,
    }


def health_level_from_failures(consecutive_failures: int, policy: dict[str, int]) -> str:
    if consecutive_failures >= policy["unhealthy_after"]:
        return "unhealthy"
    if consecutive_failures >= policy["degraded_after"]:
        return "degraded"
    return "healthy"


def collect_source_items(
    client,
    source: dict[str, Any],
    max_per_source: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rss_config = source.get("rss", {})
    preset_feed = (rss_config.get("url") or "").strip()
    feed_result = {
        "feed_url": preset_feed or None,
        "status": "confirmed" if preset_feed else "not_found",
        "method": "configured",
        "checked_at": now_iso(),
    }
    status = "ok"
    error = ""
    items: list[dict[str, Any]] = []
    mode = "rss_config"

    if preset_feed:
        try:
            items = parse_feed_entries(client, source, preset_feed, max_per_source)
        except Exception as exc:
            error = f"rss_config_failed: {exc}"
            feed_result = discover_source_feed(client, source)
    if not items:
        if not feed_result.get("feed_url"):
            feed_result = discover_source_feed(client, source)
        if feed_result["feed_url"]:
            try:
                items = parse_feed_entries(client, source, feed_result["feed_url"], max_per_source)
                mode = "rss_discovered"
            except Exception as exc:
                error = f"{error}; rss_discovered_failed: {exc}".strip("; ")
                feed_result["status"] = "invalid"
                feed_result["feed_url"] = None
                mode = "html_fallback"
        else:
            mode = "html"

    if not items and mode in {"html", "html_fallback"}:
        mode = "html"
        try:
            items = parse_html_entries(client, source, max_per_source)
        except Exception as exc:
            status = "error"
            reason = f"html_failed: {exc}"
            error = f"{error}; {reason}".strip("; ")
    if status == "ok" and not items:
        status = "empty"
    return items, {
        "source_id": source["id"],
        "source_name": source["name"],
        "homepage": source["homepage"],
        "mode": mode,
        "feed_url": feed_result["feed_url"],
        "feed_status": feed_result.get("status", ""),
        "check_method": feed_result.get("method", ""),
        "status": status,
        "item_count": len(items),
        "checked_at": feed_result.get("checked_at", now_iso()),
        "error": error,
        "retry_attempted": False,
        "retry_succeeded": False,
        "retry_count": 0,
        "skip_reason": "",
        "health_level": str(source.get("health", {}).get("level", "healthy") or "healthy"),
        "cooldown_until": source.get("health", {}).get("cooldown_until"),
    }


def apply_source_rss_update(source: dict[str, Any], source_report: dict[str, Any]) -> None:
    source.setdefault("rss", {})
    status = str(source_report.get("status", "")).strip()
    report_feed = source_report.get("feed_url")
    if report_feed:
        source["rss"]["url"] = report_feed
        source["rss"]["status"] = "confirmed"
    elif status not in {"error", "skipped_cooldown"}:
        source["rss"]["url"] = None
        source["rss"]["status"] = "unknown"
    source["rss"]["checked_at"] = source_report.get("checked_at", now_iso())
    source["rss"]["check_method"] = source_report.get("check_method", "")

    policy = resolve_health_policy(source)
    health = source.setdefault("health", {})
    checked_at = str(source_report.get("checked_at", "") or now_iso())
    checked_dt = parse_iso8601(checked_at) or datetime.now(timezone.utc)
    consecutive_failures = parse_int(health.get("consecutive_failures"), 0)
    level = str(health.get("level", "healthy") or "healthy")
    cooldown_until = health.get("cooldown_until")
    if status in {"ok", "empty"}:
        consecutive_failures = 0
        level = "healthy"
        cooldown_until = None
        health["last_success_at"] = checked_at
        health["last_error"] = ""
    elif status == "error":
        consecutive_failures += 1
        level = health_level_from_failures(consecutive_failures, policy)
        if level == "unhealthy":
            cooldown_minutes = policy["unhealthy_cooldown"]
        elif level == "degraded":
            cooldown_minutes = policy["degraded_cooldown"]
        else:
            cooldown_minutes = 0
        cooldown_until = (
            (checked_dt + timedelta(minutes=cooldown_minutes)).isoformat()
            if cooldown_minutes > 0
            else None
        )
        health["last_error"] = str(source_report.get("error", "") or "")
    elif status == "skipped_cooldown":
        cooldown_until = source_report.get("cooldown_until") or cooldown_until
        level = str(source_report.get("health_level") or level or "degraded")
    health["level"] = level
    health["consecutive_failures"] = consecutive_failures
    health["cooldown_until"] = cooldown_until
    health["last_status"] = status or "unknown"
    health["last_checked_at"] = checked_at
    health["retry_attempted"] = bool(source_report.get("retry_attempted", False))
    health["retry_succeeded"] = bool(source_report.get("retry_succeeded", False))
    health["retry_count"] = parse_int(source_report.get("retry_count"), 0, minimum=0, maximum=3)


def crawl_sources(
    sources: list[dict[str, Any]],
    max_per_source: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    crawled_items: list[dict[str, Any]] = []
    source_results: list[dict[str, Any]] = []
    with build_http_client() as client:
        for source in sources:
            max_items = int(source.get("crawl", {}).get("max_items", max_per_source))
            items, source_report = collect_source_items(client, source, max_items)
            source_results.append(source_report)
            for item in items:
                crawled_items.append(
                    {
                        "source_id": source["id"],
                        "source_name": source["name"],
                        "title": item["title"],
                        "url": item["url"],
                        "summary": item.get("summary", ""),
                        "published_at": item.get("published_at", ""),
                        "source_via": item.get("source_via", "unknown"),
                    }
                )
    return crawled_items, source_results


def write_json(path: str, payload: dict[str, Any]) -> None:
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    path_obj.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl AI news from configured sources.")
    parser.add_argument("--sources", default="config/sources.yaml")
    parser.add_argument("--max-per-source", type=int, default=20)
    parser.add_argument("--source-id", action="append", default=[])
    parser.add_argument("--output", default="data/crawl-latest.json")
    parser.add_argument("--update-sources", action="store_true")
    return parser.parse_args()


def filter_sources(sources: list[dict[str, Any]], source_ids: list[str]) -> list[dict[str, Any]]:
    if not source_ids:
        return sources
    wanted = {source_id.strip() for source_id in source_ids if source_id.strip()}
    return [source for source in sources if source.get("id") in wanted]


def main() -> None:
    args = parse_args()
    config = load_sources(args.sources)
    sources = filter_sources(config.get("sources", []), args.source_id)
    items, source_results = crawl_sources(sources, args.max_per_source)

    if args.update_sources:
        report_index = {report["source_id"]: report for report in source_results}
        for source in sources:
            source_report = report_index.get(source["id"])
            if source_report:
                apply_source_rss_update(source, source_report)
        save_sources(args.sources, config)

    payload = {
        "generated_at": now_iso(),
        "sources_checked": len(sources),
        "new_items_count": len(items),
        "items": items,
        "sources": source_results,
    }
    write_json(args.output, payload)
    print(
        "Crawl complete: "
        f"sources={len(sources)}, "
        f"items={len(items)}, "
        f"output={args.output}"
    )


if __name__ == "__main__":
    main()
