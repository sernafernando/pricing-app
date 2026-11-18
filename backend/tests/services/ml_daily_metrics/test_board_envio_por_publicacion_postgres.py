"""auditoria-stock-niveles S3: each publication's 7d / 30d units split into Full and the rest (ERP).

Full is a sold line whose order ships by `fulfillment` under the Board's own rule (`modo_logistico_expr`, the one
"Por tipo de envío" uses); every other line is ERP, an unknown shipping too, which is also counted apart
(`sin_envio`) so the view can say so. ERP is the window's units minus Full, so ERP + Full is the window's total.

The sales (`test_board_por_tipo_envio_postgres.shipped`, today Sep 30): MLA sells A (x2, Flex, today) and C (x7, no
shipment, tagged `no_shipping`, Sep 27), and 1 unit of pack P by Full (Sep 20); OTHER sells 2 units of pack P by
Full and 1 by Colecta (Sep 20). The 7d window starts Sep 24.
"""

# ruff: noqa: F811 -- the imported fixtures are used by name

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.services.ml_daily_metrics import board
from tests.services.ml_daily_metrics.test_board_operaciones_postgres import PERIOD, _env  # noqa: F401
from tests.services.ml_daily_metrics.test_board_por_tipo_envio_postgres import sales, shipped  # noqa: F401
from tests.services.ml_daily_metrics.test_board_postgres import MLA, OTHER

pytestmark = pytest.mark.postgres


def _split(db) -> tuple[dict, dict]:
    with board.Board(db, board.BoardFilter(**PERIOD, group_by="publication"), scope_pairs=None) as b:
        split = b.units_by_fulfillment()
        rows = {r.mla: r.windows for r in b.rows_for_keys([MLA, OTHER])}
    return split, rows


def test_full_is_the_fulfillment_lines_and_erp_the_rest(shipped) -> None:
    split, _ = _split(shipped)

    assert split[MLA] == board.ShippingSplit(full_7d=0, full_30d=1, erp_7d=9, erp_30d=9, unknown_7d=0, unknown_30d=0)
    assert split[OTHER] == board.ShippingSplit(full_7d=0, full_30d=2, erp_7d=0, erp_30d=1, unknown_7d=0, unknown_30d=0)


def test_erp_plus_full_is_the_publications_window(shipped) -> None:
    split, windows = _split(shipped)

    for mla in (MLA, OTHER):
        assert split[mla].erp_7d + split[mla].full_7d == windows[mla]["7d"]
        assert split[mla].erp_30d + split[mla].full_30d == windows[mla]["30d"]


def test_an_unknown_shipping_is_erp_and_counted_apart(shipped, request) -> None:
    # Only the persisted lines outlive their order row: that line's shipping is unknown, and it is ERP.
    shipped.execute(text("DELETE FROM ml_orders_ops WHERE order_id = 2000012345678913"))
    shipped.flush()

    split, windows = _split(shipped)

    if request.node.callspec.params["sales"] == "persisted":
        assert split[MLA] == board.ShippingSplit(
            full_7d=0, full_30d=1, erp_7d=9, erp_30d=9, unknown_7d=7, unknown_30d=7
        )
    else:
        assert split[MLA] == board.ShippingSplit(
            full_7d=0, full_30d=1, erp_7d=2, erp_30d=2, unknown_7d=0, unknown_30d=0
        )
    assert split[MLA].erp_30d + split[MLA].full_30d == windows[MLA]["30d"]


def test_a_publication_without_sales_in_the_windows_has_no_split(shipped) -> None:
    with board.Board(
        shipped, board.BoardFilter(**PERIOD, group_by="publication", marcas=("Logi",)), scope_pairs=None
    ) as b:
        split = b.units_by_fulfillment()

    assert MLA not in split
    assert split[OTHER].full_30d == 2
