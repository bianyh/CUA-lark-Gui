from pathlib import Path
from uuid import uuid4

from cua_lark.agents import ReportAgent
from cua_lark.models import Bounds, Observation, TaskContext, TestCase as CuaTestCase, TraceEvent


def test_reporter_writes_files():
    tmp_path = Path("test_artifacts") / f"reporter_{uuid4().hex}"
    tmp_path.mkdir(parents=True, exist_ok=True)
    case = CuaTestCase(
        id="sample",
        name="Sample",
        product="IM",
        instruction="test",
        expected_result="ok",
    )
    context = TaskContext(
        case=case,
        run_id="run",
        run_dir=str(tmp_path),
        status="passed",
    )
    context.add_trace(
        TraceEvent(
            case_id="sample",
            step_id="1",
            observation=Observation(
                screenshot_path="fake.png",
                window_bounds=Bounds(left=0, top=0, width=100, height=100),
            ),
        )
    )
    paths = ReportAgent().write(context)
    assert paths["json"].exists()
    assert paths["markdown"].exists()
    assert paths["html"].exists()
