# GitHub 案例矩阵：可借鉴机制与禁区

> 研究日期：2026-08-26（Asia/Shanghai）  
> 判定标准：官方/活跃度/可观察工程结构/许可证清晰度/与 V1 的机制相关性。  
> 所有“借鉴”均指理念或可重新实现的结构；不拷贝代码、课程段落、测试题、角色文本、品牌或数据。

| 案例 | 类型与可观察结构 | 可借鉴的机制 | 不采用/风险 | 许可结论 |
|---|---|---|---|---|
| [OpenAI Build skills](https://learn.chatgpt.com/docs/build-skills) | 官方 Skill 文档；`SKILL.md` + 可选 scripts/references/assets/agents，渐进加载 | 薄入口、资源分层、描述负责发现 | 不把官方示例全文塞入新 Skill；随规范变更复核 | 官方文档事实引用；不复制大段文字 |
| [openai/skills](https://github.com/openai/skills) | Skill 目录案例；仓库声明已废弃并指向 Plugins | Skill 包含指令、脚本、资源的目录思路 | 不以该仓库作为当前规范或依赖；单个 Skill 许可不同 | 逐 Skill 核验；本项目仅参考官方现行文档 |
| [microsoft/ai-agents-for-beginners](https://github.com/microsoft/ai-agents-for-beginners) | 12 课课程仓库、多语言、明确课次 | 短单元、示例/练习/扩展的内容组织 | 不复制课程正文、图像、示例或品牌；不把线性课表移植到所有领域 | MIT；仍坚持原创重写 |
| [freeCodeCamp/freeCodeCamp](https://github.com/freeCodeCamp/freeCodeCamp) | 大型课程与挑战结构、课程清单、自动检查 | 以可验证挑战组织学习、课程结构数据化 | V1 不建设完整在线学习平台；课程文本和题目不复制 | 主仓 BSD-3-Clause；独立扩展课程可能是 CC-BY-SA，需逐项复核 |
| [exercism/python](https://github.com/exercism/python) | 概念目录、练习、参考实现与测试分离 | 任务与验证分离、按能力点给反馈、练习自包含 | 不复制练习、测试、canonical data 或反馈话术；不把所有领域变成代码题 | MIT（Python track）；组织内各仓许可证并不一致 |
| [Aider](https://github.com/Aider-AI/aider) | 终端配对编程、阅读证据—小修改—运行验证 | 最小修改、先证据后结论、运行验证循环 | V1 不是代码代理；不得复制实现/提示词或把代码验证外推到所有领域 | Apache-2.0；本项目只重新实现抽象反馈循环 |
| [langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) | 有状态 Agent；检查点与长期存储概念 | 线程状态和跨线程偏好分离、持久化/恢复/故障考虑 | 不引入该框架或数据库；自行实现本地事件账本 | MIT；仅借鉴架构概念 |
| [openedx/openedx-platform](https://github.com/openedx/openedx-platform) | LMS/CMS、内容与学习交付系统分层 | 内容与学习状态分离、扩展边界意识 | 体量与产品目标不匹配；不引入 LMS、服务端或其代码 | AGPL-3.0；禁止复制/链接其实现，理念级参考即可 |
| [ankitects/anki](https://github.com/ankitects/anki) | 间隔复习产品 | 到期复习提示与长期记忆价值 | 不复制算法、UI、Logo、文档；V1 不实现完整卡片系统 | AGPL-3.0+；严格仅采纳“需要复习项”这一常识性产品需求 |
| [Open edX demo course](https://github.com/openedx/openedx-demo-course) | 可导入示例课程/内容库 | 内容与平台可分离的提醒 | 不复制课程、题目、素材或结构 JSON | CC BY-NC-SA 3.0 US；不纳入实现 |

## 选型结果

### 直接作为当前工程规范的来源

- OpenAI 官方 Build skills、Subagents、Memories 文档：定义 Skill 发现、资源结构、项目 Agent 与平台记忆的实际边界。

### 只借鉴机制、并自主实现的案例

- Microsoft：课程单元中“讲解—动手—验收—扩展”的组织感。
- Exercism：任务、参考、验证、反馈的边界清晰，而不是只生成教程。
- Aider：先读取可用证据，提出最小下一步，执行后验证。
- LangGraph：短期会话状态与长期偏好分离、可恢复性优先。
- Open edX：内容资产与学习记录要分离，但不承担 LMS 的范围。
- Anki：到期复习项应是状态的一部分，而非每次强制背卡。

### 明确不引入的范式

1. 复杂 LMS / 账号 / 云后端 / 课程作者后台；这会吞没 V1 的学习导师核心。
2. 以题库或选择题作为唯一能力证据；真实任务、解释、修改和迁移应共同判断。
3. 复制开源课程或测试集再改名；即使许可宽松，也会失去跨领域与用户实际场景的适配。
4. 把 AGPL/CC BY-NC-SA/CC BY-SA 内容混入项目后再不加条件分发。
5. 依赖废弃 `openai/skills` 仓库的安装说明；以当前官方文档和本机可用 Skill Creator 为准。

## 案例覆盖度审查

| 计划要求的调研类型 | 覆盖案例 | 是否足够用于 V1 |
|---|---|---|
| 渐进式课程与练习 | Microsoft、freeCodeCamp、Exercism | 是；仅借鉴结构 |
| 项目/挑战学习平台 | freeCodeCamp、Exercism、Open edX | 是；明确不建 LMS |
| 自适应/复习/知识状态 | Anki、LangGraph | 是；只取到期项与持久化原则 |
| Agent Skill/子 Agent/评估 | OpenAI 官方、openai/skills、LangGraph、Aider | 是；官方资料优先 |
| 跨领域差异 | 工程（Aider）、编程（Exercism/fCC）、平台（Open edX）、复习（Anki） | 部分；V1 由八适配器和双示范验证，不靠案例复制 |

## 采用前检查清单

每一项未来想从 GitHub 借鉴的内容都要先回答：

1. 这是否是机制思想而非可受版权保护的具体表达、代码、题目或素材？
2. 所在文件/仓库许可证是否明确，是否有附加内容许可？
3. 是否真的服务于 R01–R21 中某条要求？
4. 能否用更小的原创实现达到同一目的？
5. 是否会带来全局安装、云依赖、账号、LMS 或旧 STM32 耦合？

任一项不清楚，默认不引入，记录到 `rejected-patterns.md` 或许可证账本。

## 证据与许可证

完整 URL、访问日期与支持结论见 [`source-ledger.json`](source-ledger.json)。许可证细节与项目处理策略见 [`license-ledger.json`](license-ledger.json)。具体采用理由和原创重建边界见 [`borrowing-log.md`](borrowing-log.md)。
