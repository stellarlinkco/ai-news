from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from pipeline_lib import build_http_client


def write_json(path: str, payload: dict[str, Any]) -> None:
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    path_obj.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_text(path: str, content: str) -> None:
    path_obj = Path(path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    path_obj.write_text(content, encoding="utf-8")


def update_history(history_path: str, run_summary: dict[str, Any]) -> list[dict[str, Any]]:
    path_obj = Path(history_path)
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    if not path_obj.exists():
        history: list[dict[str, Any]] = []
    else:
        with open(path_obj, "r", encoding="utf-8") as file:
            raw = json.load(file)
        history = raw.get("history", []) if isinstance(raw, dict) else raw
    history = [item for item in history if item.get("date") != run_summary["date"]]
    history.append(run_summary)
    history.sort(key=lambda item: item["date"], reverse=True)
    write_json(history_path, {"history": history[:180]})
    return history[:180]


def render_web_index(web_dir: str) -> None:
    path = Path(web_dir)
    path.mkdir(parents=True, exist_ok=True)
    index_path = path / "index.html"
    if index_path.exists():
        return
    html = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>AI Daily Intel</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; margin: 24px; color: #1f2937; background: #f8fafc; }
    h1 { margin: 0 0 8px; }
    .meta { color: #475569; margin-bottom: 20px; }
    .card { background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 14px; margin: 10px 0; }
    .source { color: #334155; font-size: 13px; margin-bottom: 6px; }
    .title a { text-decoration: none; color: #0f172a; font-weight: 600; }
    .summary { color: #334155; margin-top: 8px; line-height: 1.5; }
    .tags { margin-top: 8px; color: #0f766e; font-size: 12px; }
  </style>
</head>
<body>
  <h1>AI Daily Intel</h1>
  <div class="meta" id="meta">加载中...</div>
  <div id="list"></div>
  <script>
    async function run() {
      const latest = await fetch('./data/latest.json').then(r => r.json());
      const meta = document.getElementById('meta');
      const list = document.getElementById('list');
      meta.textContent = `日期: ${latest.date} · 新增: ${latest.new_items_count} · 来源: ${latest.sources_checked}`;
      latest.items.forEach(item => {
        const card = document.createElement('div');
        card.className = 'card';
        card.innerHTML = `
          <div class="source">${item.source_name} · 相关性 ${item.relevance}</div>
          <div class="title"><a href="${item.url}" target="_blank" rel="noreferrer">${item.title}</a></div>
          <div class="summary">${item.ai_summary || ''}</div>
          <div class="tags">${(item.tags || []).join(' / ')}</div>
        `;
        list.appendChild(card);
      });
    }
    run().catch(error => {
      document.getElementById('meta').textContent = '加载失败: ' + error;
    });
  </script>
</body>
</html>
"""
    index_path.write_text(html, encoding="utf-8")


def render_markdown_digest(run_payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# AI Daily Intel · {run_payload['date']}")
    lines.append("")
    lines.append(
        f"- 生成时间: `{run_payload['generated_at']}`  "
        f"- 新增条目: `{run_payload['new_items_count']}`  "
        f"- 检查来源: `{run_payload['sources_checked']}`"
    )
    lines.append("")
    if not run_payload["items"]:
        lines.append("> 今日无新增条目。")
        lines.append("")
        return "\n".join(lines)
    for index, item in enumerate(run_payload["items"][:30], start=1):
        title = item["title"].replace("\n", " ").strip()
        summary = (item.get("ai_summary") or "").replace("\n", " ").strip()
        tags = ", ".join(item.get("tags", []))
        lines.append(
            f"{index}. [{title}]({item['url']}) "
            f"（{item['source_name']} / 相关性 {item['relevance']}）"
        )
        if summary:
            lines.append(f"   - 摘要: {summary}")
        if tags:
            lines.append(f"   - 标签: {tags}")
    lines.append("")
    return "\n".join(lines)


def render_latest_summary(run_payload: dict[str, Any]) -> str:
    items = list(run_payload.get("items", []))
    lines: list[str] = [
        f"# AI Daily Summary · {run_payload.get('date', '')}",
        "",
        "## 今日概览",
        (
            f"- 来源检查: `{run_payload.get('sources_checked', 0)}`  "
            f"- 成功来源: `{run_payload.get('sources_successful', 0)}`  "
            f"- 新增条目: `{run_payload.get('new_items_count', 0)}`"
        ),
        "",
    ]
    if not items:
        lines.extend(["今日没有新增新闻，建议重点检查来源可用性与 RSS 健康状态。", ""])
        return "\n".join(lines)
    tag_counts: dict[str, int] = {}
    for item in items:
        for tag in item.get("tags", []):
            normalized = str(tag).strip()
            if not normalized:
                continue
            tag_counts[normalized] = tag_counts.get(normalized, 0) + 1
    top_tags = sorted(tag_counts.items(), key=lambda kv: kv[1], reverse=True)[:3]
    lines.append("## 主题观察")
    if top_tags:
        for tag, count in top_tags:
            lines.append(f"- `{tag}` 出现 `{count}` 次，属于今日重点主题。")
    else:
        lines.append("- 今日条目标签稀疏，建议优先关注高相关性条目。")
    lines.append("")
    lines.append("## 推荐阅读 Top 5")
    top_reads = sorted(
        items,
        key=lambda item: (
            int(item.get("relevance", 0)),
            str(item.get("published_at", "")),
        ),
        reverse=True,
    )[:5]
    for index, item in enumerate(top_reads, start=1):
        priority = item.get("reading_priority", "medium")
        lines.append(
            f"{index}. [{item.get('title', '(无标题)')}]({item.get('url', '')}) "
            f"（{item.get('source_name', 'unknown')} / 相关性 {item.get('relevance', 0)} / 优先级 {priority}）"
        )
    lines.append("")
    return "\n".join(lines)


def generate_ai_summary(run_payload: dict[str, Any]) -> str | None:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    model = os.getenv("AI_MODEL", "gpt-4.1-mini").strip()
    items = list(run_payload.get("items", []))[:30]
    system_prompt = (
        "你是 AI 资讯编辑。请输出中文 Markdown，长度 300-500 字，结构包含："
        "今日概览、3 个关键主题、推荐阅读 Top 5。内容必须基于输入，不要虚构。"
    )
    user_prompt = json.dumps(
        {
            "date": run_payload.get("date"),
            "sources_checked": run_payload.get("sources_checked"),
            "sources_successful": run_payload.get("sources_successful"),
            "new_items_count": run_payload.get("new_items_count"),
            "items": items,
        },
        ensure_ascii=False,
    )
    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
    }
    try:
        with build_http_client() as client:
            response = client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
        response.raise_for_status()
        body = response.json()
        text = (body.get("output_text") or "").strip()
        return text or None
    except Exception:
        return None


def send_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    webhook_url = os.getenv("WEBHOOK_URL", "").strip()
    webhook_secret = os.getenv("WEBHOOK_SECRET", "").strip()
    if not webhook_url:
        return {"status": "skipped", "reason": "WEBHOOK_URL empty"}
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    headers = {"Content-Type": "application/json"}
    timestamp = str(int(time.time()))
    headers["X-AI-News-Timestamp"] = timestamp
    if webhook_secret:
        signed_payload = f"{timestamp}.{body}".encode("utf-8")
        signature = hmac.new(webhook_secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        headers["X-AI-News-Signature"] = f"sha256={signature}"
    with build_http_client() as client:
        for attempt in range(3):
            try:
                response = client.post(webhook_url, content=body.encode("utf-8"), headers=headers)
            except Exception as error:
                if attempt == 2:
                    return {"status": "failed", "reason": str(error)}
                time.sleep(2**attempt)
                continue
            if response.status_code < 300:
                return {"status": "sent", "code": response.status_code}
            if response.status_code < 500 and response.status_code != 429:
                return {"status": "failed", "code": response.status_code, "body": response.text[:200]}
            if attempt == 2:
                return {"status": "failed", "code": response.status_code, "body": response.text[:200]}
            time.sleep(2**attempt)
    return {"status": "failed", "reason": "unknown"}


def publish_run_payload(
    run_payload: dict[str, Any],
    daily_dir: str,
    latest_json: str,
    latest_md: str,
    web_dir: str,
) -> dict[str, Any]:
    date_key = run_payload["date"]
    daily_path = str(Path(daily_dir) / f"{run_payload['date']}.json")
    write_json(daily_path, run_payload)
    write_json(latest_json, run_payload)
    digest_content = render_markdown_digest(run_payload)
    write_text(latest_md, digest_content)
    summary_content = generate_ai_summary(run_payload) or render_latest_summary(run_payload)
    write_text(str(Path(latest_md).with_name("latest-summary.md")), summary_content)

    web_data_dir = Path(web_dir) / "data"
    write_json(str(web_data_dir / f"{date_key}.json"), run_payload)
    write_json(str(web_data_dir / "latest.json"), run_payload)
    write_text(str(web_data_dir / "latest.md"), digest_content)
    write_text(str(web_data_dir / "latest-summary.md"), summary_content)

    history = update_history(
        str(web_data_dir / "history.json"),
        {
            "date": run_payload["date"],
            "generated_at": run_payload["generated_at"],
            "new_items_count": run_payload["new_items_count"],
            "sources_checked": run_payload["sources_checked"],
            "sources_successful": run_payload.get("sources_successful", 0),
            "top_titles": [item["title"] for item in run_payload["items"][:5]],
        },
    )
    render_web_index(web_dir)
    return {
        "daily_path": daily_path,
        "history_size": len(history),
        "summary_path": str(Path(latest_md).with_name("latest-summary.md")),
        "history": history,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate daily summary artifacts from run payload.")
    parser.add_argument("--input", default="data/latest.json")
    parser.add_argument("--daily-dir", default="data/daily")
    parser.add_argument("--latest-json", default="data/latest.json")
    parser.add_argument("--latest-md", default="data/latest.md")
    parser.add_argument("--web-dir", default="web")
    parser.add_argument("--send-webhook", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with open(args.input, "r", encoding="utf-8") as file:
        run_payload = json.load(file)
    publish_result = publish_run_payload(
        run_payload=run_payload,
        daily_dir=args.daily_dir,
        latest_json=args.latest_json,
        latest_md=args.latest_md,
        web_dir=args.web_dir,
    )
    webhook_status = "skipped"
    if args.send_webhook:
        webhook_result = send_webhook(
            {
                "event": "daily_ai_news",
                "payload": run_payload,
                "history_size": publish_result["history_size"],
            }
        )
        webhook_status = webhook_result.get("status", "unknown")
    print(
        "Summary complete: "
        f"date={run_payload['date']}, "
        f"items={run_payload['new_items_count']}, "
        f"webhook={webhook_status}"
    )


if __name__ == "__main__":
    main()
