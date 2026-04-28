# CUA-lark-Gui

CUA-Lark is a Computer-Use Agent testing framework for the Feishu/Lark desktop client. It observes the desktop through screenshots, asks a vision-language model to understand GUI state, executes real mouse/keyboard actions, verifies the result visually, and writes structured test reports.

Runtime capture and actions are scoped to the Feishu/Lark desktop window. On Windows, the runner looks for a window title matching `飞书|Feishu|Lark`, restores and activates that window if it is in the background, captures only that window region, and maps model coordinates from window-local pixels back to screen coordinates for execution.

## Architecture

The runtime is organized as a central orchestrator plus specialized agents:

- `Orchestrator`: runs the observe-plan-ground-act-verify-recover loop.
- `TestPlannerAgent`: converts natural-language test cases into GUI steps.
- `PerceptionAgent`: captures screenshots and asks the VLM for page summaries, UI candidates, and alerts.
- `GroundingAgent`: maps a step goal to exactly one structured GUI action.
- `ActionExecutor`: executes clicks, typing, hotkeys, scrolling, dragging, waiting, and screenshots.
- `VerifierAgent`: checks whether the post-action screenshot satisfies the success criteria.
- `RecoveryAgent`: handles low confidence, popups, loading delays, and failed verifications.
- `ReportAgent`: writes JSON, Markdown, and HTML reports.

All agents communicate through typed models in `src/cua_lark/models.py`. Visual understanding is the primary decision path; OCR, Accessibility Tree, Feishu OpenAPI, and window metadata are reserved as future auxiliary checks.

## Environment

Use the conda base environment as requested:

```powershell
conda activate base
python --version
```

Install dependencies with a China mainland PyPI mirror:

```powershell
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

Backup mirrors:

```powershell
python -m pip install -i https://mirrors.aliyun.com/pypi/simple -r requirements.txt
python -m pip install -i https://mirrors.huaweicloud.com/repository/pypi/simple -r requirements.txt
python -m pip install -i https://pypi.mirrors.ustc.edu.cn/simple -r requirements.txt
```

## VLM Configuration

Copy `.env.example` to `.env` and fill the real key locally:

```powershell
Copy-Item .env.example .env
```

Required values:

```env
OPENAI_BASE_URL=https://api.chattoken.cc/
OPENAI_MODEL=gpt-4o
OPENAI_API_KEY=replace-with-your-api-key
CUA_LARK_WINDOW_TITLE_PATTERN=飞书|Feishu|Lark
```

Do not commit `.env`. The repository intentionally only includes `.env.example`.

## CLI

Run environment checks:

```powershell
python -m cua_lark.cli doctor
```

Optionally check screenshot and VLM access:

```powershell
python -m cua_lark.cli doctor --screenshot
python -m cua_lark.cli doctor --check-vlm
```

`doctor --screenshot` targets the Feishu/Lark window, not the whole desktop. If the window is behind other windows or minimized, the Windows window manager will try to restore and activate it before capture.

Run one case in dry-run mode:

```powershell
python -m cua_lark.cli run cases/im_send_text.yaml --dry-run
```

Run a suite:

```powershell
python -m cua_lark.cli run-suite cases/smoke.yaml --dry-run
```

Generated reports are written to `runs/<run_id>/report.json`, `report.md`, and `report.html`.

## Real Feishu E2E

Before running without `--dry-run`, confirm:

- Feishu desktop is installed and logged in with a test account.
- Test group, test document workspace, test calendar, and test attendee are safe to modify.
- The desktop allows screenshot, mouse, keyboard, and clipboard automation.
- No real production chats, documents, calendars, or contacts are targeted.

The executor validates coordinates against the Feishu window screenshot bounds, then converts them to absolute screen coordinates by adding the Feishu window origin. Real runs print progress for case start, planning, each step, observations, proposed actions, execution results, verification, recovery, and final report location.

## Test Cases

Initial standard cases:

- `cases/im_send_text.yaml`: search a test group and send a unique text message.
- `cases/docs_create_document.yaml`: create a document and enter a project title.
- `cases/calendar_create_event.yaml`: create a meeting and invite a test attendee.
- `cases/smoke.yaml`: suite covering IM, Docs, and Calendar.

## Tests

Run unit and mock integration tests:

```powershell
python -m pytest
```

These tests do not move the mouse or keyboard. They use dry-run execution and generated local images.

## Git Workflow

The implementation branch is `feature-cua-lark-agent`. Recommended milestones:

1. Scaffold and environment docs.
2. VLM interface and schema validation.
3. GUI executor and screenshot perception.
4. Multi-agent orchestration.
5. Feishu standard cases.
6. Report generation and evaluation docs.

Commit after each tested milestone. Keep `.env`, `runs/`, screenshots, recordings, and local reports out of Git.
