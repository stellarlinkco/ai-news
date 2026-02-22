# 运行实测报告（2026-02-21 UTC）

## 1) 测试范围

- 仓库：`ai-news`
- 目标：验证真实 blog/news 拉取与总结生成
- 唯一入口：`scripts/pipeline.py`
- 运行方式：
  - 直接本地执行
  - `codex exec` 执行

## 2) 测试命令

```bash
# RSS 审计（隔离输出）
.venv/bin/python scripts/rss_audit.py \
  --sources config/sources.yaml \
  --out data/runtime-test/rss-audit.json \
  --workers 12

# 直接执行 pipeline
.venv/bin/python scripts/pipeline.py \
  --sources config/sources.yaml \
  --db data/runtime-test/ai-news.db \
  --daily-dir data/runtime-test/daily \
  --latest-json data/runtime-test/latest.json \
  --latest-md data/runtime-test/latest.md \
  --web-dir web/runtime-test \
  --workers 10 \
  --use-codex

# 通过 Codex 执行同一 pipeline
codex exec --sandbox danger-full-access --skip-git-repo-check \
  "仅执行该命令并返回结果，不修改脚本代码：.venv/bin/python scripts/pipeline.py \
  --sources config/sources.yaml \
  --db data/runtime-test/codex/ai-news.db \
  --daily-dir data/runtime-test/codex/daily \
  --latest-json data/runtime-test/codex/latest.json \
  --latest-md data/runtime-test/codex/latest.md \
  --web-dir web/runtime-test-codex \
  --workers 6 --use-codex"
```

## 3) 结果

### 3.1 RSS 审计

- 输出：`data/runtime-test/rss-audit.json`
- `confirmed_total=11`，`sources_total=19`
- `checked_at=2026-02-21T16:56:55.315990+00:00`

### 3.2 直接执行 pipeline

- 输出：`data/runtime-test/latest.json`
- `generated_at=2026-02-21T16:57:19.067698+00:00`
- `sources_checked=19`
- `sources_successful=19`
- `sources_with_items=19`
- `new_items_count=308`
- `sources_skipped_cooldown=0`
- `retry_attempted_sources=0`
- `retry_recovered_sources=0`

### 3.3 Codex 执行 pipeline

- 输出：`data/runtime-test/codex/latest.json`
- `generated_at=2026-02-21T17:00:42.268165+00:00`
- `sources_checked=19`
- `sources_successful=19`
- `sources_with_items=19`
- `new_items_count=308`
- 与直接执行结果一致：**已匹配**

## 4) 数据与总结校验

- SQLite（`data/runtime-test/codex/ai-news.db`）：
  - `rows=308`，`distinct_sources=19`
- 来源抓取模式（codex run）：
  - `rss_config=11`
  - `html=8`
- 每日总结已生成：
  - `data/runtime-test/codex/latest-summary.md`
  - 包含“概览 / 主题 / Top5 推荐”
- Web 产物已生成：
  - `web/runtime-test-codex/data/latest.json`
  - `web/runtime-test-codex/data/latest.md`
  - `web/runtime-test-codex/data/latest-summary.md`
  - `web/runtime-test-codex/data/history.json`

## 5) Top 内容样例（Codex Run）

1. Microsoft Foundry Blog — Beyond the Prompt – Why and How to Fine-tune Your Own Models
2. Vercel Blog — Skills Night: 69,000+ ways agents are getting smarter
3. Vercel Blog — Qwen 3.5 Plus is on AI Gateway
4. Microsoft Foundry Blog — Foundry IQ in Microsoft Agent Framework
5. AWS Machine Learning Blog — Scale LLM fine-tuning with Hugging Face and Amazon SageMaker AI

## 6) 结论

- 真实抓取、分析、总结链路端到端可用。
- 单一入口 `scripts/pipeline.py` 在直接执行与 Codex 执行两条链路均正常。
- 本次运行来源覆盖 `19/19`，产物完整，结果稳定。
