import pytest

from cua_lark.models import ActionProposal, Bounds, Point


def test_pointer_action_requires_coordinates():
    with pytest.raises(ValueError):
        ActionProposal(action="click", target="button")


def test_bounds_contains_point():
    bounds = Bounds(left=10, top=10, width=100, height=80)
    assert bounds.contains(Point(x=50, y=50))
    assert not bounds.contains(Point(x=200, y=50))


def test_wait_action_is_valid_without_coordinates():
    action = ActionProposal(action="wait", wait_seconds=0.2)
    assert action.action.value == "wait"
