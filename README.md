# AI News Daily Collector

每天自动聚合 AI 模型公司、Agent 框架与工程博客更新，优先 RSS，失败回退页面解析，并输出到本地数据、Webhook、GitHub Pages。当前工作流使用 `codex + skill` 单一编排入口。

## 已做内容

- 来源池：`config/sources.yaml`
- RSS 审计脚本：`scripts/rss_audit.py`
- 每日管道：`scripts/pipeline.py`
- 技能模块：`skills/crawl_ai_news.py`、`skills/analyze_ai_news.py`、`skills/generate_daily_summary.py`
- 失败恢复：失败来源自动二次重试 + 源健康度分级冷却（`healthy/degraded/unhealthy`）
- 编排入口：`.github/workflows/daily-ai-news.yml`（`openai/codex-action@v1`）
- 网页展示：`web/index.html` + `web/data/latest.json`

## 快速开始（本地脚本调试）

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/rss_audit.py --update
python scripts/pipeline.py --update-sources --use-codex
```

## 本地模拟编排入口（Codex）

```bash
npm install -g @openai/codex@0.104.0
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
OPENAI_BASE_URL=https://api.openai.com/v1 OPENAI_API_KEY=your_key OPENAI_MODEL=gpt-4.1-mini codex exec --sandbox danger-full-access --skip-git-repo-check "依次运行 python scripts/rss_audit.py --sources config/sources.yaml --out data/rss-audit-latest.json --update 和 python scripts/pipeline.py --sources config/sources.yaml --update-sources --use-codex，失败即退出。"
```

## 环境变量 / Secrets

- `OPENAI_RESPONSES_API_ENDPOINT`：可选，供 `openai/codex-action` 使用，推荐填完整 endpoint（如 `https://api.openai.com/v1/responses`）
- `OPENAI_BASE_URL`：可选，供 Python 脚本使用，支持 `.../v1` 或 `.../v1/responses`，默认 `https://api.openai.com/v1`
- `OPENAI_API_KEY`：必需（Codex Action 鉴权；脚本模型分析也依赖）
- `OPENAI_MODEL`：可选，默认 `gpt-4.1-mini`（兼容旧变量 `AI_MODEL`）
- `WEBHOOK_URL`：可选，允许为空，配置后推送每日结果
- `WEBHOOK_SECRET`：可选，配置后启用 HMAC-SHA256 签名

## GitHub Actions Secret 建议

- 必需：`OPENAI_API_KEY`
- 可选：`OPENAI_RESPONSES_API_ENDPOINT`、`OPENAI_BASE_URL`、`OPENAI_MODEL`、`WEBHOOK_URL`、`WEBHOOK_SECRET`

## 工作流执行说明

- `daily-ai-news.yml` 通过 `openai/codex-action@v1` 触发每日编排。
- 编排入口由 Codex 执行两步：RSS 审计 + `scripts/pipeline.py`。
- 产物仍提交到 `config/sources.yaml`、`data/`、`web/`，并部署到 GitHub Pages。

## 数据产物

- `data/rss-audit-latest.json`：最新 RSS 可用性审计
- `data/daily/YYYY-MM-DD.json`：每日采集结果
- `data/latest.json`：最近一次运行结果
- `data/latest.md`：最近一次运行的 Markdown 摘要
- `data/latest-summary.md`：每日总结（主题 + Top5 推荐）
- `web/data/latest.json`：前端读取数据
- `web/data/latest.md`：前端可直接引用的摘要文件
- `web/data/latest-summary.md`：前端可展示的每日总结
- `web/data/history.json`：历史索引

## 失败重试与健康度回退

- 首轮采集后，`status=error` 的来源会进入二次重试队列（默认 `crawl.retry_on_failure: 1`）
- 二次重试默认延迟 2 秒，可通过 `crawl.retry_delay_seconds` 调整
- 连续失败会更新到 `source.health`：
  - `consecutive_failures`
  - `level`（`healthy` / `degraded` / `unhealthy`）
  - `cooldown_until`（冷却到期前自动跳过该来源）
- 默认阈值：
  - `degraded_after_failures=2`（冷却 60 分钟）
  - `unhealthy_after_failures=4`（冷却 360 分钟）
- 运行结果新增字段：`sources_skipped_cooldown`、`retry_attempted_sources`、`retry_recovered_sources`
