"""T4.1: `GET /ml-bot/questions` fallback_reason filter + counts endpoint.

Uses `rma_superadmin_user` (bypasses `ml_bot.*` permission checks via
`Usuario.es_superadmin`) so these tests focus purely on the filter/route
contract, not the permission system already covered elsewhere."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.ml_bot_question import MlBotQuestion
from tests.conftest import make_access_token


@pytest.fixture()
def superadmin_auth_headers(rma_superadmin_user) -> dict:
    token = make_access_token(rma_superadmin_user)
    return {"Authorization": f"Bearer {token}"}


_next_ml_question_id = iter(range(2_000_000, 3_000_000))


def _seed_question(
    db,
    *,
    status: str = "waiting",
    fallback_reason: str | None = None,
    question_date: datetime | None = None,
) -> MlBotQuestion:
    row = MlBotQuestion(
        ml_question_id=next(_next_ml_question_id),
        item_id="MLA123",
        buyer_id=555,
        buyer_nickname="comprador1",
        question_text="¿Tienen stock?",
        question_date=question_date or datetime.now(timezone.utc),
        status=status,
        fallback_reason=fallback_reason,
    )
    db.add(row)
    db.flush()
    return row


class TestFallbackReasonListFilter:
    def test_valid_fallback_reason_filters_correctly(self, client, db, superadmin_auth_headers) -> None:
        _seed_question(db, fallback_reason="low_confidence")
        _seed_question(db, fallback_reason="provider_error")
        db.commit()

        response = client.get(
            "/api/ml-bot/questions",
            params={"fallback_reason": "low_confidence"},
            headers=superadmin_auth_headers,
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert len(payload["questions"]) == 1
        assert payload["questions"][0]["fallback_reason"] == "low_confidence"

    def test_invalid_fallback_reason_returns_4xx_and_never_queries_db(
        self, client, db, superadmin_auth_headers, query_counter
    ) -> None:
        _seed_question(db, fallback_reason="low_confidence")
        db.commit()

        with query_counter() as counter:
            response = client.get(
                "/api/ml-bot/questions",
                params={"fallback_reason": "not_a_real_reason"},
                headers=superadmin_auth_headers,
            )

        assert 400 <= response.status_code < 500
        assert "fallback_reason" in response.text.lower() or "not_a_real_reason" in response.text
        # FastAPI's Enum-based Query validation (422) rejects the request
        # BEFORE the endpoint body runs, so the `ml_bot_questions` table is
        # never queried for this request (auth still resolves the current
        # user against `usuarios`, which is fine and expected).
        assert counter.matching("ml_bot_questions") == 0

    def test_omitting_param_behaves_as_before(self, client, db, superadmin_auth_headers) -> None:
        _seed_question(db, fallback_reason="low_confidence")
        _seed_question(db, fallback_reason=None)
        db.commit()

        response = client.get("/api/ml-bot/questions", headers=superadmin_auth_headers)

        assert response.status_code == 200
        assert response.json()["total"] == 2

    def test_fallback_reason_filter_ands_with_status_filter_before_count(
        self, client, db, superadmin_auth_headers
    ) -> None:
        _seed_question(db, status="waiting", fallback_reason="low_confidence")
        _seed_question(db, status="published", fallback_reason="low_confidence")
        _seed_question(db, status="waiting", fallback_reason="provider_error")
        db.commit()

        response = client.get(
            "/api/ml-bot/questions",
            params={"status": "waiting", "fallback_reason": "low_confidence"},
            headers=superadmin_auth_headers,
        )

        assert response.status_code == 200
        payload = response.json()
        # `total` (post-filter count) must match the returned row count —
        # both filters applied BEFORE `query.count()`.
        assert payload["total"] == 1
        assert len(payload["questions"]) == 1
        assert payload["questions"][0]["status"] == "waiting"
        assert payload["questions"][0]["fallback_reason"] == "low_confidence"

    def test_question_response_serializes_fallback_reason_none(self, client, db, superadmin_auth_headers) -> None:
        _seed_question(db, fallback_reason=None)
        db.commit()

        response = client.get("/api/ml-bot/questions", headers=superadmin_auth_headers)

        assert response.status_code == 200
        payload = response.json()
        assert payload["questions"][0]["fallback_reason"] is None


class TestFallbackReasonCountsEndpoint:
    def test_counts_endpoint_returns_group_by_reason_and_total(self, client, db, superadmin_auth_headers) -> None:
        _seed_question(db, fallback_reason="low_confidence")
        _seed_question(db, fallback_reason="low_confidence")
        _seed_question(db, fallback_reason="provider_error")
        _seed_question(db, fallback_reason=None)
        db.commit()

        response = client.get("/api/ml-bot/questions/fallback-reason-counts", headers=superadmin_auth_headers)

        assert response.status_code == 200
        payload = response.json()
        assert payload["counts"]["low_confidence"] == 2
        assert payload["counts"]["provider_error"] == 1
        # `total` is sum(counts.values()) — rows with fallback_reason IS
        # NULL (never went through the fallback pipeline) are excluded from
        # both `counts` and `total`, so they always stay consistent.
        assert payload["total"] == 3

    def test_counts_endpoint_honours_status_but_ignores_fallback_reason(
        self, client, db, superadmin_auth_headers
    ) -> None:
        _seed_question(db, status="waiting", fallback_reason="low_confidence")
        _seed_question(db, status="published", fallback_reason="low_confidence")
        db.commit()

        response = client.get(
            "/api/ml-bot/questions/fallback-reason-counts",
            params={"status": "waiting", "fallback_reason": "provider_error"},
            headers=superadmin_auth_headers,
        )

        assert response.status_code == 200
        payload = response.json()
        # `status` filters the counts; `fallback_reason` (even if passed) is
        # deliberately ignored by this endpoint — it counts BY reason.
        assert payload["total"] == 1
        assert payload["counts"] == {"low_confidence": 1}

    def test_counts_route_not_swallowed_by_path_param_route(self, client, db, superadmin_auth_headers) -> None:
        """Route-order proof: `/questions/fallback-reason-counts` must be
        registered BEFORE `/questions/{question_id}` (a path-param route),
        or FastAPI would try to parse "fallback-reason-counts" as a
        `question_id` and 422 instead of hitting the counts handler."""
        db.commit()

        response = client.get("/api/ml-bot/questions/fallback-reason-counts", headers=superadmin_auth_headers)

        assert response.status_code == 200
        assert "counts" in response.json()
