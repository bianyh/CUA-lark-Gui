# CUA-Lark-Gui

Vision-first GUI testing agent for the Feishu desktop client, built for the Feishu AI Product Innovation Competition.

## What This Repository Contains

- A modular CUA runtime with `observe -> plan -> execute -> validate -> report`.
- An OpenAI-compatible vision policy adapter with `responses` first and `chat.completions` fallback.
- Optional Windows desktop automation integrations for screenshot capture, OCR, and mouse/keyboard control.
- Structured Feishu test case definitions for IM, Calendar, Docs, and cross-product MVP scenarios.
- A reporting pipeline that emits `run.json`, `report.md`, and a screenshot timeline per run.
- A progress assessment and reflection loop that estimates completion, identifies failure stages, and suggests safe recovery actions.

## Tech Decisions

- Platform focus: Windows first, architecture prepared for future macOS support.
- Modeling: `gpt-4o` via `https://api.chattoken.cc/v1`.
- Primary runtime: Python in the existing conda `base` environment.
- Secret handling: API keys are read from environment variables or `.env.local`, never committed.

## Quickstart

1. Activate the existing conda base environment.

```powershell
conda activate base
```

2. Install the package in editable mode.

```powershell
python -m pip install -e .
python -m pip install -e .[desktop]
```

3. Create a local config file from the template.

```powershell
Copy-Item .env.example .env.local
```

4. Set `OPENAI_API_KEY` in `.env.local` or export it in your shell.

5. Run environment diagnostics.

```powershell
python -m cua_lark doctor
```

6. List bundled cases.

```powershell
python -m cua_lark list-cases
```

7. Run a case in mock mode.

```powershell
python -m cua_lark run-case --case cases/im/send_message.yaml --mock
```

8. Run a suite against all bundled cases.

```powershell
python -m cua_lark run-suite --case-dir cases --mock
```

## Repository Layout

```text
cases/                  Structured IM / Calendar / Docs / cross-product cases
docs/                   Design and competition-facing documentation
src/cua_lark/           Core runtime, providers, execution, validation, reporting
tests/                  Lightweight unit tests for the core loop
.github/workflows/      CI checks
```

## Runtime Modes

- `--mock`: Uses synthetic screenshots and a mock executor. This is the safe default for CI and architecture validation.
- Desktop mode: Requires Windows, Feishu desktop client, `pyautogui`, `pygetwindow`, and `pyperclip`.
- OCR is optional. The current default is no OCR because the vision model can read the screenshot directly and PaddleOCR may be unstable in some Windows conda environments.

## Runtime Logs

- The CLI now prints Chinese runtime status messages for observation, planning, execution, validation, retries, and report generation.
- The runtime also prints progress assessment, reflection output, and recovery actions after each stable step.
- Control it with `CUA_RUNTIME_LOGS=true|false`.
- Control preview length with `CUA_RUNTIME_PREVIEW_CHARS=80`.
- This is useful when you want to watch model decisions, fallback behavior, and workflow progress in real time while testing Feishu.

## OCR Backend

- The project uses `CUA_OCR_BACKEND=none` by default. In this mode the runner sends screenshots to the vision policy and does not require OCR to operate.
- PaddleOCR remains available as an optional text-signal source. Enable it with `CUA_OCR_BACKEND=paddleocr` and `CUA_PADDLE_OCR_LANG=ch`.
- Use `python -m cua_lark doctor` to confirm whether PaddleOCR is importable in the current environment.
- If PaddleOCR raises dependency or NumPy-related errors, the runner catches OCR extraction failures and continues with the vision-only observation path.

## Competition Coverage

The current implementation maps directly to the required competition sections:

- `3.1 系统架构设计`: `docs/design.md` describes the layered `observe -> plan -> execute -> validate -> report` architecture and module boundaries.
- `3.2 核心功能实现`: the Windows executor supports click, double-click, right-click, drag, scroll, text input, hotkeys, wait/assert/noop, and multi-step Feishu workflows driven by YAML natural-language cases.
- `3.3 进阶能力`: implemented adaptive replanning, reflection-based recovery, load/timeout handling, optional OCR/VLM mixed perception, cross-product IM + Calendar flow, and structured run reports.
- `3.4 渐进式实现路径`: `docs/competition_delivery.md` records M1-M5 status, acceptance evidence, and remaining risks.

Bundled cases currently cover:

- IM: `cases/im/send_message.yaml`, `cases/im/mention_member.yaml`
- Calendar: `cases/calendar/create_event.yaml`, `cases/calendar/reschedule_event.yaml`
- Docs: `cases/docs/create_project_report.yaml`, `cases/docs/edit_project_report.yaml`
- Cross-product: `cases/calendar/im_calendar_handoff.yaml`

## Git Workflow

- `main` should remain demoable.
- Current implementation branch: `feat-core-loop`.
- Use Conventional Commits for new work, for example `feat: add calendar reschedule case`.
- Commit logical slices: scaffolding, planner changes, new product cases, report improvements.

## Current MVP Scope

- IM: search conversation, send text, `@` mention, verify text appears.
- Calendar: create event, reschedule event, verify time or attendee appears.
- Docs: create a document, edit text content, verify document title/content appears.
- Cross-product: IM receives calendar-related context and the runner validates corresponding calendar state.

## Next Steps After This Bootstrap

- Add more real-environment runs for Calendar and Docs after test accounts and fixtures are stable.
- Add richer Windows UIA hints without making them the sole source of truth.
- Stabilize optional PaddleOCR dependencies for environments that want OCR-based assertions.
- Introduce replay and trace-to-dataset export for later self-healing and tuning.

## Design Document

See [docs/design.md](docs/design.md) for the system architecture, module boundaries, data flow, and milestone plan.
See [docs/competition_delivery.md](docs/competition_delivery.md) for the competition requirement checklist and delivery evidence.
