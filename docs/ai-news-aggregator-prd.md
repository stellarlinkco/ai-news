# Product Requirements Document: AI News Aggregator (Codex-Powered)

**Version**: latest
**Date**: 2026-02-21
**Author**: Sarah (Product Owner)
**Quality Score**: 92/100

---

## Executive Summary

AI News Aggregator is a complete architectural redesign of the existing Python-based news collection system, transitioning to a **codex + skill** architecture. The system will continue to aggregate daily updates from 20+ AI companies, model providers, and agent frameworks, but will leverage GitHub Actions to trigger codex execution with specialized skills for crawling, analysis, and content generation.

This redesign maintains the core value proposition—automated RSS-first collection with HTML fallback, AI-powered relevance scoring, and multi-channel distribution—while introducing deeper content analysis (key findings extraction, daily summaries) and enhanced web UI capabilities (search/filter, historical browsing). The system remains fully open-source on GitHub with public GitHub Pages hosting.

**Business Impact**: Provides AI practitioners with a single, intelligent aggregation point for tracking technical developments across the fragmented AI ecosystem, reducing information overload through AI-powered curation and prioritization.

---

## Problem Statement

**Current Situation**:
The current Python-based implementation (`scripts/pipeline.py`) successfully collects and processes AI news from 20 sources, but:
- Architecture is monolithic and difficult to extend with new analysis capabilities
- AI analysis is limited to basic relevance scoring and summarization
- Web UI is minimal (simple list view) without search, filtering, or historical navigation
- Content processing logic is tightly coupled to the collection pipeline

**Proposed Solution**:
Redesign the system using a **codex + skill** architecture where:
- GitHub Actions triggers codex execution daily
- Specialized skills handle crawling, AI analysis, and content generation as modular components
- Enhanced AI analysis extracts key findings and generates daily summaries
- Improved web UI supports search/filter and historical browsing while maintaining simplicity

**Business Impact**:
- Faster iteration on new analysis features through modular skill architecture
- Deeper insights through enhanced AI processing (key findings, daily summaries)
- Better user experience through searchable, filterable historical archive
- Maintained open-source accessibility and zero hosting costs via GitHub Pages

---

## Success Metrics

**Primary KPIs:**
- **Collection Reliability**: ≥95% successful daily runs (measured via GitHub Actions success rate)
- **Content Freshness**: New articles detected within 24 hours of publication (measured via `published_at` vs `collected_at` delta)
- **AI Analysis Quality**: ≥80% relevance score accuracy (validated through manual spot-checks of top 20 items/day)

**Secondary KPIs:**
- **Web Engagement**: GitHub Pages traffic and unique visitors (measured via GitHub Insights)
- **Data Completeness**: ≥18/20 sources successfully crawled per day (measured via `sources_with_items` count)
- **Webhook Delivery**: ≥99% successful webhook deliveries when configured (measured via webhook response codes)

**Validation**:
- Daily automated monitoring via GitHub Actions logs
- Weekly manual review of top 10 articles for relevance accuracy
- Monthly analysis of source coverage and failure patterns

---

## User Personas

### Primary: AI Engineer / Researcher

- **Role**: Software engineer or researcher working on AI/ML systems, agent frameworks, or LLM applications
- **Goals**:
  - Stay current with latest model releases, API updates, and framework improvements
  - Discover technical blog posts with code examples and implementation details
  - Track developments from specific companies (e.g., OpenAI, Anthropic, LangChain)
- **Pain Points**:
  - Information overload from following 20+ separate blogs/RSS feeds
  - Difficulty filtering signal from noise (marketing vs. technical content)
  - No centralized view of daily AI ecosystem developments
- **Technical Level**: Advanced (comfortable with GitHub, RSS, webhooks)

### Secondary: Product Manager / Tech Lead

- **Role**: Technical decision-maker evaluating AI tools and frameworks
- **Goals**:
  - Monitor competitive landscape and emerging trends
  - Identify new capabilities for product roadmap planning
  - Share curated updates with engineering teams
- **Pain Points**:
  - Time-constrained, needs quick daily digest
  - Requires high-level summaries, not deep technical details
  - Wants historical context for trend analysis
- **Technical Level**: Intermediate (uses web UI, may consume via webhook)

---

## User Stories & Acceptance Criteria

### Story 1: Daily Automated Collection via Codex

**As a** system administrator
**I want to** trigger codex execution via GitHub Actions daily
**So that** news collection runs automatically without manual intervention

