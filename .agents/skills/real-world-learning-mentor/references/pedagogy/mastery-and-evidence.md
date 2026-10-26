# 掌握度、MVC 与证据

## MVC

MVC 是最小可验证能力，不是最小阅读量。合格 MVC 必须有真实或近真实结果、可提交证据、关键逻辑解释、一个小修改、失败分支和停止条件。

## 任务阶梯

```text
Taste 体验 -> Follow 跟做 -> Understand 理解 -> Modify 修改
-> Diagnose 排错 -> Transfer 迁移 -> Capstone 综合作品
```

升级依据是证据，不是用户自信或导师感觉。

## 掌握度

```text
Seen 见过 -> Understood 理解 -> Applied 应用 -> Modified 修改
-> Diagnosed 排错 -> Transferred 迁移
```

约束：

- 听懂或读懂只能到 `Understood`。
- 按步骤复现最多到 `Applied`。
- 修改条件且结果合理，才到 `Modified`。
- 能解释错误原因并修正，才到 `Diagnosed`。
- 迁移必须改变场景、材料、工具、受众或限制，并且提示明显减少。

## 证据验证等级

- `user-reported`：用户描述结果，但导师无法直接核验。
- `documented`：有可追溯文档、记录或来源支持。
- `artifact-observed`：导师实际读取了文件、图片、日志、数据或其他产物。
- `compile-verified`：代码通过指定构建环境的编译检查。
- `logic-verified`：逻辑、测试或静态检查通过，但未证明现实环境运行。
- `simulation-verified`：只在沙盒、模拟器、样例数据或练习环境验证。
- `hardware-verified`：有足以支持实板/实物现象的可核验证据。
- `externally-verified`：有第三方、真实受众或外部系统的可核验反馈。

没有证据时不创建证据记录。禁止把 `user-reported`、编译、逻辑或模拟结果写成更高层级的现实验证。

## 回退

连续两次同类错误时，只回退薄弱点，不重启整门课；同时重评方法组合。
