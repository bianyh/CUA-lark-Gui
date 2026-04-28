# CUA-Lark GUI 智能体架构设计

## 设计目标

CUA-Lark 面向飞书桌面客户端，使用截图作为主要观测输入，让视觉多模态模型理解 UI 状态，再通过真实鼠标、键盘、滚动和拖拽动作执行测试。结构化辅助信息可以用于定位和验证，但不能替代视觉决策。

Windows 实际执行时，截图和动作都限定在飞书窗口。系统会按 `CUA_LARK_WINDOW_TITLE_PATTERN` 查找飞书窗口，必要时恢复并激活后台窗口，然后只截取飞书窗口区域。模型返回的坐标被视为窗口截图内坐标，执行器会结合 `Observation.screen_bounds` 转换成屏幕绝对坐标。

## 多智能体协作

系统采用中心调度器加专业智能体的架构。所有智能体围绕 `TaskContext` 协作，`Orchestrator` 是唯一调度者，其他智能体不直接互相调用。

| 智能体 | 职责 | 输入 | 输出 |
| --- | --- | --- | --- |
| Orchestrator | 组织 observe-plan-ground-act-verify-recover 主循环 | TestCase | TaskContext |
| TestPlannerAgent | 把自然语言用例拆成步骤 | TestCase | StepPlan 列表 |
| PerceptionAgent | 截图、页面理解、候选元素识别 | run_dir | Observation |
| GroundingAgent | 把语义目标映射为一个 GUI 动作 | StepPlan + Observation | ActionProposal |
| ActionExecutor | 执行鼠标、键盘、滚动、等待等动作 | ActionProposal | ExecutionResult |
| VerifierAgent | 判断执行后状态是否满足成功条件 | StepPlan + Observation | VerificationResult |
| RecoveryAgent | 在失败或低置信度时给出恢复动作 | StepPlan + Observation + VerificationResult | ActionProposal |
| ReportAgent | 生成 JSON、Markdown 和 HTML 报告 | TaskContext | 报告文件 |

## 执行流程

1. CLI 读取 YAML 用例，构造 `TestCase`。
2. `Orchestrator` 创建运行目录并调用 `TestPlannerAgent` 获取步骤。
3. 每个步骤先由 `PerceptionAgent` 截图并识别页面摘要、候选元素和弹窗。
4. `GroundingAgent` 基于截图和步骤目标输出一个结构化动作。
5. `ActionExecutor` 校验坐标和风险后执行动作；中文输入使用剪贴板粘贴并恢复原剪贴板。
6. `PerceptionAgent` 再次截图，`VerifierAgent` 判断步骤是否成功。
7. 失败时 `RecoveryAgent` 尝试等待、关闭弹窗、返回、搜索入口或重新定位。
8. 全部步骤结束后，`ReportAgent` 汇总轨迹、截图、成功率和失败原因。

## 关键数据结构

核心 schema 位于 `src/cua_lark/models.py`：

- `TestCase`：用例 ID、产品线、自然语言指令、测试数据、期望结果、风险等级和步骤。
- `StepPlan`：步骤目标、成功条件、允许动作、最大重试次数和确认要求。
- `Observation`：截图路径、窗口范围、缩放因子、页面摘要、候选 UI 和弹窗。
- `Observation.screen_bounds`：飞书窗口在屏幕上的绝对位置，用于把窗口内坐标映射回真实点击坐标。
- `ActionProposal`：动作类型、目标、坐标、文本、快捷键、置信度、理由和期望状态。
- `VerificationResult`：是否通过、置信度、证据、失败类型和建议动作。
- `TraceEvent`：单步执行轨迹，绑定观察、动作、执行结果、验证结果和耗时。

## VLM 接口

VLM 使用 OpenAI-compatible Chat Completions 接口：

- `OPENAI_BASE_URL=https://api.chattoken.cc/`
- `OPENAI_MODEL=gpt-4o`
- `OPENAI_API_KEY` 只保存在本地 `.env`

模型所有关键输出都要求为 JSON 对象。解析失败、字段缺失、坐标越界或动作置信度低于阈值时，不执行高风险点击，而是进入恢复或重新观测。

## 安全边界

- 默认只针对飞书测试账号、测试群、测试文档空间和测试日历运行。
- 高风险动作默认阻塞，需要人工确认。
- `.env`、运行截图、录屏、报告和真实账号数据均不进入 Git。
- Mock 和 dry-run 模式用于开发与单元测试，避免自动移动鼠标键盘。