**Acceptance Criteria:**
- [ ] GitHub Actions workflow triggers codex at scheduled time (01:15 UTC daily)
- [ ] Codex executes crawling skill to fetch articles from all 20 sources
- [ ] RSS feeds are prioritized; HTML parsing is fallback when RSS unavailable
- [ ] New articles are deduplicated using stable UID (source_id + url + title hash)
- [ ] Collected data is committed to repository (`data/daily/YYYY-MM-DD.json`)
- [ ] Workflow fails gracefully with error logs if codex execution fails

### Story 2: Enhanced AI Analysis with Key Findings

**As an** AI engineer
**I want** articles to include extracted key findings (technical breakthroughs, API updates, code examples)
**So that** I can quickly identify high-value content without reading full articles

**Acceptance Criteria:**
- [ ] AI analysis skill extracts structured key findings: `technical_depth`, `has_code_example`, `has_api_update`, `reading_priority`
- [ ] Findings are stored in database schema: `key_findings_json`, `has_code_example`, `has_api_update`, `technical_depth`, `estimated_reading_time`
- [ ] Relevance scoring (0-100) continues to work as baseline filter
- [ ] Fallback to rule-based analysis if AI model unavailable (no blocking failures)
- [ ] Key findings displayed in web UI card view

### Story 3: Daily Summary Generation

**As a** product manager
**I want** an AI-generated daily summary of all articles
**So that** I can understand the day's key trends in 2-3 minutes

**Acceptance Criteria:**
- [ ] AI summary skill generates daily digest highlighting: top 3-5 articles, emerging themes, notable announcements
- [ ] Summary saved to `data/latest-summary.md` and `web/data/latest-summary.md`
- [ ] Summary includes: date, article count, top themes, recommended reads
- [ ] Summary generation does not block main pipeline (runs as separate step)
- [ ] Summary displayed prominently on web UI homepage

### Story 4: Web UI Search and Filtering

**As an** AI engineer
**I want to** filter articles by source, tag, relevance, and date
**So that** I can find specific content (e.g., "all LangChain articles about agents")

**Acceptance Criteria:**
- [ ] Search bar filters by title/summary text (client-side JavaScript)
- [ ] Dropdown filters for: source name, tags, relevance threshold (≥70, ≥80, ≥90)
- [ ] Date range picker for historical browsing (last 7/30/90/180 days)
- [ ] Filters are combinable (e.g., "LangChain + agent tag + last 30 days")
- [ ] URL parameters preserve filter state for sharing (e.g., `?source=langchain&tag=agent`)
- [ ] UI remains simple and fast (no heavy frameworks, vanilla JS preferred)

### Story 5: Historical Archive Browsing

**As a** tech lead
**I want to** browse past daily digests by date
**So that** I can review what happened during a specific time period

**Acceptance Criteria:**
- [ ] Web UI displays calendar or date list for last 180 days
- [ ] Clicking a date loads that day's articles from `data/daily/YYYY-MM-DD.json`
- [ ] Historical view shows same card layout as current day
- [ ] Navigation between dates (previous/next day buttons)
- [ ] `web/data/history.json` maintains index of all available dates with metadata (article count, top titles)

---

## Functional Requirements

### Core Features

**Feature 1: Codex-Powered Crawling Pipeline**

- **Description**: Evolve Python `scripts/pipeline.py` with codex + skill architecture
- **User flow**:
  1. GitHub Actions workflow triggers at 01:15 UTC daily
  2. Workflow invokes codex with `crawl-ai-news` skill
  3. Skill reads `config/sources.yaml` for source list
  4. For each source: attempt RSS fetch → fallback to HTML parsing if RSS fails
  5. Skill returns collected articles as structured JSON
  6. Workflow commits results to `data/daily/YYYY-MM-DD.json`
- **Edge cases**:
  - Source website down: log error, continue with other sources
  - RSS feed malformed: fallback to HTML parsing
  - Rate limiting: implement exponential backoff (1s, 2s, 4s delays)
- **Error handling**:
  - Workflow fails if <10 sources successfully crawled (critical threshold)
  - Individual source failures logged but do not block pipeline
  - Retry logic: 3 attempts per source with 2s delay

**Feature 2: AI Analysis Skill with Key Findings**

- **Description**: Enhanced AI processing to extract structured insights beyond basic summarization
- **User flow**:
  1. Crawling skill passes article metadata (title, summary, url) to analysis skill
  2. Analysis skill calls OpenAI API (or configured model) with structured prompt
  3. Model returns JSON: `{relevance: 85, tags: ["agent", "llm"], ai_summary: "...", key_findings: {...}}`
  4. Key findings include: `technical_depth` (1-5), `has_code_example` (bool), `has_api_update` (bool), `reading_priority` (high/medium/low), `estimated_reading_time` (minutes)
  5. Results stored in SQLite database with extended schema
