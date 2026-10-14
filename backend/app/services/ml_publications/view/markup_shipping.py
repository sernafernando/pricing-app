"""The active publications of the priced products, as the shipping resolver reads them.

`resolver_costos_envio_batch` needs, for each product, the MLAs of its ACTIVE publications (it reads `mla` and
`activo` of each). Left to load them itself it builds one `PublicacionML` entity per publication, every column of
it: 24k entities on a 25k-publication store, about 0.4 s of a set-wide markup request, to read two attributes of
each. `ActivePublications` is the `pubs_by_item` the resolver accepts for callers that already have them, built
from the two columns it reads, in ONE statement (the product ids travel as one array parameter) and only when the
resolver first asks, so a caller that stubs the resolver issues no query.

This module reads the pricing tables' publication mirror, not the product catalog.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterator, Mapping, NamedTuple, Sequence

from sqlalchemy import ARRAY, Integer, any_, literal, select
from sqlalchemy.orm import Session

from app.models.publicacion_ml import PublicacionML


class ActivePublication(NamedTuple):
    """The two attributes of a publication the resolver reads (`activo` is always true here: only those are read)."""

    mla: str
    activo: bool = True


class ActivePublications(Mapping):
    """`product item_id -> [active publications]`, loaded on first access."""

    def __init__(self, db: Session, product_ids: Sequence[int]) -> None:
        self._db = db
        self._product_ids = list(product_ids)
        self._by_product: dict[int, list[ActivePublication]] | None = None

    def _load(self) -> dict[int, list[ActivePublication]]:
        if self._by_product is None:
            found: dict[int, list[ActivePublication]] = defaultdict(list)
            if self._product_ids:
                rows = self._db.connection().execute(
                    select(PublicacionML.item_id, PublicacionML.mla).where(
                        PublicacionML.item_id == any_(literal(self._product_ids, ARRAY(Integer))),
                        PublicacionML.activo.is_(True),
                    )
                )
                for product_id, mla in rows.all():
                    found[product_id].append(ActivePublication(mla))
            self._by_product = dict(found)
        return self._by_product

    def __getitem__(self, product_id: int) -> list[ActivePublication]:
        return self._load()[product_id]

    def __iter__(self) -> Iterator[int]:
        return iter(self._load())

    def __len__(self) -> int:
        return len(self._load())
