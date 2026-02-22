# Product Requirements Document: AI Agent 每日情报聚合系统

**Version**: 1.0  
**Date**: 2026-02-21  
**Author**: Sarah (Product Owner)  
**Quality Score**: 92/100

---

## Executive Summary

本项目目标是构建一个公开仓库驱动的 AI 资讯采集与分发系统：每天由 GitHub Actions 定时执行脚本，自动从模型公司、Agent 框架与高质量 AI 工程博客抓取最新内容，进行结构化保存与 AI 处理，再输出到 Web 页面与 Webhook。

核心价值在于“稳定、可追溯、低人工成本”的情报管道。相比手动巡检多个站点，系统以 RSS 优先、页面抓取兜底的方式提高覆盖率，并通过模型对内容进行相关性判断和摘要，降低噪声。

**Assumption**: MVP 以“开发者个人/小团队自用”为主，优先保证每日稳定采集与历史可追溯，不追求实时秒级推送。

---

## Problem Statement

**Current Situation**: AI 相关高价值信息分散在多个博客与公告渠道，人工跟踪成本高、容易漏读，且缺少统一历史记录与结构化视图。  

**Proposed Solution**: 构建“定时采集 → 规范化存储 → AI 分析 → 多通道分发（Webhook + Web）”的一体化流水线，优先使用 RSS，缺失 RSS 时再回退页面解析。  

**Business Impact**:
- 将每日人工巡检时间从 30–60 分钟降至 5 分钟以内
- 将重点来源更新漏检率降到 <5%
- 为后续趋势分析、选题与技术决策提供可复用数据资产

---

## Success Metrics

**Primary KPIs:**
- 采集任务成功率：`>= 98%`（按日统计 GitHub Actions 成功运行占比）
- 更新捕获时效：`>= 95%` 的新文章在发布后 24 小时内入库
- 内容相关性准确率：AI 标记为“高相关”的条目人工抽检准确率 `>= 85%`

**Validation**: 每周自动汇总运行日志与抽样结果，月度复盘来源质量、漏检原因与模型判定偏差。

---

## User Personas

### Primary: AI 工程开发者（维护者）
- **Role**: 独立开发者/技术负责人
- **Goals**: 每天低成本获取高质量 AI/Agent 相关更新
- **Pain Points**: 渠道分散、信息噪声高、无法持续追踪
- **Technical Level**: Advanced

### Secondary: 小型研发团队成员
- **Role**: 算法/应用工程师
- **Goals**: 快速浏览每日精华并追溯原文
- **Pain Points**: 信息过载，难以定位与当前项目强相关内容
- **Technical Level**: Intermediate

---

## User Stories & Acceptance Criteria

### Story 1: 来源配置与扩展
**As a** 维护者  
**I want to** 配置并管理来源列表（公司/框架/个人）  
**So that** 系统可以稳定覆盖重点信息源

**Acceptance Criteria:**
- [ ] 支持统一配置文件定义来源类型、URL、RSS 地址与抓取策略
- [ ] 新增来源无需改代码逻辑（仅改配置即可生效）
- [ ] 当来源不可用时有明确错误记录与跳过策略

### Story 2: 每日自动采集
**As a** 维护者  
**I want to** 通过 GitHub Actions 定时运行采集任务  
**So that** 我不需要手动执行脚本

**Acceptance Criteria:**
- [ ] 支持 cron 定时与手动触发两种运行方式
- [ ] 采集失败具备重试与最终失败告警
- [ ] 同一文章重复抓取时不重复入库（幂等）

### Story 3: AI 相关性筛选与摘要
**As a** 团队成员  
**I want to** 获取 AI/Agent 相关内容的自动摘要与标签  
**So that** 我可以快速判断是否值得深入阅读

**Acceptance Criteria:**
- [ ] 每条内容输出主题标签、相关性分数与摘要
- [ ] 明确记录模型调用失败并回退为“仅原始条目”
- [ ] 结果可复现（保留模型版本、提示词版本）

### Story 4: Webhook 与 Web 展示
**As a** 维护者  
**I want to** 将每日结果推送到 Webhook，并在网页中查看历史  
**So that** 我能集成现有通知系统并随时回看

**Acceptance Criteria:**
- [ ] Webhook payload 含签名与版本字段
- [ ] 推送失败时支持重试并记录重放信息
- [ ] Web 页面可按日期与来源筛选查看

---

## Functional Requirements

### Core Features

**Feature 1: 来源注册中心（RSS 优先）**
- Description: 统一管理来源元数据，优先读取 RSS/Atom，失败时回退页面解析
- User flow: 读取配置 → 尝试 RSS → 抓取增量条目 → 标准化字段
- Edge cases: RSS 返回空、Feed 重定向、站点结构变更
- Error handling: 记录失败原因、标记来源健康状态、不中断全局任务

