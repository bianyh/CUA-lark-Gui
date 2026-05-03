# CUA-Lark-Gui 系统架构设计

## 目标

本项目面向飞书桌面客户端构建 Windows-first Computer-Use Agent 测试框架。框架以自然语言测试用例为入口，通过截图感知、视觉模型规划、系统级 GUI 执行、状态验证和结构化报告，完成可复现的飞书端到端自动化测试。

## 分层架构

| 层级 | 职责 | 当前实现 |
| --- | --- | --- |
| 视觉感知层 | 采集飞书窗口截图，生成观察对象，融合可选 OCR、窗口状态和截图稳定性信号 | `perception/screenshot.py`、`perception/ocr.py`、`perception/state.py` |
| 规划决策层 | 根据自然语言任务、当前截图、历史动作、规划提示和失败反思，只决定下一步动作 | `planning/hybrid.py`、`providers/openai_compatible.py`、`providers/mock.py` |
| 执行操作层 | 将模型输出的窗口内坐标和动作转换为真实桌面鼠标/键盘操作 | `executors/windows.py`、`executors/mock.py` |
| 状态验证层 | 校验步骤提示、最终断言、视觉语义结果、图像差异和任务进度 | `validators/engine.py`、`providers/*` |
| 评估报告层 | 汇总步骤轨迹、截图时间线、指标、最终校验和失败原因 | `reporter.py`、`reports/generated/<task>/<run_id>/` |
| 用例管理层 | 加载自然语言 YAML/JSON 用例，保留前置条件、断言、标签和可选动作提示 | `cases/`、`cases/loader.py` |

## 核心循环

1. 聚焦飞书窗口，并截取目标窗口区域。
2. 生成 `Observation`，包含截图路径、窗口尺寸、OCR 文本、运行状态和 UI hints。
3. `StateAnalyzer` 判断页面是否仍在加载、是否出现弹窗/异常、截图是否稳定。
4. `HybridPlanner` 调用视觉策略生成下一步动作；在真实模型模式下，`metadata.scripted_actions` 只作为提示，不作为固定计划。
5. `WindowsDesktopExecutor` 执行动作，并把窗口内坐标转换为真实屏幕坐标。
6. 再次截图并进行步骤校验、任务进度评估。
7. 如果动作失败、页面停滞或加载超时，调用反思模块分析原因，必要时执行恢复动作并动态重规划。
8. 任务结束后执行最终断言，写出 `run.json`、`report.md` 和截图 timeline。

## 关键数据模型

| 模型 | 作用 |
| --- | --- |
| `TaskSpec` | 归一化测试用例，包含产品、自然语言指令、前置条件、断言、清理动作和元数据 |
| `Observation` | 单次 UI 观察结果，包含截图、OCR blocks、窗口标题、屏幕尺寸、状态评估和 UI hints |
| `ActionStep` | 标准 GUI 动作协议，支持点击、双击、右键、拖拽、滚动、文本输入、快捷键、等待、断言和空操作 |
| `PolicyDecision` | 规划器返回的下一步决策，包含是否结束、动作、理由和重规划原因 |
| `ProgressAssessment` | 模型对任务完成度的评估，包含成功标记、完成分、证据和未完成目标 |
| `ReflectionResult` | 失败后的反思结果，包含根因、失败阶段、恢复策略和可选恢复动作 |
| `RunReport` | 一次测试运行的完整结构化结果 |

## 模型集成

默认模型配置：

- `OPENAI_BASE_URL=https://api.chattoken.cc/v1`
- `OPENAI_MODEL=gpt-4o`
- `OPENAI_API_KEY` 从环境变量或本地 `.env.local` 读取，不进入 Git。

调用策略：

- 优先使用 `responses.create` 发送截图和文本提示。
- 如果接口不兼容，自动回退到 `chat.completions.create`。
- 截图会按配置压缩，避免多模态请求体过大。
- 模型输出必须是 JSON，动作字段会被 `ActionStep.from_dict()` 归一化。

规划提示明确约束模型：

- 每次只规划下一步，不输出一次性的固定完整计划。
- 坐标必须相对当前截图/窗口图像，而不是绝对桌面坐标。
- `scripted_actions` 是可跳过、可修改的提示，不是强制剧本。
- 如果最近动作没有带来进展，应避免重复同一点击坐标。
- 对中文和混合文本输入优先使用 `type_text`，由执行器走剪贴板粘贴。

## Windows 执行

真实桌面执行依赖：

- `pyautogui`: 鼠标、键盘、滚动、拖拽和快捷键。
- `pygetwindow`: 查找并聚焦飞书窗口，获取窗口区域。
- `pyperclip`: 中文文本通过剪贴板粘贴，避免键盘逐字符输入失败。

支持动作：

- `click`
- `double_click`
- `right_click`
- `drag`
- `scroll`
- `type_text`
- `hotkey`
- `wait`
- `assert`
- `noop`

坐标执行方式：

- 模型输出 `coordinates: [x, y]` 或 `x/y`。
- 坐标按截图窗口内位置解析。
- 执行器根据飞书窗口左上角偏移转换成屏幕绝对坐标。
- 如果 `type_text` 没有坐标，执行器默认点击飞书窗口下方偏右的输入区域，再粘贴文本。

## 感知与 OCR

当前默认配置是 `CUA_OCR_BACKEND=none`。原因是本项目主路径已经由视觉模型直接理解截图，且 PaddleOCR 在部分 Windows conda 环境中容易遇到二进制依赖或数组格式差异问题。

OCR 仍作为可选增强：

- 设置 `CUA_OCR_BACKEND=paddleocr` 可启用 PaddleOCR。
- `paddleocr_diagnostics()` 用于诊断包是否可导入。
- OCR 提取异常会被 runner 捕获，运行不会因 OCR 失败而崩溃。
- 状态验证会综合 OCR 文本、模型语义判断、动作提示和历史输入。

## 用例覆盖

当前内置自然语言用例覆盖：

- IM: 发送文本消息、`@` 提及。
- Calendar: 创建日程、修改日程时间。
- Docs: 创建文档、编辑文档内容。
- Cross-product: IM 日程通知与 Calendar 会议验证联动。

每个 YAML 用例包含：

- `instruction`: 自然语言任务描述，是真实规划的任务源。
- `preconditions`: 环境前置条件。
- `assertions`: OCR/文本、VLM 语义、图像差异等验证规则。
- `metadata.scripted_actions`: 可选规划提示和 mock 模式回放依据。

## 报告契约

每次运行写出：

- `artifacts/<task>/<run_id>/timeline/*.png`
- `reports/generated/<task>/<run_id>/run.json`
- `reports/generated/<task>/<run_id>/report.md`

报告指标包括：

- `step_attempts`
- `step_success_rate`
- `successful_steps`
- `failed_steps`
- `retries`
- `load_wait_rounds`
- `load_timeouts`
- `replans`
- `max_steps`
- `max_retries`

这些文件用于复盘模型决策、真实操作路径、失败根因和最终验收结果。生成目录默认被 `.gitignore` 排除，避免把个人飞书截图、API 运行痕迹或测试数据提交到远程仓库。

## Git 纪律

- 使用 feature branch 管理开发，目前主分支工作集中在 `feat-core-loop`。
- `.env.local`、`artifacts/`、`reports/generated/` 不提交。
- 代码和文档改动按逻辑切片提交。
- 提交信息使用 Conventional Commits。
