# 答辩 PPT 提纲

## 1. 背景与痛点

- 传统 GUI 自动化依赖选择器，飞书 Electron UI 频繁变化时维护成本高。
- CUA 通过视觉理解和真实操作提升泛化能力。

## 2. 系统目标

- 自然语言驱动测试。
- 视觉感知与状态验证。
- 跨飞书子产品执行测试。
- 自动生成评测报告。

## 3. 架构设计

- Orchestrator + Planner + Perception + Grounding + Executor + Verifier + Recovery + Reporter。
- 共享 `TaskContext` 与结构化动作 schema。

## 4. 关键实现

- OpenAI-compatible `gpt-4o` VLM 接口。
- 截图和坐标 grounding。
- PyAutoGUI 动作执行。
- dry-run/mock 测试模式。
- JSON/Markdown/HTML 报告。

## 5. 测试覆盖

- IM：搜索群并发送消息。
- Docs：创建文档并输入标题。
- Calendar：创建会议并邀请联系人。

## 6. 评测结果

- 展示成功率、耗时、步数、重试次数和失败分类。

## 7. 加分能力与展望

- 异常弹窗处理。
- 自愈式替代路径。
- 跨产品联动测试。
- 录制回放与用例自动生成。