- **Edge cases**:
  - API rate limit: queue requests with exponential backoff
  - Model timeout: fallback to rule-based analysis (keyword matching)
  - Invalid JSON response: retry once, then fallback
- **Error handling**:
  - Fallback to rule-based scoring if API unavailable (no blocking)
  - Log all API errors for debugging
  - Continue pipeline even if analysis fails for individual articles

**Feature 3: Daily Summary Generation Skill**

- **Description**: AI-generated digest of the day's articles highlighting key themes and top reads
- **User flow**:
  1. After all articles collected and analyzed, summary skill is invoked
  2. Skill receives array of top 30 articles (sorted by relevance)
  3. Calls AI model with prompt: "Summarize today's AI news, identify 3 key themes, recommend top 5 reads"
  4. Model returns markdown-formatted summary (300-500 words)
  5. Summary saved to `data/latest-summary.md` and `web/data/latest-summary.md`
- **Edge cases**:
  - Zero new articles: generate "No new articles today" summary
  - <5 articles: skip theme identification, just list articles
- **Error handling**:
  - Summary generation failure does not block main pipeline
  - Fallback to template-based summary if AI unavailable

**Feature 4: Enhanced Web UI**

- **Description**: Improved GitHub Pages site with search, filtering, and historical browsing
- **User flow**:
  1. User visits GitHub Pages URL
  2. Homepage displays: daily summary (top section), filter controls (sidebar), article cards (main area)
  3. User applies filters (source, tag, relevance, date range)
  4. JavaScript filters `latest.json` data client-side and re-renders cards
  5. User clicks "History" to view calendar of past 180 days
  6. Clicking a date fetches `data/daily/YYYY-MM-DD.json` and displays articles
- **Edge cases**:
  - No articles match filters: display "No results" message
  - Historical date has no data: display "No data for this date"
  - Slow network: show loading spinner during fetch
- **Error handling**:
  - JSON fetch failure: display error message with retry button
  - Invalid filter combinations: disable conflicting options

### Out of Scope

- **RSS feed generation**: Users cannot subscribe to aggregator output via RSS (may add in Phase 2)
- **User accounts/authentication**: No personalized recommendations or saved preferences
- **Real-time updates**: Daily batch processing only, no live streaming
- **Mobile app**: Web UI is responsive but no native mobile app
- **Email notifications**: Webhook-only distribution (no email digest)
- **Content archival beyond 180 days**: Historical data older than 180 days is pruned

---

## Technical Constraints

### Performance

- **Pipeline execution time**: Complete daily run (crawl + analysis + summary) must finish within 30 minutes
- **Web UI load time**: Initial page load <2s on 3G connection (target: <1s on broadband)
- **Database query performance**: SQLite queries for deduplication <100ms per article
- **API rate limits**: Respect OpenAI rate limits (3500 RPM for gpt-4o-mini), implement batching if needed

### Security

- **API key management**: Store `OPENAI_API_KEY` in GitHub Actions secrets, never commit to repository
- **Webhook signature**: Use HMAC-SHA256 signature (`X-AI-News-Signature` header) to verify webhook authenticity
- **Input validation**: Sanitize all scraped HTML content to prevent XSS in web UI
- **Dependency security**: Run `npm audit` / `pip audit` in CI to detect vulnerable dependencies

### Integration

- **GitHub Actions**: Workflow must use `ubuntu-latest` runner, Python 3.11+, and codex CLI
- **Codex CLI**: Install via `pip install codex-cli` (or equivalent), authenticate with API key
- **OpenAI API**: Support OpenAI-compatible endpoints (configurable via `AI_MODEL` and `OPENAI_BASE_URL` env vars)
- **Webhook endpoint**: POST JSON payload to configurable `WEBHOOK_URL` with retry logic (3 attempts, exponential backoff)

### Technology Stack

- **Orchestration**: GitHub Actions (daily cron schedule)
- **Execution engine**: Codex CLI with custom skills
- **Skills**: Modular Python/JavaScript skills for crawling, analysis, summary generation
- **Database**: SQLite (single file `data/ai-news.db`) for deduplication and historical queries
- **Web frontend**: Static HTML/CSS/JavaScript (no build step), vanilla JS for filtering
- **Hosting**: GitHub Pages (static site deployment from `web/` directory)
- **AI model**: OpenAI GPT-4o-mini (default), configurable to other OpenAI-compatible models

---

## MVP Scope & Phasing

