"""RED/GREEN for TicketVikunjaSync (sdd/tickets-sync-vikunja PR 1, task 1.2/1.3).

Verifies the `ticket_id` UNIQUE constraint at the DB level: two rows with the
same `ticket_id` must raise `IntegrityError`, never silently succeed.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.tickets.models.ticket_vikunja_sync import TicketVikunjaSync


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine, tables=[TicketVikunjaSync.__table__])
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestTicketIdIsUnique:
    def test_ticket_id_is_unique(self, db_session) -> None:
        db_session.add(TicketVikunjaSync(ticket_id=1, estado="pendiente"))
        db_session.commit()

        db_session.add(TicketVikunjaSync(ticket_id=1, estado="pendiente"))
        with pytest.raises(IntegrityError):
            db_session.commit()
