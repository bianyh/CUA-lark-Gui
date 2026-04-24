# CUA-Lark-Gui Design

## Goal

Build a Windows-first Computer-Use Agent that can observe Feishu desktop UI, plan multi-step actions from natural-language test instructions, execute them, validate outcomes, and emit reproducible reports for competition submission.

## Architecture

The runtime is split into six layers:

1. `Perception`: screenshot capture, OCR, UI hints, observation summarization.
2. `Grounding`: target candidate representation and bounding-box handling.
3. `Planner`: scripted-step preference plus model-based next-action generation.
4. `Executor`: mock executor for CI and Windows executor for real mouse/keyboard control.
5. `Validator`: OCR, semantic, and image-diff oriented assertions.
6. `Reporter`: structured JSON plus human-readable Markdown output.

## Core Loop

Each run follows:

1. Focus the target application when possible.
2. Capture a pre-action observation.
3. Select the next action from scripted guidance or the vision policy.
4. Execute the action.
5. Capture a post-action observation.
6. Validate the step and decide whether to retry or replan.
7. After the loop ends, validate task-level assertions and write the report.

## Key Interfaces

- `TaskSpec`: normalized test case definition.
- `Observation`: screenshot path, OCR blocks, notes, and window state.
- `ActionStep`: GUI action contract for click, type, scroll, wait, hotkey, and assert.
- `ValidationResult`: pass/fail decision with evidence.
- `RunReport`: complete run artifact with metrics and trajectory.
- `VisionPolicy`: model provider interface for planning and semantic validation.

## Model Integration

- Defaults:
  - `OPENAI_BASE_URL=https://api.chattoken.cc/v1`
  - `OPENAI_MODEL=gpt-4o`
- API key source:
  - `OPENAI_API_KEY` environment variable
  - `.env.local` for local-only development
- Call sequence:
  - Prefer `responses.create`
  - Fallback to `chat.completions.create`

## Windows Execution Notes

- Real execution uses `pyautogui` and optional `pygetwindow`.
- Screenshots use Pillow `ImageGrab`.
- OCR uses `PaddleOCR` by default and falls back to a null provider when PaddleOCR cannot be imported in the local environment.
- Windows UI automation data is intentionally not required for correctness, only for future hint fusion.

## Bundled Case Strategy

Bundled cases are declarative and can include `metadata.scripted_actions`.

- The natural-language instruction remains the source task specification.
- Scripted actions bootstrap repeatable demos and CI-safe mock runs.
- Later iterations can delete or shrink scripted actions as grounding improves.

## Reporting Contract

Each task run writes:

- `artifacts/<task>/<run_id>/timeline/*.png`
- `reports/generated/<task>/<run_id>/run.json`
- `reports/generated/<task>/<run_id>/report.md`

These files together support replay, judging, and postmortem analysis.

## Git Discipline

- Track all repository changes on feature branches.
- Keep generated artifacts out of Git.
- Use small commits aligned to subsystem boundaries.
- Avoid storing any live API key or personal test data.

## Immediate Follow-Up

- Improve model prompts for robust target grounding.
- Add additional Calendar and Docs tasks.
- Introduce run-level dashboards once stable JSON metrics exist.
