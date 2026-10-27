"""The configured treatment of ML tax charges, by period (ventas-ml-impuestos-informativos S1, S2).

`TaxTreatment.load` reads every version of `ml_venta_impuesto_tratamiento` once, plus the sale date of the orders
being computed, and answers per order and charge name whether a version says the charge is informational. `None`
means no version covers that sale, and the caller keeps the built-in rule
(`breakdown_service.is_recoverable_withholding`). The rule itself lives in `breakdown_service.informational_rule`,
the one place every neto path asks.

A version applies when `fecha_desde <= sale date <= fecha_hasta` (open-ended when `fecha_hasta` is NULL), the sale
date being `ml_orders_ops.date_created`, and when two versions cover the same day the latest `fecha_desde` wins:
the same resolution as `% de varios` (`deducciones.VariosDeduccion.resolve_bulk`), whose endpoint also closes the
previous version on the new one's start day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.models.ml_orders_ops import MlOrdersOps
from app.models.ml_venta_impuesto_tratamiento import ImpuestoTratamientoVenta

# (fecha_desde, fecha_hasta, informativo), ascending by fecha_desde.
_Version = Tuple[date, Optional[date], bool]


@dataclass(frozen=True)
class TaxTreatment:
    versions_by_name: Dict[str, List[_Version]] = field(default_factory=dict)
    sale_dates: Dict[int, date] = field(default_factory=dict)

    @classmethod
    def load(cls, db: Session, order_ids: Sequence[int]) -> "TaxTreatment":
        """Every configured version, and the sale date of `order_ids` (skipped when nothing is configured)."""
        versions_by_name: Dict[str, List[_Version]] = {}
        rows = db.query(ImpuestoTratamientoVenta).order_by(ImpuestoTratamientoVenta.fecha_desde.asc()).all()
        for row in rows:
            versions_by_name.setdefault(row.charge_name, []).append((row.fecha_desde, row.fecha_hasta, row.informativo))
        sale_dates: Dict[int, date] = {}
        if versions_by_name and order_ids:
            orders = (
                db.query(MlOrdersOps.order_id, MlOrdersOps.date_created)
                .filter(MlOrdersOps.order_id.in_(list(order_ids)))
                .all()
            )
            for order_id, date_created in orders:
                if date_created is not None:
                    sale_dates[order_id] = date_created.date() if hasattr(date_created, "date") else date_created
        return cls(versions_by_name, sale_dates)

    def informativo(self, order_id: int, charge_name: Optional[str]) -> Optional[bool]:
        """What the version in force at the order's sale date says about `charge_name`, or `None` when none does."""
        sold_on = self.sale_dates.get(order_id)
        return None if sold_on is None else self.informativo_on(charge_name, sold_on)

    def informativo_on(self, charge_name: Optional[str], day: date) -> Optional[bool]:
        """What the version of `charge_name` in force on `day` says, or `None` when none is."""
        answer: Optional[bool] = None
        for desde, hasta, informativo in self.versions_by_name.get(charge_name or "", []):
            if desde <= day and (hasta is None or hasta >= day):
                answer = informativo
        return answer