**Feature 2: 定时采集与去重入库**
- Description: 由 GitHub Actions 执行采集，基于 URL + 内容哈希去重
- User flow: 触发任务 → 并行拉取 → 归一化 → 去重 → 入库
- Edge cases: 网络抖动、超时、部分来源 403
- Error handling: 单来源失败不影响其他来源；支持指数退避重试

**Feature 3: AI 分析流水线**
- Description: 使用模型进行相关性分类、摘要、关键词提取
- User flow: 入库原文摘要素材 → 调用模型 → 写回分析结果
- Edge cases: 模型限流、上下文超限、返回格式异常
- Error handling: 降级到规则分类或仅保留原始数据，记录可审计日志

**Feature 4: 多通道输出**
- Description: 生成本地产物（JSON/Markdown/SQLite）并推送 Webhook，构建静态 Web 页面
- User flow: 汇总每日结果 → 输出文件 → 推送 Webhook → 更新网页
- Edge cases: Webhook 目标超时、页面生成失败
- Error handling: 输出与推送分离，单点失败不阻断整体归档

### Out of Scope
- 实时分钟级流式抓取
- 绕过强反爬策略或登录态内容抓取
- 付费资讯内容全文存储

---

## Technical Constraints

### Performance
- 单日任务在 15 分钟内完成（约 100 个来源规模）
- 单来源抓取超时上限 20 秒
- 模型调用成本控制在可配置预算内（默认日预算）

### Security
- API Key 与 Webhook Secret 必须存放于 GitHub Secrets
- Webhook 使用 HMAC 签名，防重放时间窗校验
- 存储策略默认仅保留摘要/片段与原文链接，避免版权与合规风险

### Integration
- **GitHub Actions**: 定时调度、运行日志、失败通知
- **Codex Action/CLI + Skill**: 触发采集与 AI 分析编排
- **Webhook Endpoint**: 下游通知或消息系统集成
- **GitHub Pages**: 静态页面托管与历史归档展示

### Technology Stack
- 采集与处理脚本：Python（建议）或 Node.js（二选一）
- 数据层：SQLite + JSON 导出
- 页面层：静态 HTML（后续可升级到轻量前端框架）

---

## MVP Scope & Phasing

### Phase 1: MVP (Required for Initial Launch)
- 来源配置管理（含你提供的种子站点）
- GitHub Actions 每日调度
- RSS 优先采集 + 页面兜底解析
- 去重入库与运行日志
- AI 相关性打分 + 摘要
- Webhook 推送 + 静态页面每日列表

**MVP Definition**: 在无人值守情况下，系统可连续 7 天稳定产出“可读、可追溯、可分发”的每日 AI 情报。

### Phase 2: Enhancements (Post-Launch)
- 来源自动发现（feed/sitemap 探测）
- 主题聚类与趋势检测
- 多语言摘要与翻译

### Future Considerations
- 个性化订阅（按标签/公司/框架）
- 语义检索与问答接口

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation Strategy |
|------|------------|--------|---------------------|
| 来源结构变化导致抓取失败 | High | High | RSS 优先 + 可插拔解析器 + 来源健康检查 |
| 模型限流或成本不可控 | Med | High | 批处理、缓存、降级模型、预算上限 |
| Webhook 下游不稳定 | Med | Med | 签名重试、死信记录、可重放机制 |
| 合规/版权风险 | Low | High | 仅存摘要与链接，保留来源归属与引用规范 |

---

## Dependencies & Blockers

**Dependencies:**
- GitHub 仓库与 Actions 运行权限
- 可用的模型 API（及配额）
- 可接收并验证签名的 Webhook 服务

**Known Blockers:**
- 部分来源可能无 RSS 且页面反爬严格，需要单独解析策略
- 不同来源发布时间字段不统一，需标准化规则

---

## Appendix

### Glossary
- **RSS/Atom**: 用于订阅网站更新的标准 Feed 格式
- **Webhook**: 系统向外部服务主动推送事件数据的 HTTP 回调机制
- **幂等**: 重复执行同一操作不会产生重复副作用

### References
- https://www.anthropic.com/engineering
- https://manus.im/blog
- https://blog.langchain.com/
- https://huggingface.co/blog/
- https://github.blog/
- https://openai.com/news/engineering/
- https://developers.openai.com/blog/
- https://blog.cloudflare.com/
- https://claude.com/blog
- https://vercel.com/blog

---

*This PRD was created through structured requirements analysis with explicit assumptions, measurable KPIs, and phased scope control for implementation readiness.*
