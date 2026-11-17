"""C6 monopoly ceiling: flag via synthetic c6 fingerprint when raise-price opportunity."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import ml_promotions_hay_mejores as hay_mejores
from app.services.ml_hay_mejores_criterios_service import default_criterios
from app.services.ml_promotions_hay_mejores import C6_FINGERPRINT_KEY, FlagDecision, MonopolioEvaluacion


class _Nested:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_evaluar_monopolio_c6_builds_flag_tuple(monkeypatch) -> None:
    monkeypatch.setattr(hay_mejores, "obtener_ultimo_snapshot", lambda *_a, **_k: object())
    monkeypatch.setattr(hay_mejores, "_our_price_ars_from_snapshot", lambda *_a, **_k: 10000.0)
    monkeypatch.setattr(hay_mejores, "min_rival_price_ars", lambda *_a, **_k: 16000.0)
    view = replace(default_criterios("MLA1"), c6_activo=True)
    out = hay_mejores.evaluar_monopolio_c6(MagicMock(), "MLA1", criterios=view)
    assert out is not None
    assert out.flag_tuple == (C6_FINGERPRINT_KEY, 15900.0)
    assert out.oportunidad["gap"] == 6000.0


def test_actualizar_flags_c6_only_when_not_solo_via_promo(monkeypatch) -> None:
    row = SimpleNamespace(
        hay_mejores_ofertas=False,
        hay_mejores_fingerprint=None,
        hay_mejores_descartado_fingerprint=None,
        raw=[],
    )
    sale = SimpleNamespace(amount=10000.0)
    db = MagicMock()
    db.begin_nested.return_value = _Nested()
    db.query.return_value.filter.return_value.one_or_none.side_effect = [row, sale]

    monkeypatch.setattr(hay_mejores, "_candidate_entries", lambda *_a, **_k: [])
    monkeypatch.setattr(
        hay_mejores,
        "get_criterios",
        lambda *_a, **_k: replace(default_criterios("MLA1"), c6_activo=True, c6_solo_via_promo=False),
    )
    monkeypatch.setattr(
        hay_mejores,
        "evaluar_monopolio_c6",
        lambda *_a, **_k: MonopolioEvaluacion(
            oportunidad={"our_price": 10000.0, "segundo_precio": 16000.0, "gap": 6000.0, "precio_objetivo": 15900.0},
            flag_tuple=(C6_FINGERPRINT_KEY, 15900.0),
            solo_via_promo=False,
        ),
    )
    monkeypatch.setattr(hay_mejores, "_enqueue_catalog_competition_refresh", lambda *_a, **_k: None)
    monkeypatch.setattr(hay_mejores, "record_flag_transition", lambda *_a, **_k: None)
    monkeypatch.setattr(hay_mejores, "notify_hay_mejores_changed", lambda *_a, **_k: None)

    decision = hay_mejores.actualizar_hay_mejores_ofertas(db, "MLA1")
    assert decision == FlagDecision(
        hay_mejores=True,
        fingerprint="c6:15900",
        descartado_fingerprint=None,
    )
    assert row.hay_mejores_ofertas is True


def test_actualizar_skips_c6_only_when_solo_via_promo(monkeypatch) -> None:
    row = SimpleNamespace(
        hay_mejores_ofertas=False,
        hay_mejores_fingerprint=None,
        hay_mejores_descartado_fingerprint=None,
        raw=[],
    )
    sale = SimpleNamespace(amount=10000.0)
    db = MagicMock()
    db.begin_nested.return_value = _Nested()
    db.query.return_value.filter.return_value.one_or_none.side_effect = [row, sale]

    monkeypatch.setattr(hay_mejores, "_candidate_entries", lambda *_a, **_k: [])
    monkeypatch.setattr(
        hay_mejores,
        "get_criterios",
        lambda *_a, **_k: replace(default_criterios("MLA1"), c6_activo=True, c6_solo_via_promo=True),
    )
    monkeypatch.setattr(
        hay_mejores,
        "evaluar_monopolio_c6",
        lambda *_a, **_k: MonopolioEvaluacion(
            oportunidad={"our_price": 10000.0, "segundo_precio": 16000.0, "gap": 6000.0, "precio_objetivo": 15900.0},
            flag_tuple=(C6_FINGERPRINT_KEY, 15900.0),
            solo_via_promo=True,
        ),
    )
    monkeypatch.setattr(hay_mejores, "_enqueue_catalog_competition_refresh", lambda *_a, **_k: None)
    monkeypatch.setattr(hay_mejores, "record_flag_transition", lambda *_a, **_k: None)

    decision = hay_mejores.actualizar_hay_mejores_ofertas(db, "MLA1")
    assert decision == FlagDecision(hay_mejores=False, fingerprint=None, descartado_fingerprint=None)
    assert row.hay_mejores_ofertas is False
