"""Tests for the ML billing daily sweep (ml-ventas-desglose-costos, corte 3).

Contract-first: assert the PROMISES (flag-gated, lock reuse, pagination,
request spacing, 429 clean cutoff with no retry, idempotent writes,
completeness stat as observation-only) not just the happy path.

ASSUMPTION (not yet confirmed by the user, see module docstring on
`billing_sweep_service.py`): this sweep covers ONLY the currently OPEN
billing period, re-swept whole every day. No backfill of closed periods.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest import mock

import pytest

from app.core.config import settings
from app.models.ml_billing import MlBillingCharge, MlBillingChargeOrder, MlBillingPeriodStat
from app.services.ml_billing import billing_sweep_service
from app.services.ml_webhook_client import ml_webhook_client


def _fake_ctx(db):
    class _Ctx:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            return False

    return lambda: _Ctx()


@pytest.fixture(autouse=True)
def _background_db(db, monkeypatch):
    monkeypatch.setattr(billing_sweep_service, "get_background_db", _fake_ctx(db))
    # También en `sweep_service`: `release_lock_as_error` y sus hermanas
    # abren su PROPIA sesión desde ese namespace. Sin parchearlo, el lock
    # se libera contra otra base y el test no puede ver el resultado --
    # solo que la función fue llamada, que es bastante menos.
    from app.services.ml_orders_ingestion import sweep_service as _sweep

    monkeypatch.setattr(_sweep, "get_background_db", _fake_ctx(db))


@pytest.fixture(autouse=True)
def _sin_red_de_verdad(monkeypatch):
    """Corta `get_billing_periods` en TODO el módulo, por defecto.

    Cuando el barrido derivaba el período de la fecha no llamaba a nadie, y
    ningún test necesitaba mockearlo. Al pasar a preguntarle a ML, ocho
    tests empezaron a salir a producción de verdad — y se comían el
    presupuesto de 5 requests por minuto de la CUENTA, que es exactamente
    lo que este módulo existe para proteger. Uno devolvió 429 y así lo
    descubrimos.

    Acordarse de mockearlo test por test no es una defensa: el que agregue
    el número nueve se va a olvidar. El corte va acá, y el que necesite
    otra respuesta la sobreescribe en su propio `with`.
    """
    monkeypatch.setattr(
        ml_webhook_client,
        "get_billing_periods",
        mock.AsyncMock(side_effect=AssertionError("un test intentó salir a la red: mockeá get_billing_periods")),
    )


@pytest.fixture(autouse=True)
def _no_flag(monkeypatch):
    monkeypatch.setattr(settings, "ML_BILLING_ENABLED", True)


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(billing_sweep_service.time, "sleep", mock.Mock())


def _detail(detail_id: str, amount: str = "100.00", order_id: int = 2000018265495500) -> dict:
    return {
        "charge_info": {
            "detail_id": detail_id,
            "detail_type": "CHARGE",
            "detail_sub_type": "CVFV",
            "detail_amount": amount,
        },
        "items_info": [{"order_id": order_id}],
        "sales_info": [],
        "shipping_info": {},
        "discount_info": {},
        "document_info": {"document_id": "DOC1"},
    }


def _page(results: list, total: int, offset: int = 0) -> dict:
    return {"results": results, "paging": {"total": total, "limit": 1000, "offset": offset}}


def _documents(count_details: int) -> dict:
    return {"documents": [{"count_details": count_details}]}


class TestFlagGate:
    def test_flag_off_makes_zero_requests_and_writes_nothing(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "ML_BILLING_ENABLED", False)
        with mock.patch.object(ml_webhook_client, "get_billing_details", new=mock.AsyncMock()) as m:
            result = billing_sweep_service.run_billing_sweep()
        assert result.ran is False
        m.assert_not_called()


class TestLockReuse:
    def test_lock_not_acquired_cuts_pass_without_writing(self, monkeypatch, db) -> None:
        monkeypatch.setattr(billing_sweep_service, "try_acquire_run_lock", lambda *a, **k: False)
        with mock.patch.object(ml_webhook_client, "get_billing_details", new=mock.AsyncMock()) as m:
            result = billing_sweep_service.run_billing_sweep()
        assert result.ran is False
        m.assert_not_called()
        assert db.query(MlBillingCharge).count() == 0

    def test_lock_functions_called_with_billing_cursor_name(self, monkeypatch, db) -> None:
        calls = {}

        def _fake_acquire(db_, now, cursor_name="sweep", **k):
            calls["acquire"] = cursor_name
            return True

        monkeypatch.setattr(billing_sweep_service, "try_acquire_run_lock", _fake_acquire)
        monkeypatch.setattr(
            billing_sweep_service,
            "release_lock_as_idle",
            lambda *a, cursor_name="sweep", **k: calls.setdefault("release", cursor_name),
        )
        with (
            mock.patch.object(ml_webhook_client, "get_billing_details", new=mock.AsyncMock(return_value=_page([], 0))),
            mock.patch.object(
                ml_webhook_client, "get_billing_documents", new=mock.AsyncMock(return_value=_documents(0))
            ),
        ):
            billing_sweep_service.run_billing_sweep()

        assert calls["acquire"] == "billing"
        assert calls["release"] == "billing"


class TestPagination:
    def test_pages_until_paging_total_covered(self, db) -> None:
        page1 = _page([_detail("D1"), _detail("D2")], total=3, offset=0)
        page2 = _page([_detail("D3")], total=3, offset=2)
        get_details = mock.AsyncMock(side_effect=[page1, page2])
        with (
            mock.patch.object(ml_webhook_client, "get_billing_details", new=get_details),
            mock.patch.object(
                ml_webhook_client, "get_billing_documents", new=mock.AsyncMock(return_value=_documents(3))
            ),
        ):
            result = billing_sweep_service.run_billing_sweep()

        assert result.charges_seen == 3
        assert get_details.call_count == 2
        assert db.query(MlBillingCharge).count() == 3


class TestSpacing:
    def test_sleeps_between_pages_with_correct_spacing(self, db) -> None:
        page1 = _page([_detail("D1")], total=2, offset=0)
        page2 = _page([_detail("D2")], total=2, offset=1)
        get_details = mock.AsyncMock(side_effect=[page1, page2])
        with (
            mock.patch.object(ml_webhook_client, "get_billing_details", new=get_details),
            mock.patch.object(
                ml_webhook_client, "get_billing_documents", new=mock.AsyncMock(return_value=_documents(2))
            ),
        ):
            billing_sweep_service.run_billing_sweep()

        billing_sweep_service.time.sleep.assert_called_with(billing_sweep_service.REQUEST_SPACING_SECONDS)


class Test429CleanCutoff:
    def test_failed_request_stops_pass_without_retry(self, db) -> None:
        get_details = mock.AsyncMock(return_value=None)
        with mock.patch.object(ml_webhook_client, "get_billing_details", new=get_details):
            result = billing_sweep_service.run_billing_sweep()

        assert result.stopped_early is True
        assert get_details.call_count == 1
        assert db.query(MlBillingCharge).count() == 0


class TestIdempotency:
    def test_two_passes_same_overlapping_data_do_not_duplicate(self, db) -> None:
        page = _page([_detail("D1"), _detail("D2")], total=2, offset=0)
        for _ in range(2):
            get_details = mock.AsyncMock(return_value=page)
            with (
                mock.patch.object(ml_webhook_client, "get_billing_details", new=get_details),
                mock.patch.object(
                    ml_webhook_client, "get_billing_documents", new=mock.AsyncMock(return_value=_documents(2))
                ),
            ):
                billing_sweep_service.run_billing_sweep()

        assert db.query(MlBillingCharge).count() == 2
        assert db.query(MlBillingChargeOrder).count() == 2


class TestCompletenessStat:
    def test_documents_count_mismatch_is_observation_not_error(self, db) -> None:
        page = _page([_detail("D1")], total=1, offset=0)
        with (
            mock.patch.object(ml_webhook_client, "get_billing_details", new=mock.AsyncMock(return_value=page)),
            mock.patch.object(
                ml_webhook_client, "get_billing_documents", new=mock.AsyncMock(return_value=_documents(999))
            ),
        ):
            result = billing_sweep_service.run_billing_sweep()

        assert result.error is None
        assert result.stopped_early is False

        stat = db.query(MlBillingPeriodStat).filter_by(period_key=result.period_key).first()
        assert stat is not None
        assert stat.documents_count_details == 999
        assert stat.stored_total == 1
        assert stat.reported_total == 1

    def test_rerun_same_period_upserts_stat_row_not_duplicates(self, db) -> None:
        page = _page([_detail("D1")], total=1, offset=0)
        for _ in range(2):
            with (
                mock.patch.object(ml_webhook_client, "get_billing_details", new=mock.AsyncMock(return_value=page)),
                mock.patch.object(
                    ml_webhook_client, "get_billing_documents", new=mock.AsyncMock(return_value=_documents(1))
                ),
            ):
                billing_sweep_service.run_billing_sweep()

        assert db.query(MlBillingPeriodStat).count() == 1


class TestOpenPeriodKey:
    def test_period_key_before_17th_is_current_month(self) -> None:
        now = datetime(2026, 9, 5, tzinfo=timezone.utc)
        assert billing_sweep_service._derived_period_key(now) == "2026-09-01"

    def test_period_key_on_or_after_17th_is_next_month(self) -> None:
        now = datetime(2026, 9, 17, tzinfo=timezone.utc)
        assert billing_sweep_service._derived_period_key(now) == "2026-10-01"

    def test_period_key_rolls_over_year(self) -> None:
        now = datetime(2026, 12, 20, tzinfo=timezone.utc)
        assert billing_sweep_service._derived_period_key(now) == "2027-01-01"


class TestOpenPeriodComesFromMlNotFromArithmetic:
    """El corte 17-16 es una regla de negocio DE ML. Derivarla acá haría
    barrer un período equivocado en silencio el día que la cambien, y el
    chequeo de completitud compararía contra el total de otro período.
    `get_billing_periods` marca cuál está `OPEN`: cuesta UNA request de las
    ~20 del barrido, una vez por día."""

    def test_gana_el_period_status_open_de_ml_sobre_el_derivado(self) -> None:
        from app.services.ml_billing import billing_sweep_service as svc

        # ML dice que el abierto es otro (como si hubieran movido el corte)
        payload = {
            "results": [
                {"key": "2026-10-01", "period_status": "OPEN"},
                {"key": "2026-09-01", "period_status": "CLOSED"},
            ]
        }
        with mock.patch.object(svc.ml_webhook_client, "get_billing_periods", return_value=payload):
            resolved = svc._resolve_open_period_key(datetime(2026, 9, 7, tzinfo=timezone.utc))

        assert resolved == "2026-10-01"
        assert svc._derived_period_key(datetime(2026, 9, 7, tzinfo=timezone.utc)) == "2026-09-01"

    def test_si_la_llamada_falla_cae_al_derivado_y_no_aborta(self) -> None:
        from app.services.ml_billing import billing_sweep_service as svc

        with mock.patch.object(svc.ml_webhook_client, "get_billing_periods", side_effect=RuntimeError("proxy caído")):
            resolved = svc._resolve_open_period_key(datetime(2026, 9, 7, tzinfo=timezone.utc))

        assert resolved == "2026-09-01"

    def test_si_ml_no_marca_ninguno_como_open_cae_al_derivado(self) -> None:
        from app.services.ml_billing import billing_sweep_service as svc

        with mock.patch.object(svc.ml_webhook_client, "get_billing_periods", return_value={"results": []}):
            resolved = svc._resolve_open_period_key(datetime(2026, 9, 7, tzinfo=timezone.utc))

        assert resolved == "2026-09-01"

    def test_el_barrido_consulta_el_periodo_que_ML_reporta_abierto(self, db) -> None:
        """Cierra el hueco entre `_resolve_open_period_key` y quien lo usa.

        Mutar el call site de vuelta al derivado no ponía ningún test en
        rojo: la función estaba probada, pero nada verificaba que el barrido
        la llamara. Un test que prueba una pieza sin probar que esté
        enchufada deja pasar exactamente ese cambio.
        """
        periodos = {
            "results": [
                {"key": "2026-10-01", "period_status": "OPEN"},
                {"key": "2026-09-01", "period_status": "CLOSED"},
            ]
        }
        get_details = mock.AsyncMock(return_value=_page([_detail("D1")], total=1, offset=0))
        with (
            mock.patch.object(ml_webhook_client, "get_billing_periods", new=mock.AsyncMock(return_value=periodos)),
            mock.patch.object(ml_webhook_client, "get_billing_details", new=get_details),
            mock.patch.object(
                ml_webhook_client, "get_billing_documents", new=mock.AsyncMock(return_value=_documents(1))
            ),
        ):
            result = billing_sweep_service.run_billing_sweep()

        # el período que pidió, no el que da la aritmética local
        assert get_details.call_args.args[0] == "2026-10-01"
        assert result.period_key == "2026-10-01"
        assert db.query(MlBillingPeriodStat).one().period_key == "2026-10-01"


class TestLockIsAlwaysReleased:
    """El camino más caro del módulo y el único que no tenía red.

    Si una excepción en medio del loop deja el lock tomado, el cron de
    mañana encuentra el cursor trabado y se va sin hacer nada — en
    silencio, todos los días, hasta que alguien mira la tabla."""

    def test_una_excepcion_en_medio_del_barrido_libera_el_lock(self, db) -> None:
        get_details = mock.AsyncMock(side_effect=RuntimeError("se cayó a mitad de camino"))
        with (
            mock.patch.object(ml_webhook_client, "get_billing_details", new=get_details),
            mock.patch.object(
                billing_sweep_service, "release_lock_as_error", wraps=billing_sweep_service.release_lock_as_error
            ) as release_error,
        ):
            result = billing_sweep_service.run_billing_sweep()

        assert result.error is not None
        release_error.assert_called_once()

        from app.services.ml_orders_ingestion.sweep_service import load_cursor

        cursor = load_cursor(db, cursor_name=billing_sweep_service.CURSOR_NAME)
        assert cursor is not None
        assert cursor.state != "running", "el lock quedó tomado: el cron de mañana no va a correr"

    def test_el_periodo_se_resuelve_despues_del_lock_no_antes(self) -> None:
        """Si dos crons se solapan, el segundo tiene que irse SIN gastar una
        request del presupuesto de 5/minuto, que es de toda la cuenta."""
        get_periods = mock.AsyncMock(return_value={"results": []})
        with (
            mock.patch.object(billing_sweep_service, "try_acquire_run_lock", return_value=False),
            mock.patch.object(ml_webhook_client, "get_billing_periods", new=get_periods),
        ):
            result = billing_sweep_service.run_billing_sweep()

        assert result.ran is False
        assert result.error == "already running"
        get_periods.assert_not_called()
