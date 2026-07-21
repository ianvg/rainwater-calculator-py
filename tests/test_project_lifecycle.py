from __future__ import annotations

import pytest

from tkinter_app import RainwaterTkApp


class _DraftStub:
    def __init__(self) -> None:
        self.cleared = False

    def clear(self) -> None:
        self.cleared = True


class _AppStub:
    def __init__(
        self, *, dirty: bool = True, save_succeeds: bool = True, choice: str = "cancel"
    ) -> None:
        self.dirty = dirty
        self.save_succeeds = save_succeeds
        self.choice = choice
        self.save_calls = 0
        self.working_draft_store = _DraftStub()

    def _refresh_project_dirty_state(self) -> bool:
        return self.dirty

    def save_project(self) -> bool:
        self.save_calls += 1
        return self.save_succeeds

    def _ask_unsaved_changes(self, _action: str) -> str:
        return self.choice


@pytest.mark.parametrize(
    ("choice", "expected", "save_calls", "draft_cleared"),
    [
        ("save", True, 1, False),
        ("discard", True, 0, True),
        ("cancel", False, 0, False),
    ],
)
def test_unsaved_change_guard_honors_save_discard_and_cancel(
    choice, expected, save_calls, draft_cleared
) -> None:
    app = _AppStub(choice=choice)

    result = RainwaterTkApp._confirm_project_replacement(app, "closing the project")

    assert result is expected
    assert app.save_calls == save_calls
    assert app.working_draft_store.cleared is draft_cleared


def test_unsaved_change_guard_stays_open_when_save_fails() -> None:
    app = _AppStub(save_succeeds=False, choice="save")

    assert not RainwaterTkApp._confirm_project_replacement(app, "exiting")
    assert app.save_calls == 1
    assert not app.working_draft_store.cleared


def test_clean_project_does_not_prompt() -> None:
    app = _AppStub(dirty=False)
    app._ask_unsaved_changes = lambda _action: (_ for _ in ()).throw(
        AssertionError("A clean project should not display an unsaved-change prompt.")
    )

    assert RainwaterTkApp._confirm_project_replacement(app, "exiting")
