from cua_lark.executor import ActionExecutor, scale_point
from cua_lark.models import ActionProposal, Bounds, Observation, Point


def test_scale_point_uses_inverse_dpi_scale():
    assert scale_point(Point(x=150, y=75), 1.5) == Point(x=100, y=50)


def test_dry_run_click_executes_without_pyautogui():
    observation = Observation(
        screenshot_path="fake.png",
        window_bounds=Bounds(left=0, top=0, width=500, height=400),
    )
    proposal = ActionProposal(action="click", coordinates=Point(x=10, y=10))
    result = ActionExecutor(dry_run=True).execute(proposal, observation)
    assert result.executed
    assert "dry-run" in result.message


def test_window_relative_point_maps_to_screen_coordinates():
    observation = Observation(
        screenshot_path="fake.png",
        window_bounds=Bounds(left=0, top=0, width=500, height=400),
        screen_bounds=Bounds(left=100, top=200, width=500, height=400),
        scale_factor=1.0,
    )
    point = ActionExecutor._to_screen_point(Point(x=10, y=20), observation, 1.0)
    assert point == Point(x=110, y=220)


def test_coordinates_outside_bounds_are_rejected():
    observation = Observation(
        screenshot_path="fake.png",
        window_bounds=Bounds(left=0, top=0, width=50, height=50),
    )
    proposal = ActionProposal(action="click", coordinates=Point(x=60, y=10))
    result = ActionExecutor(dry_run=True).execute(proposal, observation)
    assert not result.executed
    assert "outside" in result.message
