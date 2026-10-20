"""`sell_in_bono_dirty` claim and settle (sell-in-sell-out T3c-3): what the
`sell_in.bono` worker uses to take keys off the queue, ack them and charge the
ones that fail, parking them after `MAX_ATTEMPTS`.

Postgres only (`FOR UPDATE SKIP LOCKED`). Runs in a throwaway schema.
"""

from __future__ import annotations

from typing import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from app.services.sell_in import bono_queue
from tests.services.sell_in import _bono_world as b


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    with b.world("sell_in_bono_claim") as engine:
        yield engine


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    yield
    b.clean(engine)


def _sql(engine: Engine, statement: str, **params) -> None:
    with engine.begin() as conn:
        conn.execute(text(statement), params)


@pytest.mark.postgres
class TestClaim:
    def test_claim_skips_parked_excluded_and_locked_rows(self, engine: Engine) -> None:
        uno, dos, tres = b.bono(engine), b.bono(engine), b.bono(engine)
        _sql(engine, "UPDATE sell_in_bono_dirty SET attempts = :m WHERE ref = :r", m=bono_queue.MAX_ATTEMPTS, r=tres)
        Session = sessionmaker(bind=engine)
        with Session() as holder, Session() as db:
            assert bono_queue.claim_batch(holder, 1) == [("bono", uno)]

            # uno is held by the other session and tres is parked: only dos is left, unless excluded.
            assert bono_queue.claim_batch(db, 10, excluded=[("bono", dos)]) == []
            assert bono_queue.claim_batch(db, 10) == [("bono", dos)]
            holder.rollback()
            db.rollback()

    def test_settle_acks_done_and_charges_failed_rows_parking_at_the_limit(self, engine: Engine) -> None:
        uno, dos = b.bono(engine), b.bono(engine)
        _sql(engine, "UPDATE sell_in_bono_dirty SET attempts = :m WHERE ref = :r", m=bono_queue.MAX_ATTEMPTS - 1, r=dos)
        with sessionmaker(bind=engine)() as db:
            claimed = bono_queue.claim_batch(db, 10)
            parked = bono_queue.settle(db, [("bono", uno)], {("bono", dos): "sin tipo de cambio"})
            db.commit()

        assert claimed == [("bono", uno), ("bono", dos)]
        assert parked == [("bono", dos)]
        assert b.queue_rows(engine) == [("bono", dos, bono_queue.MAX_ATTEMPTS, "sin tipo de cambio")]
