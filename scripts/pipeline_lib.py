from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import feedparser
import httpx
import yaml
from bs4 import BeautifulSoup

USER_AGENT = "ai-news-collector/1.0 (+https://github.com)"
FEED_CONTENT_MARKERS = ("<rss", "<feed", "<rdf:rdf")
COMMON_FEED_SUFFIXES = (
    "/feed",
    "/feed/",
    "/rss",
    "/rss/",
    "/rss.xml",
    "/feed.xml",
    "/atom.xml",
    "/all.atom",
    "/index.xml",
)
ARTICLE_PATH_HINTS = ("blog", "news", "engineering", "research", "agent", "ai")
IGNORE_LINK_HINTS = (
    "login",
    "signup",
    "sign-up",
    "sign-in",
    "privacy",
    "terms",
    "careers",
    "jobs",
    "contact",
)
GENERIC_LINK_TITLES = (
    "read more",
    "ask questions about this page",
    "try claude",
    "subscribe",
    "learn more",
    "blog posts",
    "featured",
    "next",
    "previous",
)
DATE_TEXT_PATTERN = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+"
    r"\d{1,2},\s+\d{4}\b",
    flags=re.IGNORECASE,
)
COHERE_EMBEDDED_POST_PATTERN = re.compile(
    r'\\"published_at\\":\\"(?P<published>[^\\"]+)\\".{0,900}?'
    r'\\"slug\\":\\"(?P<slug>[^\\"]+)\\".{0,1200}?'
    r'\\"title\\":\\"(?P<title>[^\\"]+)\\"',
    flags=re.DOTALL,
)
MANUS_EMBEDDED_POST_PATTERN = re.compile(
    r'\\"title\\":\\"(?P<title>[^\\"]+)\\".*?'
    r'\\"recordUid\\":\\"(?P<slug>[^\\"]+)\\".*?'
    r'\\"seconds\\":(?P<seconds>\d+)',
    flags=re.DOTALL,
)
TOPIC_KEYWORDS = (
    "ai",
    "agent",
    "llm",
    "model",
    "reasoning",
    "inference",
    "fine-tuning",
    "evaluation",
    "retrieval",
    "rag",
    "prompt",
    "multimodal",
    "automation",
)

CODE_INDICATORS = (
    "code",
    "github",
    "repository",
    "implementation",
    "function",
    "class",
    "def ",
    "import ",
    "```",
    "<code",
    "api endpoint",
    "sdk",
    "library",
    "package",
)

