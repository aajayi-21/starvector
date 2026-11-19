"""Parity of the console paths and the operator command (spec OC1
section 9).

Each operator path of the server has a command, or a line in
`NOT_IN_CLI` that says why it has none. A new console path with no
command thus stops this test.
"""

from fastapi.routing import APIRoute
from svc_fixture import build_service_fixture

from service import operator_plan
from service.server import create_app

# The roots of the operator plane: the dev surfaces, the day moves,
# the scripted reader, and the dev sign-in. A path is in the plane
# when it is a root or is below one: `/api/device-code` is a player
# path, and it is not below `/api/dev`.
_OPERATOR_ROOTS = ("/api/dev", "/api/ops", "/api/door")
# `GET /api/day` is the player's view of the day. The paths below it
# are the day moves.
_DAY_MOVES = "/api/day/"


def _in_operator_plane(path: str) -> bool:
    return path.startswith(_DAY_MOVES) or any(
        path == root or path.startswith(root + "/")
        for root in _OPERATOR_ROOTS)


def _operator_routes(app) -> set[tuple[str, str]]:
    found = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not _in_operator_plane(route.path):
            continue
        for method in route.methods - {"HEAD"}:
            found.add((method, route.path))
    return found


def test_each_operator_path_has_a_command_or_a_stated_cause(
        tmp_path) -> None:
    fixture = build_service_fixture(tmp_path)
    app = create_app(fixture["service_config"], dev_mode=True)
    routes = _operator_routes(app)
    known = operator_plan.covered_routes() | set(operator_plan.NOT_IN_CLI)
    assert routes - known == set(), "an operator path has no command"
    assert known - routes == set(), "a table names a path that is gone"


def test_no_path_is_in_the_two_tables() -> None:
    both = operator_plan.covered_routes() & set(operator_plan.NOT_IN_CLI)
    assert both == set()


def test_each_cause_of_a_path_with_no_command_is_text() -> None:
    for route, cause in operator_plan.NOT_IN_CLI.items():
        assert isinstance(cause, str) and cause.strip(), route
