from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from pipeline_lib import (
    API_INDICATORS,
    CODE_INDICATORS,
    analyze_item_with_openai,
    analyze_with_codex,
    build_http_client,
    compact_text,
    estimate_relevance,
    estimate_reading_time,
    now_iso,
)


def top_tags_from_text(title: str, summary: str) -> list[str]:
    candidate = f"{title} {summary}".lower()
    mapping = {
        "agent": "agent",
        "llm": "llm",
        "model": "model",
        "reasoning": "reasoning",
        "inference": "inference",
        "evaluation": "evaluation",
        "benchmark": "benchmark",
        "api": "api",
        "multimodal": "multimodal",
        "rag": "rag",
        "safety": "safety",
        "open-source": "open-source",
    }
    tags = [value for key, value in mapping.items() if key in candidate]
    return tags[:6]


def fallback_analysis(item: dict[str, Any]) -> dict[str, Any]:
    title = item["title"]
    summary = item.get("summary", "")
    merged_text = f"{title} {summary}".lower()
    score = estimate_relevance(item["title"], item.get("summary", ""))
    tags = top_tags_from_text(title, summary)
    compact_summary = compact_text(summary)[:140]
    if not compact_summary:
        compact_summary = compact_text(title)[:140]
    findings = [compact_summary] if compact_summary else [compact_text(title)]
    has_code = any(indicator in merged_text for indicator in CODE_INDICATORS)
    has_api = any(indicator in merged_text for indicator in API_INDICATORS)
    priority = "high" if score >= 80 else "medium" if score >= 50 else "low"
    technical_depth = max(1, min(5, score // 20 + 1))
    return {
        "relevance": score,
        "tags": tags,
        "ai_summary": compact_summary,
        "key_findings": findings[:3],
        "has_code_example": has_code,
        "has_api_update": has_api,
        "reading_priority": priority,
        "technical_depth": technical_depth,
        "estimated_reading_time": estimate_reading_time(f"{title}\n{summary}"),
        "model_used": "rule-based",
    }


def normalize_analysis(item: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    fallback = fallback_analysis(item)
    result = dict(fallback)
    result.update(analysis or {})
    result["relevance"] = int(max(0, min(100, int(result.get("relevance", fallback["relevance"])))))
    result["tags"] = [str(tag).strip() for tag in result.get("tags", []) if str(tag).strip()][:6]
    result["ai_summary"] = compact_text(str(result.get("ai_summary", fallback["ai_summary"])))
    result["key_findings"] = [
        compact_text(str(item_text))
        for item_text in result.get("key_findings", fallback["key_findings"])
        if compact_text(str(item_text))
    ][:5]
    result["has_code_example"] = bool(result.get("has_code_example", fallback["has_code_example"]))
    result["has_api_update"] = bool(result.get("has_api_update", fallback["has_api_update"]))
    priority = str(result.get("reading_priority", fallback["reading_priority"])).lower()
    result["reading_priority"] = priority if priority in {"high", "medium", "low"} else fallback["reading_priority"]
    result["technical_depth"] = max(1, min(5, int(result.get("technical_depth", fallback["technical_depth"]))))
    result["estimated_reading_time"] = max(
        1, int(result.get("estimated_reading_time", fallback["estimated_reading_time"]))
    )
    result["model_used"] = str(result.get("model_used", fallback["model_used"]))
    return result


def analyze_item(
    client,
    item: dict[str, Any],
    source_name: str,
    api_key: str,
    model: str,
    use_codex: bool = False,
) -> dict[str, Any]:
    if not api_key:
        return fallback_analysis(item)
    try:
        if use_codex:
            analysis = analyze_with_codex(
                client=client,
                api_key=api_key,
                model=model,
                title=item["title"],
                summary=item.get("summary", ""),
                source_name=source_name,
                full_content=item.get("full_content", ""),
            )
        else:
            analysis = analyze_item_with_openai(
                client=client,
                api_key=api_key,
                model=model,
                title=item["title"],
                summary=item.get("summary", ""),
                source_name=source_name,
            )
        return normalize_analysis(item, analysis)
    except Exception:
        return fallback_analysis(item)


def analyze_items(
    client,
    items: list[dict[str, Any]],
    api_key: str,
    model: str,
    use_codex: bool = False,
) -> list[dict[str, Any]]:
    analyzed: list[dict[str, Any]] = []
    for item in items:
        source_name = str(item.get("source_name") or item.get("source") or "unknown")
        analysis = analyze_item(client, item, source_name, api_key, model, use_codex)
        merged = dict(item)
        merged["relevance"] = int(analysis.get("relevance", 0))
        merged["tags"] = analysis.get("tags", [])
        merged["ai_summary"] = analysis.get("ai_summary", "")
        merged["key_findings"] = analysis.get("key_findings", [])
        merged["has_code_example"] = analysis.get("has_code_example", False)
        merged["has_api_update"] = analysis.get("has_api_update", False)
        merged["reading_priority"] = analysis.get("reading_priority", "medium")
        merged["technical_depth"] = analysis.get("technical_depth", 3)
        merged["estimated_reading_time"] = analysis.get("estimated_reading_time", 1)
        merged["analysis_model"] = analysis.get("model_used", "")
        analyzed.append(merged)
    return analyzed


def write_json(path: str, payload: dict[str, Any]) -> None:
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    path_obj.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_items(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as file:
        raw = json.load(file)
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        return raw["items"]
    raise ValueError("input json must be list or object with items[]")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze crawled AI news items.")
    parser.add_argument("--input", default="data/crawl-latest.json")
    parser.add_argument("--output", default="data/analyze-latest.json")
    parser.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY", "").strip())
    parser.add_argument("--model", default=os.getenv("AI_MODEL", "gpt-4.1-mini").strip())
    parser.add_argument("--use-codex", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    items = load_items(args.input)
    with build_http_client() as client:
        analyzed = analyze_items(client, items, args.api_key, args.model, args.use_codex)
    payload = {
        "generated_at": now_iso(),
        "items_count": len(analyzed),
        "items": analyzed,
    }
    write_json(args.output, payload)
    print(
        "Analyze complete: "
        f"items={len(analyzed)}, "
        f"output={args.output}"
    )


if __name__ == "__main__":
    main()
