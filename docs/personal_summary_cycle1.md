# 第一周期（4.23-4.25）

## 一、核心产出 （必填）

本周期我最满意的成果，是把 `CUA-Lark` 从一个空仓库直接落成了一个可运行的 GUI 智能体测试框架雏形。

这次不是只做了架构图或方案文档，而是把核心闭环真正接起来了：`TestCase/StepPlan/Observation/ActionProposal/VerificationResult/TraceEvent` 这些结构化模型先定下来，再把 `Orchestrator + Planner + Perception + Grounding + Executor + Verifier + Recovery + Reporter` 串成一个真实可运行的工作流。最后又补上了 CLI、示例用例、报告生成、dry-run/mock 测试和文档，让它具备后续继续往飞书真实场景推进的基础。

我自己比较认可的一点，是这版框架没有停在“能跑通 happy path”的层面，而是提前把几个关键工程问题处理掉了：

- 支持 `dry-run`，开发和测试时不会真的乱点桌面。
- VLM 输出强制走 JSON，对解析失败、低置信度和高风险动作都有兜底。
- 报告不是口头说明，而是能直接产出 `report.json / report.md / report.html`。
- 第三方网关 `https://api.chattoken.cc/` 根路径实际返回的是 HTML 门户页，代码里已经补了自动回退到 `/v1` 的兼容逻辑。

## 二、量化指标 （必填）

- 本周期新增核心代码与文档共 `34` 个文件，首个主提交代码统计为 `1914` 行新增。
- 已实现 `8` 个核心角色/模块：`Orchestrator`、`Planner`、`Perception`、`Grounding`、`Executor`、`Verifier`、`Recovery`、`Reporter`。
- 已提供 `4` 个 YAML 用例文件，其中包含 `3` 个飞书子产品场景和 `1` 个 smoke suite。
- 已提供 `4` 个 CLI 入口：`doctor`、`run`、`run-suite`、`report`。
- 已编写并跑通 `13` 个测试用例，当前测试结果为 `13 passed`。
- 已完成 `1` 次真实 VLM 网关联通验证，确认 `gpt-4o` 可通过 `api.chattoken.cc` 使用，且代码已兼容 `/v1` 回退。
- Git 侧本周期实际形成 `2` 次提交：一次框架主提交，一次个人小结提交。

## 三、过程复盘与沉淀（必填）

### 1. 这周主要搞定了哪些具体环节？用了什么方法或工具辅助？

这周主要把下面几个环节从 0 到 1 接起来了：

- 先把仓库从空目录接到远端 Git 仓库，并切出开发分支开展实现。
- 用 Python 在 conda `base` 环境中搭好了项目结构，统一了依赖、配置、CLI、测试和文档入口。
- 用结构化 schema 先约束智能体之间的数据接口，避免后面一边写一边漂。
- 用多智能体拆分职责：规划、感知、定位、执行、验证、恢复、报告各自做一件事，由 `Orchestrator` 统一编排。
- 用 `PyAutoGUI` 封装了桌面动作执行层；中文输入采用剪贴板粘贴并恢复原剪贴板，减少输入不稳定。
- 用 OpenAI-compatible SDK 接 VLM，并要求模型只返回 JSON；同时为第三方网关补了兼容处理。
- 用 `Typer` 做 CLI，用 `pytest` 做单元和 mock 集成测试，用 `Jinja2` 生成 Markdown/HTML 报告。
- 用国内源安装依赖，统一到清华源，保证环境安装路径明确可复现。

AI 在这次开发里主要承担了方案梳理、模块拆分、接口约束和代码快速搭建的工作；我自己重点放在工程边界、执行安全、异常兼容和最终落地验证上。

### 2. 过程中有没有遇到什么特别不顺、卡住很久的情况？后来是怎么破局的？

有两个坑比较典型。

第一个坑是 Windows 沙箱环境下，`pytest` 的临时目录会出现“目录创建后不可枚举/不可清理”的权限问题，导致测试主体虽然通过，但 session finish 阶段报错。后来的处理方式不是继续跟 pytest 的临时目录死磕，而是把测试里依赖 `tmp_path` 的部分改成仓库内可控的 `test_artifacts/` 目录，直接绕开这个环境坑。

第二个坑是第三方 VLM 网关看起来是 OpenAI-compatible，但根路径 `https://api.chattoken.cc/` 实际返回的是 HTML 门户页，不是 Chat Completions JSON。最开始 `doctor --check-vlm` 就因为这个直接炸掉。后面我做了两步修正：

- 先把响应解析层写得更稳，能识别 SDK 对象、字典和字符串三种返回形态。
- 再加自动回退逻辑：先试用户给的 `base_url`，如果拿到 HTML 或明显非 API 响应，就自动尝试 `base_url + /v1`。

这个坑补完之后，真实 `gpt-4o` 健康检查已经可以成功返回 JSON。

### 3. 有没有什么你觉得这次写得特别顺，或者下次还能直接复用的东西？

这次最值得复用的有三块。

- 一个是“先定 schema，再写智能体”的做法。`TestCase / StepPlan / Observation / ActionProposal / VerificationResult / TraceEvent` 先稳定下来后，后面加模块时边界很清楚。
- 一个是 `dry-run + replay/mock + real VLM check` 这三层验证方式。开发时先不碰真实桌面，最后再补真实链路校验，节奏比较稳。
- 还有一个是针对第三方 OpenAI-compatible 网关的兼容套路：不要默认它真兼容，先检查根路径返回值形态，再决定是否自动补 `/v1`。

这三套东西下个周期扩到真实飞书桌面自动化时，可以直接继续用。

## 四、本周随手记（选填）

- 空仓库起步时，最容易高估“先跑起来再说”的效率，但 GUI agent 这种东西如果不先把动作 schema 和状态流定住，后面会一直返工。
- 中文 GUI 输入真的不能偷懒走逐字符键盘输入，剪贴板粘贴稳定很多。
- `dry-run` 对桌面自动化项目非常重要，没有它，开发过程会变成一边写一边赌鼠标别乱飞。
- 第三方模型网关的“兼容 OpenAI”很多时候只是营销层面的兼容，真正接 SDK 还是要做防御式处理。