### Phase 1: MVP (Required for Initial Launch)

**Core Infrastructure:**
- [ ] GitHub Actions workflow triggering codex daily
- [ ] Crawling skill with RSS-first + HTML fallback logic
- [ ] SQLite deduplication using stable UID
- [ ] Basic AI analysis (relevance, tags, summary) via skill

**Enhanced Analysis:**
- [ ] Key findings extraction (technical_depth, has_code_example, has_api_update, reading_priority)
- [ ] Extended database schema for key findings
- [ ] Daily summary generation skill

**Web UI:**
- [ ] Search bar (filter by title/summary text)
- [ ] Dropdown filters (source, tag, relevance threshold)
- [ ] Date range picker (last 7/30/90/180 days)
- [ ] Historical archive browsing (calendar view + date navigation)
- [ ] Display key findings in article cards

**Distribution:**
- [ ] Webhook delivery with HMAC signature
- [ ] Commit artifacts to repository (`data/`, `web/data/`)
- [ ] GitHub Pages deployment

**MVP Definition**: System can replace existing Python pipeline with feature parity + enhanced analysis + improved web UI, running reliably for 7 consecutive days without manual intervention.

### Phase 2: Enhancements (Post-Launch)

- [ ] RSS feed generation for aggregator output (users can subscribe)
- [ ] Personalized recommendations based on user-selected topics (requires lightweight user preferences)
- [ ] Email digest option (daily/weekly summary via email)
- [ ] Advanced analytics dashboard (trending topics, source activity heatmap)
- [ ] Mobile-optimized PWA (progressive web app) for offline reading

### Future Considerations

- [ ] Multi-language support (translate summaries to Chinese, Japanese, etc.)
- [ ] Integration with Slack/Discord for team notifications
- [ ] AI-powered "deep dive" mode: fetch full article content and generate detailed analysis
- [ ] Community contributions: allow users to submit new sources via PR

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation Strategy |
|------|------------|--------|---------------------|
| Codex CLI breaking changes | Medium | High | Pin codex version in `requirements.txt`, test upgrades in staging branch before production |
| OpenAI API rate limits exceeded | Medium | Medium | Implement request batching (10 articles/batch), add exponential backoff, fallback to rule-based analysis |
| Source websites block scraping | Low | Medium | Rotate user-agent strings, respect robots.txt, add 1-2s delay between requests per domain |
| GitHub Actions quota exhaustion | Low | High | Monitor usage via GitHub billing dashboard, optimize workflow to reduce runtime (target <15min) |
| SQLite database corruption | Low | High | Daily backup to `data/backups/`, implement write-ahead logging (WAL mode) |
| Skill execution failures | Medium | Medium | Wrap all skill calls in try-catch, log errors to GitHub Actions, send alert via webhook if >50% skills fail |

---

## Dependencies & Blockers

**Dependencies:**
- **Codex CLI availability**: Requires codex CLI to be publicly available and stable (owner: Codex team)
- **GitHub Actions runner capacity**: Depends on GitHub's infrastructure uptime (owner: GitHub)
- **OpenAI API access**: Requires valid API key with sufficient quota (owner: project maintainer)

**Known Blockers:**
- **Skill development timeline**: Custom skills for crawling, analysis, and summary generation must be developed and tested before migration (estimated: 2-3 weeks)
- **Data migration**: Existing SQLite database schema must be extended to support key findings fields (requires migration script)

---

## Appendix

### Glossary

- **Codex**: AI-powered code execution platform that runs skills (modular scripts) in response to triggers
- **Skill**: Modular, reusable script (Python/JavaScript) that performs a specific task (e.g., crawling, analysis)
- **RSS-first strategy**: Attempt to fetch RSS feed before falling back to HTML parsing
- **Stable UID**: Deterministic unique identifier for articles: `sha256(source_id + url + title)`
- **Key findings**: Structured metadata extracted by AI (technical depth, code examples, API updates, reading priority)
- **Daily summary**: AI-generated digest of the day's articles (300-500 words, highlights themes and top reads)

### References

- Existing implementation: `scripts/pipeline.py`, `scripts/rss_audit.py`
- Source configuration: `config/sources.yaml`
- Database schema: `scripts/pipeline.py` (SQLite table definition)
- Web UI: `web/index.html`
- GitHub Actions workflow: `.github/workflows/daily-ai-news.yml`

---

*This PRD was created through interactive requirements gathering with quality scoring (92/100) to ensure comprehensive coverage of business, functional, UX, and technical dimensions. The redesign maintains the proven value of the existing system while introducing modular architecture and enhanced capabilities.*
