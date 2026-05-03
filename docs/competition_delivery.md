# 竞赛交付说明

本文对应飞书 AI 产品创新赛 CUA 测试框架要求的 3.1-3.4，说明当前仓库的实现范围、模块映射、运行证据和后续风险。

## 3.1 系统架构设计

### 架构总览

系统采用 `observe -> plan -> execute -> validate -> report` 闭环架构。每一轮只基于当前飞书截图和历史轨迹规划下一步动作，而不是预先生成一份固定计划后照单执行。

| 必需模块 | 职责 | 项目实现 | 技术方式 |
| --- | --- | --- | --- |
| 视觉感知层 | 屏幕截图采集、UI 状态识别、可选 OCR 文本抽取 | `Screenshotter`、`NullOCRProvider`、`PaddleOCRProvider`、`StateAnalyzer` | Pillow `ImageGrab`、窗口区域截图、VLM、可选 PaddleOCR、截图相似度 |
| 规划决策层 | 将自然语言指令动态拆解为下一步动作 | `HybridPlanner`、`OpenAICompatibleVisionPolicy`、`MockVisionPolicy` | OpenAI-compatible VLM、历史动作、规划提示、失败反思、progress assessment |
| 执行操作层 | 模拟鼠标、键盘等人机交互操作 | `WindowsDesktopExecutor`、`MockDesktopExecutor` | PyAutoGUI、PyGetWindow、Pyperclip、窗口坐标到屏幕坐标映射 |
| 状态验证层 | 执行后判断步骤和任务是否成功 | `CompositeValidator`、`validate_hint`、`validate_task`、VLM semantic validation | 文本检索、VLM 语义判断、图像 diff、进度评分 |
| 评估报告层 | 汇总测试结果，生成可复盘报告 | `ReportWriter`、`RunReport` | `run.json`、`report.md`、timeline 截图、核心指标统计 |

### 模块到文件映射

| 模块 | 文件 |
| --- | --- |
| 用例加载 | `src/cua_lark/cases/loader.py` |
| 配置与环境 | `src/cua_lark/config.py`、`.env.example` |
| 数据模型 | `src/cua_lark/models.py` |
| 截图/OCR/状态 | `src/cua_lark/perception/screenshot.py`、`src/cua_lark/perception/ocr.py`、`src/cua_lark/perception/state.py` |
| 规划 | `src/cua_lark/planning/hybrid.py`、`src/cua_lark/providers/openai_compatible.py` |
| 执行 | `src/cua_lark/executors/windows.py`、`src/cua_lark/executors/mock.py` |
| 验证 | `src/cua_lark/validators/engine.py` |
| 编排 | `src/cua_lark/runner.py` |
| 报告 | `src/cua_lark/reporter.py` |
| CLI | `src/cua_lark/cli.py` |

### 动态规划机制

本项目已修正早期“预设计划一次性执行”的问题。现在真实模型模式下的执行逻辑是：

1. 每轮先截取当前飞书窗口。
2. 将自然语言任务、最新截图、最近动作、剩余步数、可选提示和失败反思交给模型。
3. 模型只返回下一步动作。
4. 执行后重新截图和评估进度。
5. 如果进展停滞或校验失败，反思模块生成根因和新策略，下一轮重新规划。

`metadata.scripted_actions` 在真实模型模式中只作为 hints 传入模型。模型可以跳过、重排或替换它们；只有 mock 模式会优先使用这些提示来保证 CI 和本地无飞书环境可复现。

## 3.2 核心功能实现

### A. 基础操作能力

`ActionStep` 和 `WindowsDesktopExecutor` 已支持下列基础 GUI 操作：

| 操作 | 状态 | 说明 |
| --- | --- | --- |
| 单击 | 已实现 | `click`，支持模型输出截图内坐标 |
| 双击 | 已实现 | `double_click` |
| 右键 | 已实现 | `right_click` |
| 拖拽 | 已实现 | `drag`，起点来自 `coordinates`，终点来自 `metadata.to_coordinates` |
| 滚动 | 已实现 | `scroll` |
| 文本输入 | 已实现 | `type_text`，优先使用剪贴板粘贴，适配中文输入 |
| 快捷键组合 | 已实现 | `hotkey`，支持 `ctrl+k`、`enter` 等 |
| 等待 | 已实现 | `wait` |
| 断言/空操作 | 已实现 | `assert`、`noop` |

执行器会将模型输出的窗口内坐标转换为真实屏幕坐标，因此模型可以直接输出页面中要点击的位置。例如：

```json
{
  "done": false,
  "rationale": "点击搜索结果中的测试群。",
  "action": {
    "action_type": "click",
    "description": "进入测试群",
    "coordinates": [265, 368]
  }
}
```

### 多步骤复合操作

`AgentRunner.run_task()` 串联完成：

1. 聚焦飞书窗口。
2. 初始观察。
3. 动态规划下一步。
4. 执行桌面动作。
5. 稳定等待和二次观察。
6. 步骤校验。
7. 进度评估。
8. 失败反思和重规划。
9. 最终断言。
10. 输出报告。

已经通过真实飞书界面调试的 IM 样例链路为：

```text
hotkey(ctrl+k) -> click(搜索结果) -> type_text(Hello World) -> hotkey(enter)
```

本地真实运行报告示例：

- `reports/generated/im_send_message/20260503-101011/report.md`
- 状态：`success`
- 耗时：`57.42s`
- 步骤数：`4`
- 步骤成功率：`1.0`
- OCR 后端：`none`
- 规划器：`adaptive`
- 执行器：`windows_executor`

### B. 飞书功能覆盖

