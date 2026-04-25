from __future__ import annotations

import json
from pathlib import Path

from cua_lark.models import RunReport
from cua_lark.utils.json import to_jsonable


class ReportWriter:
    def write(self, report: RunReport) -> dict[str, Path]:
        report.output_dir.mkdir(parents=True, exist_ok=True)
        json_path = report.output_dir / "run.json"
        markdown_path = report.output_dir / "report.md"

        json_path.write_text(
            json.dumps(to_jsonable(report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        markdown_path.write_text(self._render_markdown(report), encoding="utf-8")

        return {"json": json_path, "markdown": markdown_path}

    def _render_markdown(self, report: RunReport) -> str:
        lines = [
            f"# Run Report: {report.task_id}",
            "",
            f"- Product: `{report.product}`",
            f"- Status: `{report.status}`",
            f"- Duration: `{report.duration_seconds:.2f}s`",
            f"- Artifact Dir: `{report.artifact_dir}`",
            f"- Failure Reason: `{report.failure_reason or 'N/A'}`",
            "",
            "## Metrics",
            "",
        ]
        for key, value in report.metrics.items():
            lines.append(f"- {key}: `{value}`")

        lines.extend(["", "## Steps", ""])
        for record in report.step_records:
            lines.append(
                f"- Step {record.index} attempt {record.attempt}: `{record.action.action_type}` "
                f"{record.action.description} -> `{record.success}`"
            )
            if record.state_assessment:
                lines.append(f"  state: {record.state_assessment.summary}")
            if record.progress_assessment:
                lines.append(f"  progress: {record.progress_assessment.summary}")
            if record.reflection:
                lines.append(f"  reflection: {record.reflection.root_cause}")
                lines.append(f"  strategy: {record.reflection.suggested_strategy}")
            if record.validation:
                lines.append(f"  validation: {record.validation.summary}")
            if record.error:
                lines.append(f"  error: {record.error}")

        if report.final_validation:
            lines.extend(
                [
                    "",
                    "## Final Validation",
                    "",
                    f"- Passed: `{report.final_validation.passed}`",
                    f"- Summary: {report.final_validation.summary}",
                    f"- Strategy: `{report.final_validation.strategy}`",
                ]
            )

        if report.final_progress:
            lines.extend(
                [
                    "",
                    "## Final Progress",
                    "",
                    f"- Success: `{report.final_progress.success}`",
                    f"- Completion Score: `{report.final_progress.completion_score:.2f}`",
                    f"- Label: {report.final_progress.progress_label}",
                    f"- Summary: {report.final_progress.summary}",
                ]
            )

        return "\n".join(lines) + "\n"
