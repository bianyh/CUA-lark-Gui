# 评测方案

## 指标

- 用例成功率：通过用例数 / 总用例数。
- 步骤成功率：通过步骤数 / 总步骤数。
- 平均耗时：每条用例从开始到结束的平均耗时。
- 平均步数：每条用例执行的 trace 数。
- 重试次数：RecoveryAgent 介入次数。
- 失败分类：低置信度、坐标越界、验证失败、加载超时、需要人工确认、VLM 输出非法。

## 标准用例

首版 smoke suite 覆盖三个飞书子产品：

1. IM：搜索测试群并发送唯一文本消息。
2. Docs：创建新文档并输入标题。
3. Calendar：创建明天下午 2 点会议并邀请测试联系人。

## 执行方式

开发阶段先运行 mock/dry-run：

```powershell
python -m pytest
cua-lark run cases/im_send_text.yaml --dry-run
```

真实 E2E 运行前需要确认：

- 飞书桌面客户端已安装并登录测试账号。
- 测试群、测试联系人、测试文档空间已经准备好。
- `.env` 已配置 VLM 接口。
- 当前桌面环境允许截图、鼠标和键盘自动化。

## 报告产物

每次运行生成 `runs/<run_id>/`：

- `screenshots/`：动作前后截图。
- `report.json`：完整结构化轨迹。
- `report.md`：可读评测报告。
- `report.html`：展示用 HTML 报告。
