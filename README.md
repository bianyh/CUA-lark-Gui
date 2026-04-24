# CUA-Lark-Gui

Vision-first GUI testing agent for the Feishu desktop client, built for the Feishu AI Product Innovation Competition.

## What This Repository Contains

- A modular CUA runtime with `observe -> plan -> execute -> validate -> report`.
- An OpenAI-compatible vision policy adapter with `responses` first and `chat.completions` fallback.
- Optional Windows desktop automation integrations for screenshot capture, Paddle OCR, and mouse/keyboard control.
- Structured Feishu test case definitions for IM and Calendar MVP scenarios.
- A reporting pipeline that emits `run.json`, `report.md`, and a screenshot timeline per run.

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
cases/                  Structured IM / Calendar cases
docs/                   Design and competition-facing documentation
src/cua_lark/           Core runtime, providers, execution, validation, reporting
tests/                  Lightweight unit tests for the core loop
.github/workflows/      CI checks
```

## Runtime Modes

- `--mock`: Uses synthetic screenshots and a mock executor. This is the safe default for CI and architecture validation.
- Desktop mode: Requires Windows, Feishu desktop client, `pyautogui`, and Paddle OCR availability.

## OCR Backend

- The project uses `PaddleOCR` as the default OCR backend.
- Configure it with `CUA_OCR_BACKEND=paddleocr` and `CUA_PADDLE_OCR_LANG=ch`.
- Use `python -m cua_lark doctor` to confirm whether PaddleOCR is importable in the current environment.
- If `doctor` shows a PaddleOCR import failure, a common local cause is an incompatible `NumPy` / compiled dependency mix. The runtime will fall back to no OCR instead of crashing immediately.

## Git Workflow

- `main` should remain demoable.
- Current implementation branch: `feat-core-loop`.
- Use Conventional Commits for new work, for example `feat: add calendar reschedule case`.
- Commit logical slices: scaffolding, planner changes, new product cases, report improvements.

## Current MVP Scope

- IM: search conversation, send text, `@` mention, verify text appears.
- Calendar: create event, reschedule event, verify time or attendee appears.
- Cross-product: IM receives calendar-related context and the runner validates corresponding calendar state.

## Next Steps After This Bootstrap

- Replace scripted action hints with stronger model-driven grounding.
- Stabilize PaddleOCR dependencies in the base environment and add richer OCR post-processing for Feishu-specific text patterns.
- Add richer Windows UIA hints without making them the sole source of truth.
- Introduce replay and trace-to-dataset export for later self-healing and tuning.

## Design Document

See [docs/design.md](docs/design.md) for the system architecture, module boundaries, data flow, and milestone plan.
