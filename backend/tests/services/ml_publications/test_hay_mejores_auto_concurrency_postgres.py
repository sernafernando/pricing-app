"""Two simultaneous Auto runs on the same MLA enroll once (row lock)."""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker

from app.models.ml_publications import MlItemSalePrice, MlItemSellerPromotions
from app.services import ml_promotions_hay_mejores as hm
from app.services.ml_hay_mejores_criterios_service import default_criterios


@pytest.mark.postgres
def test_two_simultaneous_auto_runs_schedule_one_enroll(mlpub_pg, monkeypatch) -> None:
    Session = sessionmaker(bind=mlpub_pg)
    s0 = Session()
    s0.add(
        MlItemSellerPromotions(
            item_id="MLA1",
            candidate_count=1,
            started_promotion_keys=[],
            raw=[{"id": "A", "type": "SMART", "status": "candidate", "price": 900}],
            hay_mejores_ofertas=False,
        )
    )
    s0.add(MlItemSalePrice(item_id="MLA1", amount=Decimal("1000.00"), raw={"amount": 1000}))
    s0.commit()
    s0.close()

    def slow_eval(*_a, **_k):
        time.sleep(0.6)  # widen the decide window
        return hm.MejoresEvaluacion(
            mejores=[("A", 900.0)],
            status_quo={},
            candidatas=[
                {
                    "key": "A",
                    "price": 900.0,
                    "markup": 12.0,
                    "path_clasico": True,
                    "path_c2": False,
                    "promotion_id": "A",
                    "promotion_type": "SMART",
                }
            ],
            criterios={},
        )

    monkeypatch.setattr(hm, "evaluar_mejores_candidatas", slow_eval)
    monkeypatch.setattr(
        hm, "get_criterios", lambda *_a, **_k: replace(default_criterios("MLA1"), auto_aplicacion=True)
    )
    monkeypatch.setattr(hm, "record_flag_transition", lambda *_a, **_k: None)
    monkeypatch.setattr(hm, "_enqueue_catalog_competition_refresh", lambda *_a, **_k: None)
    monkeypatch.setattr(hm, "notify_hay_mejores_changed", lambda *_a, **_k: None)
    monkeypatch.setattr(hm, "_ensure_hay_mejores_listeners", lambda *_a, **_k: None)

    scheduled: list[int] = []
    errors: list[BaseException] = []

    def run(delay: float) -> None:
        time.sleep(delay)
        s = Session()
        try:
            hm.actualizar_hay_mejores_ofertas(s, "MLA1")
            scheduled.append(len(s.info.get(hm._AUTO_PENDING) or []))
            s.commit()
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)
        finally:
            s.close()

    t1 = threading.Thread(target=run, args=(0.0,))
    t2 = threading.Thread(target=run, args=(0.15,))
    t1.start()
    t2.start()
    t1.join(20)
    t2.join(20)
    assert not errors, errors
    assert sorted(scheduled) == [0, 1], scheduled
