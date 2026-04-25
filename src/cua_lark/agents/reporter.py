from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Template

from cua_lark.models import TaskContext


REPORT_TEMPLATE = """# CUA-Lark Run Report

- Case: {{ case.name }} (`{{ case.id }}`)
- Product: {{ case.product }}
- Status: {{ status }}
- Steps: {{ traces|length }}
- Failure reason: {{ failure_reason or "N/A" }}

## Summary

| Metric | Value |
| --- | --- |
| Passed steps | {{ passed_steps }} |
| Failed steps | {{ failed_steps }} |
| Total duration ms | {{ total_duration_ms }} |

## Trace

{% for trace in traces -%}
### Step {{ trace.step_id }} retry {{ trace.retry_index }}

- Action: {{ trace.action.action.value if trace.action else "N/A" }}
- Target: {{ trace.action.target if trace.action else "N/A" }}
- Executed: {{ trace.execution.executed if trace.execution else "N/A" }}
- Verification: {{ trace.verification.passed if trace.verification else "N/A" }}
- Evidence: {{ trace.verification.evidence if trace.verification else "" }}
- Screenshot: `{{ trace.observation.screenshot_path }}`

{% endfor -%}
"""


class ReportAgent:
    def write(self, context: TaskContext) -> dict[str, Path]:
        run_dir = Path(context.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        report_data = self._summarize(context)

        json_path = run_dir / "report.json"
        md_path = run_dir / "report.md"
        html_path = run_dir / "report.html"

        json_path.write_text(
            json.dumps(context.model_dump(), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        md_content = Template(REPORT_TEMPLATE).render(**report_data)
        md_path.write_text(md_content, encoding="utf-8")
        html_path.write_text(self._to_html(md_content), encoding="utf-8")
        return {"json": json_path, "markdown": md_path, "html": html_path}

    @staticmethod
    def _summarize(context: TaskContext) -> dict:
        passed_steps = sum(
            1
            for trace in context.traces
            if trace.verification is not None and trace.verification.passed
        )
        failed_steps = sum(
            1
            for trace in context.traces
            if trace.verification is not None and not trace.verification.passed
        )
        total_duration_ms = sum(trace.duration_ms for trace in context.traces)
        return {
            "case": context.case,
            "status": context.status,
            "failure_reason": context.failure_reason,
            "traces": context.traces,
            "passed_steps": passed_steps,
            "failed_steps": failed_steps,
            "total_duration_ms": total_duration_ms,
        }

    @staticmethod
    def _to_html(markdown_content: str) -> str:
        escaped = (
            markdown_content.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        return (
            "<!doctype html><html><head><meta charset=\"utf-8\">"
            "<title>CUA-Lark Report</title>"
            "<style>body{font-family:Arial,sans-serif;max-width:960px;margin:32px auto;"
            "line-height:1.55}pre{white-space:pre-wrap;background:#f6f8fa;padding:16px}</style>"
            "</head><body><pre>"
            f"{escaped}"
            "</pre></body></html>"
        )
