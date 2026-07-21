"""
Shared MLA-set resolver selection for the promo filter control (feature
productos-promo-filter-per-mla).

Single source of truth (spec: "Unified promo filter control resolves to
exactly one MLA-set fold" / "Single source of truth for MLA-set
resolution"): both the Productos LISTADO (`productos_listing.py`,
product-level fold) and the lite detail endpoint
(`productos_detail.py`, per-MLA `matches_filter`) call
`select_promo_resolver` so the (promo_tipos, promo_estado) -> resolver
dispatch can never diverge between the two call sites.

Lives in its own module (not in `productos_listing.py`) to avoid a
circular import between `productos_listing.py` and `productos_detail.py`.

The actual `fetch_mlas_with_*` callables are injected via `PromoResolverFns`
(built by each caller from ITS OWN module-level imports) rather than
imported directly here — this keeps `unittest.mock.patch(
"app.api.endpoints.productos_listing.fetch_mlas_with_...")`-style patching
at each call site working unchanged, since the callable actually invoked at
request time is whatever name currently lives in the caller's module
namespace.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Callable, List, Optional, Set, Tuple


@dataclass(frozen=True)
class PromoResolverFns:
    """The four cross-DB MLA-set resolvers reused by both call sites.

    Each field is a callable matching one of the `fetch_mlas_with_*`
    signatures in `app.services.ml_promotions_service`, all of which accept
    an optional `mla_ids` kwarg (bounded lite-endpoint query) alongside their
    own positional args.
    """

    active_promo_type: Callable[..., Set[str]]
    started: Callable[..., Set[str]]
    candidate_only: Callable[..., Set[str]]
    candidate_only_for_types: Callable[..., Set[str]]


def select_promo_resolver(
    fns: PromoResolverFns,
    promo_tipos: Optional[List[str]],
    promo_estado: Optional[str],
    con_promo_aplicada: Optional[bool] = None,
    con_promo_sin_aplicar: Optional[bool] = None,
    mla_ids: Optional[List[str]] = None,
) -> Optional[Tuple[Callable[[], Set[str]], str]]:
    """Resolves the (promo_tipos, promo_estado) decision table (design D2)
    to AT MOST one resolver — never independently-ANDed subqueries.

    Decision table (`promo_tipos` present -> legacy params IGNORED
    entirely, per D2's explicit precedence rule):

    | promo_tipos | promo_estado          | resolver                              |
    |-------------|------------------------|----------------------------------------|
    | present     | disponible / None      | active_promo_type(tipos, False)        |
    | present     | aplicada               | active_promo_type(tipos, True)         |
    | present     | sin_aplicar            | candidate_only_for_types(tipos)        |
    | absent      | (con_promo_aplicada)   | started()                              |
    | absent      | (con_promo_sin_aplicar)| candidate_only()                       |
    | absent      | none                   | None (no fold)                         |

    Args:
        fns: the four resolver callables, injected by the caller so
            `unittest.mock.patch` at the caller's own module namespace keeps
            working.
        promo_tipos: list of promotion_type strings, or None/[] (empty list
            treated the same as None — no type filter).
        promo_estado: "disponible" | "aplicada" | "sin_aplicar" | None.
        con_promo_aplicada: legacy boolean fallback, used ONLY when
            `promo_tipos` is absent/empty.
        con_promo_sin_aplicar: legacy boolean fallback, used ONLY when
            `promo_tipos` is absent/empty.
        mla_ids: optional bound (feature productos-promo-filter-per-mla) —
            forwarded to the chosen resolver so the lite endpoint can scope
            the cross-DB query to a single product's own MLAs instead of the
            full account universe. List-level callers must NOT pass this
            (full-universe fold preserved).

    Returns:
        `(resolver, log_context)` where `resolver` is a zero-arg callable
        (already bound via `functools.partial`) returning `Set[str]`, and
        `log_context` is the short label used by `_resolve_and_fold_mlas`'s
        503-mapping warning log. `None` when no promo filter is active.
    """
    if promo_tipos:
        if promo_estado == "sin_aplicar":
            resolver = partial(fns.candidate_only_for_types, promo_tipos, mla_ids=mla_ids)
        else:
            applied_only = promo_estado == "aplicada"
            resolver = partial(fns.active_promo_type, promo_tipos, applied_only, mla_ids=mla_ids)
        return resolver, "Filtro de promociones"

    if con_promo_aplicada:
        return partial(fns.started, mla_ids=mla_ids), "Filtro con_promo_aplicada"

    if con_promo_sin_aplicar:
        return partial(fns.candidate_only, mla_ids=mla_ids), "Filtro con_promo_sin_aplicar"

    return None
