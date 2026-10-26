# 项目 Agent 协作约定

## 开始工作

1. 读取 `IMPLEMENTATION_PLAN.md` 和本文件。
2. 涉及学习会话时，先只读运行 `state_tool.py --state-dir Learner_State status`；若尚未初始化，再运行 `init`。
3. 读取 `.agents/skills/real-world-learning-mentor/SKILL.md`，只按当前任务加载相关 reference。
4. 新领域、快速变化或高风险事实先查一手来源并记录访问时间、版本和适用边界。

## 不变量

- 这是独立通用 Skill；不得修改、复制或导入相邻的 `STM32学习skill项目`。
- 主 Agent 是 `Learner_State/` 的唯一写入者；子 Agent 只读并返回结构化建议。
- 学习成果必须有证据和验证等级；用户自述保留为 `user-reported`。
- 每轮最多一个核心问题；默认一个任务、1–2 个概念、一个检查点和一个失败分支。
- 前台最多 1 个主方法 + 2 个辅助方法；十方法后台审查不逐项表演。
- 安全、准确、新鲜度、权限和适用边界高于极简、速度和趣味。
- 不保存原始聊天、密钥、敏感个人信息或不必要的原文件。

## 子 Agent 路由

- `learning_architect`：MVC、任务阶梯和复杂跨领域路线；
- `domain_researcher`：当前事实、工具、案例、来源和许可证；
- `learning_assessor`：准备度、证据、掌握度和迁移；
- `state_integrity`：事件账本、冲突、恢复和隐私；
- `adversarial_reviewer`：高风险、昂贵、反复失败或方法论失真。

简单课堂直接完成。并行任务必须文件所有权不重叠；由主 Agent 整合。

## 状态写入

所有写命令都携带 `expected_revision` 和稳定的 `idempotency_key`。出现冲突、事件缺口、哈希断链或派生状态不一致时停止写入，先运行 `validate`/`rebuild`。恢复摘要不超过 6 行，然后给出唯一下一动作。

## 完成前

- 运行 `python -m pytest -q`；
- 运行官方 `quick_validate.py`；
- 执行行为盲测和硬失败审查；
- 重算旧 STM32 全树指纹并与 `docs/evaluation/old_stm32_baseline.json` 比较；
- 不以“测试没报错”替代逐项需求审计。
