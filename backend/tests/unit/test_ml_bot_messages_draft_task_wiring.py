"""
Phase A (PR1), T4.9 — background task wiring smoke test for
`ml_messages_draft_task` (mirrors `ml_questions_draft_task`'s warm-up +
poll-interval loop shape; a real infinite-loop run isn't exercised here,
just that the task function + its imported cycle function exist and are
wired the way `app.main` expects)."""

from __future__ import annotations

import inspect

from app.main import ml_messages_draft_task
from app.services.ml_messages.drafting_service import run_ml_messages_draft_cycle


class TestMlMessagesDraftTaskWiring:
    def test_task_function_exists_and_is_coroutine(self) -> None:
        assert inspect.iscoroutinefunction(ml_messages_draft_task)

    def test_cycle_function_is_importable_coroutine(self) -> None:
        assert inspect.iscoroutinefunction(run_ml_messages_draft_cycle)