当前已覆盖 3 个飞书子产品和 1 条跨产品链路：

| 子产品 | 用例 | 场景 |
| --- | --- | --- |
| IM 即时通讯 | `cases/im/send_message.yaml` | 搜索测试群，发送 `Hello World`，确认发送成功 |
| IM 即时通讯 | `cases/im/mention_member.yaml` | 在群聊中发送 `@张三 请查看回归结果` |
| 日历 Calendar | `cases/calendar/create_event.yaml` | 创建“项目周会”，时间为明天下午 2 点，并邀请张三 |
| 日历 Calendar | `cases/calendar/reschedule_event.yaml` | 找到“项目周会”，修改到明天下午 3 点 |
| 云文档 Docs | `cases/docs/create_project_report.yaml` | 创建“项目周报”，输入标题“2026年Q2项目进展” |
| 云文档 Docs | `cases/docs/edit_project_report.yaml` | 打开“项目周报”，追加测试框架调试内容 |
| 跨产品 | `cases/calendar/im_calendar_handoff.yaml` | 从 IM 日程通知切换到 Calendar 验证会议上下文 |

这满足“至少覆盖 2 个子产品”的必做要求，也对齐 M3 推荐的 IM/Calendar/Docs 三个子产品各 2 条用例。

### C. 自然语言驱动测试

用例以 YAML 文件描述，核心入口是自然语言 `instruction`。示例：

```yaml
id: docs_create_project_report
product: docs
instruction: 在飞书云文档中创建一个名为“项目周报”的新文档，并输入标题“2026年Q2项目进展”。
assertions:
  - type: ocr_contains
    expected_text: 项目周报
  - type: vlm_semantic
    expected_text: 已创建项目周报文档并输入标题 2026年Q2项目进展
```

运行方式：

```powershell
python -m cua_lark list-cases
python -m cua_lark run-case --case cases/im/send_message.yaml --mock
python -m cua_lark run-suite --case-dir cases --mock
```

真实飞书桌面运行前需要设置：

```powershell
Copy-Item .env.example .env.local
# 在 .env.local 中设置 OPENAI_API_KEY，并将 CUA_MOCK_MODE=false
python -m cua_lark doctor
python -m cua_lark run-case --case cases/im/send_message.yaml
```

## 3.3 进阶能力

| 进阶能力 | 状态 | 当前实现 |
| --- | --- | --- |
| 异常场景处理 | 已实现基础版 | `StateAnalyzer` 识别加载中、弹窗、错误、超时；runner 在 OCR/执行异常时转为校验失败和反思 |
| 跨产品联动测试 | 已实现用例 | `im_calendar_handoff.yaml` 覆盖 IM 到 Calendar 的上下文验证 |
| 自愈式执行 | 已实现基础版 | `reflect_after_step()` 生成根因、恢复策略和可选恢复动作，runner 根据结果重规划 |
| 测试用例自动生成 | 未实现 | 当前用例仍由人工编写，后续可从飞书功能文档或录屏生成 YAML |
| 混合定位策略 | 已实现基础版 | VLM 坐标定位 + 可选 OCR 文本信号 + 窗口区域坐标映射 + 状态 hints |
| 多轮对话编排 | 已实现 | 每步基于最新 observation/history/progress/reflection 动态更新下一步 |
| 录制回放 | 未实现 | 当前已有结构化轨迹和报告，后续可将 `run.json` 反向导出为可回放脚本 |

## 3.4 渐进式实现路径

| 阶段 | 目标 | 当前状态 | 验收证据 |
| --- | --- | --- | --- |
| M1 · 单步操作 | 截图 -> VLM 识别 -> 单步点击/输入 | 已完成 | Windows executor 支持基础 GUI 动作；模型可输出页面坐标并被执行器点击 |
| M2 · 流程串联 | 多步操作串联 + 状态验证 | 已完成 | IM 发送消息真实运行成功，`20260503-101011` 报告显示 4 步完成 |
| M3 · 多产品覆盖 | 扩展到 3 个以上子产品 | 已完成用例层覆盖，真实跑通以 IM 为主 | IM/Calendar/Docs 各 2 条 YAML 用例；Calendar/Docs 需继续做真实账号夹具调试 |
| M4 · 评估体系 | 输出结构化报告和指标 | 已完成 | `run.json`、`report.md`、timeline 截图、成功率/耗时/重试/重规划指标 |
| M5 · 进阶优化 | 异常处理、自愈、跨产品联动 | 部分完成 | 已有加载等待、超时检测、失败反思、恢复动作、动态重规划、跨产品用例 |

## 当前运行与验证方式

开发验证：

```powershell
python -m pytest
```

Mock 套件验证：

```powershell
python -m cua_lark run-suite --case-dir cases --mock
```

真实飞书验证：

```powershell
python -m cua_lark run-case --case cases/im/send_message.yaml
```

真实运行依赖：

- Windows 桌面环境。
- 飞书客户端已登录。
- 目标窗口标题包含 `飞书`。
- `.env.local` 中配置可用的 `OPENAI_API_KEY`。
- 安装 `python -m pip install -e .[desktop]`。

## 风险与后续工作

- Calendar 和 Docs 的真实运行需要稳定测试账号、联系人和文档权限，当前已提供用例与执行能力，但仍需在目标飞书租户中补足真实夹具。
- 录制回放和测试用例自动生成尚未实现，建议作为后续加分项。
- OCR 默认关闭是有意设计；如果评测环境要求 OCR 参与，可通过配置打开 PaddleOCR，但应先用 `doctor` 验证依赖。
- 当前报告以 Markdown 和 JSON 为主，后续可以在 `run.json` 基础上追加 dashboard。