API_INDICATORS = (
    "api",
    "endpoint",
    "sdk",
    "integration",
    "webhook",
    "rest",
    "graphql",
    "request",
    "response",
    "authentication",
    "rate limit",
    "new feature",
    "launch",
    "release",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_sources(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def save_sources(path: str, payload: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as file:
        yaml.safe_dump(payload, file, sort_keys=False, allow_unicode=True)


def build_http_client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(10.0, connect=4.0),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
    )


def is_feed_content(content_type: str, body: str) -> bool:
    lowered_ct = (content_type or "").lower()
    lowered_body = (body or "").lower()
    ct_likely_xml = "xml" in lowered_ct or "rss" in lowered_ct or "atom" in lowered_ct
    body_likely_feed = any(marker in lowered_body for marker in FEED_CONTENT_MARKERS)
    return ct_likely_xml and body_likely_feed


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    normalized = parsed._replace(path=parsed.path or "/", fragment="", query="")
    return normalized.geturl()


def domain_of(url: str) -> str:
    return urlparse(url).netloc.lower()


def unique_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def extract_feed_links_from_homepage(homepage: str, html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[str] = []
    for link in soup.select("link[rel]"):
        rel = " ".join(link.get("rel", [])).lower()
        link_type = (link.get("type") or "").lower()
        href = link.get("href")
        if not href:
            continue
        if "alternate" not in rel:
            continue
        if "rss" in link_type or "atom" in link_type or "xml" in link_type:
            candidates.append(urljoin(homepage, href))
    return unique_keep_order(candidates)


def build_common_feed_candidates(homepage: str) -> list[str]:
    parsed = urlparse(homepage)
    base = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.rstrip("/")
    candidates = [f"{base}{path}{suffix}" for suffix in COMMON_FEED_SUFFIXES]
    if path:
        candidates.extend(f"{base}{suffix}" for suffix in COMMON_FEED_SUFFIXES)
    return unique_keep_order(candidates)


def probe_feed_url(client: httpx.Client, url: str) -> tuple[bool, str]:
    try:
        response = client.get(url)
    except Exception as error:
        return False, f"request_error: {error}"
    if response.status_code >= 400:
        return False, f"http_{response.status_code}"
    content_type = response.headers.get("content-type", "")
    if not is_feed_content(content_type, response.text):
        return False, f"not_feed_content_type:{content_type}"
    return True, "ok"


def discover_source_feed(client: httpx.Client, source: dict[str, Any]) -> dict[str, Any]:
    homepage = source["homepage"]
    rss_config = source.get("rss", {})
    seed_url = rss_config.get("url")
    configured_candidates = rss_config.get("candidates", [])
    candidates: list[str] = []
    if seed_url:
        candidates.append(seed_url)
    candidates.extend(configured_candidates)

    homepage_html = ""
    homepage_error = ""
    try:
        homepage_response = client.get(homepage)
        if homepage_response.status_code < 400:
            homepage_html = homepage_response.text
        else:
            homepage_error = f"http_{homepage_response.status_code}"
    except Exception as error:
        homepage_error = f"request_error: {error}"

    if homepage_html:
        candidates.extend(extract_feed_links_from_homepage(homepage, homepage_html))
    candidates.extend(build_common_feed_candidates(homepage))
    candidates = unique_keep_order([normalize_url(item) for item in candidates])
    probe_limit = int(source.get("crawl", {}).get("feed_probe_limit", 8))
    probe_limit = max(1, min(20, probe_limit))

    probe_logs: list[dict[str, str]] = []
    for candidate in candidates[:probe_limit]:
        ok, reason = probe_feed_url(client, candidate)
        probe_logs.append({"url": candidate, "result": reason})
        if ok:
            return {
                "feed_url": candidate,
                "status": "confirmed",
                "method": "http_probe",
                "checked_at": now_iso(),
                "homepage_error": homepage_error,
                "probe_logs": probe_logs,
            }
    return {
        "feed_url": None,
        "status": "not_found",
        "method": "http_probe",
        "checked_at": now_iso(),
        "homepage_error": homepage_error,
        "probe_logs": probe_logs,
    }


def parse_feed_entries(
    client: httpx.Client,
    source: dict[str, Any],
    feed_url: str,
    max_items: int,
) -> list[dict[str, Any]]:
    response = client.get(feed_url)
    parsed = feedparser.parse(response.text)
    items: list[dict[str, Any]] = []
    source_domain = domain_of(source["homepage"])
    for entry in parsed.entries[:max_items]:
        link = (entry.get("link") or "").strip()
        if not link:
            continue
        if domain_of(link) and source_domain not in domain_of(link):
            continue
        title = (entry.get("title") or "").strip()
        summary = (entry.get("summary") or entry.get("description") or "").strip()
        published = (
            entry.get("published")
            or entry.get("updated")
            or entry.get("created")
            or ""
        )
        items.append(
            {
                "title": title or link,
                "url": link,
                "summary": compact_text(summary),
                "published_at": published,
                "source_via": "rss",
            }
        )
    return items


def likely_article_link(source_homepage: str, url: str) -> bool:
    source_parsed = urlparse(source_homepage)
    base_domain = source_parsed.netloc.lower()
    source_root_path = source_parsed.path.rstrip("/").lower()
    source_root_normalized = source_root_path or "/"
    parsed = urlparse(url)
    if not parsed.scheme.startswith("http"):
        return False
    if parsed.netloc.lower() != base_domain:
        return False
    lowered = parsed.path.lower()
    lowered_normalized = lowered.rstrip("/") or "/"
    if lowered in {"", "/"}:
        return False
    if lowered_normalized == source_root_normalized:
        return False
    if any(flag in lowered for flag in IGNORE_LINK_HINTS):
        return False
    if "/category/" in lowered or "/tag/" in lowered:
        return False
    if source_root_path and any(hint in source_root_path for hint in ARTICLE_PATH_HINTS):
        if not lowered.startswith(f"{source_root_path}/") and lowered != source_root_path:
            return False
    if sum(hint in lowered for hint in ARTICLE_PATH_HINTS) == 0:
        return False
    if lowered.endswith((".png", ".jpg", ".jpeg", ".svg", ".gif", ".pdf", ".zip")):
        return False
    return True


def parse_human_date(raw: str) -> str:
    value = compact_text(raw).strip()
    if not value:
        return ""
    if value.lower().startswith("sept "):
        value = f"Sep {value[5:]}"
    formats = ("%b %d, %Y", "%B %d, %Y")
    for date_format in formats:
        try:
            parsed = datetime.strptime(value.title(), date_format).replace(tzinfo=timezone.utc)
            return parsed.isoformat()
        except ValueError:
            continue
    return ""


def parse_published_sort_key(value: str) -> datetime | None:
    text = compact_text(value).strip()
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


def decode_embedded_text(value: str) -> str:
    text = compact_text(value)
    if not text:
        return ""
    text = text.replace("\\/", "/")
    text = (
        text.replace("\\u0026", "&")
        .replace("\\u003c", "<")
        .replace("\\u003e", ">")
        .replace("\\u0027", "'")
        .replace("\\u2019", "’")
    )
    return compact_text(text)


def clean_anchor_title(raw: str) -> str:
    candidate = compact_text(raw).strip()
    if not candidate:
        return ""
    lowered = candidate.lower()
    if lowered.startswith("read "):
        candidate = candidate[5:].strip()
    if lowered.startswith("learn more "):
        candidate = candidate[11:].strip()
    return compact_text(candidate)


def slug_to_title(url: str) -> str:
    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    slug = slug.replace("-", " ").replace("_", " ").strip()
    return compact_text(slug.title())


def prefer_slug_title(title: str, url: str) -> str:
    normalized = clean_anchor_title(title)
    slug_title = slug_to_title(url)
    generic_titles = {"open source", "research", "product", "news"}
    if normalized.lower() in generic_titles and len(slug_title.split()) >= 3:
        return slug_title
    if len(normalized.split()) <= 2 and len(slug_title.split()) >= 4:
        return slug_title
    return normalized


def to_iso_from_epoch_seconds(seconds: str) -> str:
    try:
        return datetime.fromtimestamp(int(seconds), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return ""


def parse_embedded_cohere_entries(source: dict[str, Any], html: str) -> list[dict[str, Any]]:
    matches = COHERE_EMBEDDED_POST_PATTERN.finditer(html)
    entries: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for match in matches:
        slug = compact_text(match.group("slug")).strip("/")
        if not slug:
            continue
        url = normalize_url(urljoin(f"{source['homepage'].rstrip('/')}/", slug))
        if url in seen_urls:
            continue
        seen_urls.add(url)
        published_at = compact_text(match.group("published"))
        title = clean_anchor_title(decode_embedded_text(match.group("title")))
        entries.append(
            {
                "title": title or slug_to_title(url),
                "url": url,
                "summary": "",
                "published_at": published_at,
                "source_via": "html_embedded",
            }
        )
    return entries


def parse_embedded_manus_entries(source: dict[str, Any], html: str) -> list[dict[str, Any]]:
    matches = MANUS_EMBEDDED_POST_PATTERN.finditer(html)
    entries: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for match in matches:
        slug = compact_text(match.group("slug")).strip("/")
        if not slug:
            continue
        url = normalize_url(urljoin(f"{source['homepage'].rstrip('/')}/", slug))
        if url in seen_urls:
            continue
        seen_urls.add(url)
        title = clean_anchor_title(decode_embedded_text(match.group("title")))
        entries.append(
            {
                "title": title or slug_to_title(url),
                "url": url,
                "summary": "",
                "published_at": to_iso_from_epoch_seconds(match.group("seconds")),
                "source_via": "html_embedded",
            }
        )
    return entries


def parse_embedded_entries(source: dict[str, Any], html: str) -> list[dict[str, Any]]:
    source_id = str(source.get("id", "")).strip()
    if source_id == "cohere-blog":
        return parse_embedded_cohere_entries(source, html)
    if source_id == "manus-blog":
        return parse_embedded_manus_entries(source, html)
    return []


def extract_card_title(anchor, fallback_title: str = "") -> str:
    title = clean_anchor_title(anchor.get_text(" ", strip=True))
    if is_meaningful_title(title):
        return title
    for attribute_name in ("aria-label", "title"):
        attribute_value = clean_anchor_title(anchor.get(attribute_name, ""))
        if is_meaningful_title(attribute_value):
            return attribute_value
    parent = anchor
    for _ in range(6):
        parent = parent.parent
        if not parent:
            break
        for heading in parent.select("h1, h2, h3, h4"):
            candidate = clean_anchor_title(heading.get_text(" ", strip=True))
            if is_meaningful_title(candidate):
                return candidate
    if is_meaningful_title(fallback_title):
        return clean_anchor_title(fallback_title)
    return title


def extract_card_published_at(anchor) -> str:
    for candidate in (
        anchor.get_text(" ", strip=True),
        anchor.get("aria-label", ""),
        anchor.get("title", ""),
    ):
        match = DATE_TEXT_PATTERN.search(compact_text(candidate))
        if not match:
            continue
        parsed = parse_human_date(match.group(0))
        if parsed:
            return parsed
    parent = anchor
    for _ in range(8):
        parent = parent.parent
        if not parent:
            break
        text = compact_text(parent.get_text(" ", strip=True))
        if not text or len(text) > 500:
            continue
        match = DATE_TEXT_PATTERN.search(text)
        if not match:
            continue
        parsed = parse_human_date(match.group(0))
        if parsed:
            return parsed
    return ""


def is_meaningful_title(title: str) -> bool:
    normalized = compact_text(title).strip()
    if len(normalized) < 8:
        return False
    lowered = normalized.lower()
    if lowered in GENERIC_LINK_TITLES:
        return False
    return not any(lowered.startswith(prefix) for prefix in GENERIC_LINK_TITLES)


def parse_html_entries(
    client: httpx.Client,
    source: dict[str, Any],
    max_items: int,
) -> list[dict[str, Any]]:
    response = client.get(source["homepage"])
    if response.status_code >= 400:
        return []
    html = response.text
    soup = BeautifulSoup(html, "html.parser")
    embedded_entries = parse_embedded_entries(source, html)
    embedded_by_url = {entry["url"]: entry for entry in embedded_entries}
    candidates: list[dict[str, Any]] = []
    candidate_by_url: dict[str, dict[str, Any]] = {}
    scan_limit = int(source.get("crawl", {}).get("html_scan_limit", 500))
    scan_limit = max(max_items, min(2000, scan_limit))
    for anchor_index, anchor in enumerate(soup.select("a[href]")):
        if anchor_index >= scan_limit:
            break
        href = anchor.get("href", "").strip()
        if not href:
            continue
        absolute = normalize_url(urljoin(source["homepage"], href))
        if not likely_article_link(source["homepage"], absolute):
            continue
        embedded_entry = embedded_by_url.get(absolute)
        title = extract_card_title(anchor, (embedded_entry or {}).get("title", ""))
        title = prefer_slug_title(title, absolute)
        if not is_meaningful_title(title):
            continue
        published_at = extract_card_published_at(anchor)
        if not published_at and embedded_entry:
            published_at = embedded_entry.get("published_at", "")
        current = {
            "title": title,
            "url": absolute,
            "summary": "",
            "published_at": published_at,
            "source_via": (embedded_entry or {}).get("source_via", "html"),
            "_order": anchor_index,
            "_sort_key": parse_published_sort_key(published_at),
        }
        existing = candidate_by_url.get(absolute)
        if existing:
            if len(current["title"]) <= len(existing["title"]):
                continue
            current["_order"] = existing["_order"]
            if not current["published_at"]:
                current["published_at"] = existing["published_at"]
                current["_sort_key"] = existing["_sort_key"]
            candidate_by_url[absolute] = current
            continue
        candidate_by_url[absolute] = current
        candidates.append(current)

    for candidate in candidates:
        replacement = candidate_by_url.get(candidate["url"])
        if replacement and replacement is not candidate:
            candidate.update(replacement)

    if not candidates and embedded_entries:
        seen_urls: set[str] = set()
        for item_index, item in enumerate(embedded_entries):
            title = clean_anchor_title(item.get("title", ""))
            if not is_meaningful_title(title):
                continue
            absolute = normalize_url(item["url"])
            if absolute in seen_urls:
                continue
            seen_urls.add(absolute)
            published_at = item.get("published_at", "")
            candidates.append(
                {
                    "title": title,
                    "url": absolute,
                    "summary": "",
                    "published_at": published_at,
                    "source_via": item.get("source_via", "html_embedded"),
                    "_order": item_index,
                    "_sort_key": parse_published_sort_key(published_at),
                }
            )

    dated_candidates = sum(1 for item in candidates if item["_sort_key"] is not None)
    if candidates and dated_candidates == len(candidates):
        fallback = datetime(1970, 1, 1, tzinfo=timezone.utc)
        candidates.sort(
            key=lambda item: (item["_sort_key"] or fallback, -item["_order"]),
            reverse=True,
        )

    output: list[dict[str, Any]] = []
    for item in candidates[:max_items]:
        output.append(
            {
                "title": item["title"],
                "url": item["url"],
                "summary": item["summary"],
                "published_at": item["published_at"],
                "source_via": item["source_via"],
            }
        )
    return output


def compact_text(value: str) -> str:
    return " ".join((value or "").split())


def stable_item_uid(source_id: str, url: str, title: str) -> str:
    payload = f"{source_id}|{normalize_url(url)}|{compact_text(title)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def estimate_relevance(title: str, summary: str) -> int:
    text = f"{title} {summary}".lower()
    score = 0
    for keyword in TOPIC_KEYWORDS:
        if keyword in text:
            score += 10
    return min(score, 100)


def parse_json_object_from_text(raw_text: str) -> dict[str, Any] | None:
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(raw_text[start : end + 1])
    except json.JSONDecodeError:
        return None


def analyze_item_with_openai(
    client: httpx.Client,
    api_key: str,
    model: str,
    title: str,
    summary: str,
    source_name: str,
) -> dict[str, Any]:
    system_prompt = (
        "You are an AI news triage engine. "
        "Return JSON only with keys: relevance_score(0-100 integer), tags(array of 3-6), concise_summary(string <=120 Chinese chars)."
    )
    user_prompt = (
        f"Source: {source_name}\n"
        f"Title: {title}\n"
        f"Summary: {summary or '(empty)'}\n"
        "Assess relevance for AI model and agent engineering updates."
    )
    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
    }
    response = client.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {api_key}"},
        json=payload,
    )
    response.raise_for_status()
    body = response.json()
    raw_text = body.get("output_text") or ""
    parsed = parse_json_object_from_text(raw_text)
    if not parsed:
        raise ValueError("invalid_model_json")
    score = int(parsed.get("relevance_score", 0))
    tags = parsed.get("tags", [])
    concise_summary = parsed.get("concise_summary", "")
    return {
        "relevance": max(0, min(score, 100)),
        "tags": [str(tag).strip() for tag in tags if str(tag).strip()],
        "ai_summary": compact_text(str(concise_summary)),
        "model_used": model,
    }


def analyze_with_codex(
    client: httpx.Client,
    api_key: str,
    model: str,
    title: str,
    summary: str,
    source_name: str,
    full_content: str = "",
) -> dict[str, Any]:
    """使用 Codex API 进行深度内容分析。

    分析维度：
    - key_findings: 技术要点列表 (3-5 条)
    - has_code_example: 是否包含代码示例
    - has_api_update: 是否包含 API/框架更新
    - reading_priority: 阅读优先级 (high/medium/low)
    - estimated_reading_time: 估算阅读时间 (分钟)
    """
    content = full_content or summary or title
    text_for_indicators = content.lower()

    has_code = any(indicator in text_for_indicators for indicator in CODE_INDICATORS)
    has_api = any(indicator in text_for_indicators for indicator in API_INDICATORS)

    word_count = len(content.split())
    reading_time = max(1, round(word_count / 200))

    system_prompt = (
        "You are an expert AI technical analyst. Analyze the article and return ONLY valid JSON with: "
        "key_findings (array of 3-5 technical insights), "
        "reading_priority ('high'|'medium'|'low'), "
        "technical_depth (1-5 integer)."
    )
    user_prompt = (
        f"Source: {source_name}\n"
        f"Title: {title}\n"
        f"Content: {content[:2000] or '(empty)'}\n\n"
        "Analyze for AI/ML engineers. Focus on: novel techniques, performance improvements, "
        "new capabilities, practical applications."
    )

    try:
        payload = {
            "model": model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        response = client.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        response.raise_for_status()
        body = response.json()
        raw_text = body.get("output_text") or ""
        parsed = parse_json_object_from_text(raw_text)

        if not parsed:
            raise ValueError("invalid_codex_json")

        key_findings = parsed.get("key_findings", [])
        priority = parsed.get("reading_priority", "medium")
        tech_depth = int(parsed.get("technical_depth", 3))

        if priority not in ("high", "medium", "low"):
            priority = "medium"
        tech_depth = max(1, min(5, tech_depth))

        return {
            "key_findings": [str(f).strip() for f in key_findings[:5] if str(f).strip()],
            "has_code_example": has_code,
            "has_api_update": has_api,
            "reading_priority": priority,
            "technical_depth": tech_depth,
            "estimated_reading_time": reading_time,
            "model_used": model,
        }
    except Exception:
        return {
            "key_findings": [],
            "has_code_example": has_code,
            "has_api_update": has_api,
            "reading_priority": "medium",
            "technical_depth": 3,
            "estimated_reading_time": reading_time,
            "model_used": "rule-based-fallback",
        }


def estimate_reading_time(text: str) -> int:
    """估算阅读时间（分钟），基于平均阅读速度 200 词/分钟。"""
    word_count = len((text or "").split())
    return max(1, round(word_count / 200))
