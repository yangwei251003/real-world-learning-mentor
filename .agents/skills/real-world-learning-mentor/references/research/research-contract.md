# 新领域调研契约

仅在开始新主题、事实可能变化、风险较高或当前来源过期时加载。

## 最小调研包

确认该领域的真实成果、核心能力、最低先修、当前工具/版本、资源成本、常见失败、风险边界、可观察证据和适合当前用户的第一任务。稳定概念与易过期步骤分开记录。

关键结论优先使用官方文档、标准、法规、原始研究或维护良好的项目文档。技术结论不得只依赖搜索摘要或转述文章。

## 记录

每个来源使用 `references/schemas/source.schema.json` 的字段：

```text
source_id, title, url, publisher, accessed_at, version_or_date,
license, supported_claim, freshness_class, expires_at, conflict_status
```

来源冲突时保留条件与未解决状态，不拼成伪确定答案。借鉴开源成果前检查许可证，只迁移机制并原创实现。

项目级研究基线、GitHub 案例、许可证和借鉴日志在根目录 `docs/research/`；它们用于理解本 Skill 的设计来源，不等于当前新领域的最新资料。当前课程仍需按新鲜度规则核验。
