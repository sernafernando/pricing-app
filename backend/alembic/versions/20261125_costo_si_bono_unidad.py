"""costo SI: a per-unit sell-in line queues its products too

Revision ID: 20261125_costo_si_bono_unidad
Revises: 20261125_costo_si_drop_full
Create Date: 2026-11-20

Costo SI now takes every sell-in line of the sale-cost kind, % or per unit, with its topes (L4.2: "si algo se cargo
por sell in, es sell in, no se discute"). `costo_si_encolar_bono` queued only the % ones: it now queues a per-unit
line's products as well. Only that function changes; the downgrade restores the previous body.
"""

from typing import Union

from alembic import op

revision: str = "20261125_costo_si_bono_unidad"
down_revision: Union[str, None] = "20261125_costo_si_drop_full"
branch_labels = None
depends_on = None

# Frozen copies of `queue._BONO`: now, and as `20261125_costo_si` created it.
BONO_SQL = "\nCREATE OR REPLACE FUNCTION costo_si_encolar_bono(r sell_in_bonos_marca) RETURNS void AS $f$\nBEGIN\n    IF r.base = 'costo_venta' AND r.tipo IN ('porcentaje', 'por_unidad') THEN\n        PERFORM costo_si_encolar(p.item_id, r.fecha_desde)\n        FROM productos_erp p\n        WHERE (r.alcance = 'marca' AND p.marca = r.marca AND (r.categoria IS NULL OR p.categoria = r.categoria))\n           OR (r.alcance = 'categoria' AND p.categoria = r.categoria)\n           OR (r.alcance = 'modelos' AND p.item_id IN (SELECT bi.item_id FROM sell_in_bono_items bi WHERE bi.bono_id = r.id));\n    END IF;\nEND\n$f$ LANGUAGE plpgsql;\n\nCREATE OR REPLACE FUNCTION costo_si_trg_bono() RETURNS TRIGGER AS $t$\nBEGIN\n    IF TG_OP <> 'INSERT' THEN\n        PERFORM costo_si_encolar_bono(OLD);\n    END IF;\n    IF TG_OP <> 'DELETE' THEN\n        PERFORM costo_si_encolar_bono(NEW);\n    END IF;\n    RETURN NULL;\nEND\n$t$ LANGUAGE plpgsql\n"

BONO_SQL_ANTERIOR = "\nCREATE OR REPLACE FUNCTION costo_si_encolar_bono(r sell_in_bonos_marca) RETURNS void AS $f$\nBEGIN\n    IF r.base = 'costo_venta' AND r.tipo = 'porcentaje' THEN\n        PERFORM costo_si_encolar(p.item_id, r.fecha_desde)\n        FROM productos_erp p\n        WHERE (r.alcance = 'marca' AND p.marca = r.marca AND (r.categoria IS NULL OR p.categoria = r.categoria))\n           OR (r.alcance = 'categoria' AND p.categoria = r.categoria)\n           OR (r.alcance = 'modelos' AND p.item_id IN (SELECT bi.item_id FROM sell_in_bono_items bi WHERE bi.bono_id = r.id));\n    END IF;\nEND\n$f$ LANGUAGE plpgsql;\n\nCREATE OR REPLACE FUNCTION costo_si_trg_bono() RETURNS TRIGGER AS $t$\nBEGIN\n    IF TG_OP <> 'INSERT' THEN\n        PERFORM costo_si_encolar_bono(OLD);\n    END IF;\n    IF TG_OP <> 'DELETE' THEN\n        PERFORM costo_si_encolar_bono(NEW);\n    END IF;\n    RETURN NULL;\nEND\n$t$ LANGUAGE plpgsql\n"


def upgrade() -> None:
    op.execute(BONO_SQL)


def downgrade() -> None:
    op.execute(BONO_SQL_ANTERIOR)
