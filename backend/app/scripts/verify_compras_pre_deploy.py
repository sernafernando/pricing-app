"""
Pre-deploy check para modulo-compras (COMPRAS-8.1).

Ejecutar ANTES del deploy a producción. Si algún check CRÍTICO falla,
aborta el deploy (exit != 0). Los checks WARNING no bloquean pero
imprimen recomendaciones.

Uso:
    python -m app.scripts.verify_compras_pre_deploy
    python -m app.scripts.verify_compras_pre_deploy --dry-run   # no commits

Idempotente: safe to re-run. Las acciones auto-remediadoras
(crear caja USD faltante) usan INSERT ... WHERE NOT EXISTS semántica
via check previo en SQLAlchemy.

Referencias:
  - tasks.md COMPRAS-8.1, COMPRAS-8.2
  - design.md RD7 (caja USD obligatoria por empresa)
  - proposal.md R8 (permisos críticos sin asignación default)
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.compras_empresa_erp_map import EMPRESA_A_COMP_BRA_MAP  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.core.logging import get_logger  # noqa: E402
from app.models.caja import Caja  # noqa: E402
from app.models.commercial_transaction import CommercialTransaction  # noqa: E402
from app.models.empresa import Empresa  # noqa: E402
from app.models.permiso import Permiso, RolPermisoBase, UsuarioPermisoOverride  # noqa: E402
from app.models.tb_sale_document import SaleDocument  # noqa: E402

logger = get_logger("scripts.verify_compras_pre_deploy")


# ──────────────────────────────────────────────────────────────────────────
# Constantes
# ──────────────────────────────────────────────────────────────────────────

PERMISOS_CRITICOS_NUEVOS = (
    "administracion.aprobar_ordenes_compra",
    "administracion.ejecutar_pagos",
)

PERMISOS_MODULO = (
    "administracion.ver_ordenes_compra",
    "administracion.gestionar_ordenes_compra",
    "administracion.aprobar_ordenes_compra",
    "administracion.ejecutar_pagos",
    "administracion.ver_cuentas_corrientes",
    "administracion.gestionar_cuentas_corrientes",
)

MIN_SALE_DOCUMENT_ROWS = 43  # seed estático COMPRAS-1.2b

SYNC_ERP_FRESHNESS_DIAS = 2


class CheckFailed(Exception):
    """Check crítico falló — aborta el deploy."""


# ──────────────────────────────────────────────────────────────────────────
# Check 1 — Cajas USD por empresa (CRÍTICO, auto-remedia)
# ──────────────────────────────────────────────────────────────────────────


def verificar_cajas_usd_por_empresa(session: Session, dry_run: bool = False) -> None:
    """
    RD7: cada empresa con mapeo ERP debe tener al menos 1 caja USD activa.

    Si alguna falta, la crea automáticamente con saldo_inicial=0.
    Sin esto, pagar una OP en USD explotaría con 422 OP_CAJA_MONEDA_MISMATCH.
    """
    empresas_mapeadas = sorted(EMPRESA_A_COMP_BRA_MAP.keys())
    empresas = (
        session.execute(select(Empresa).where(Empresa.id.in_(empresas_mapeadas), Empresa.activo.is_(True)))
        .scalars()
        .all()
    )

    if not empresas:
        raise CheckFailed(
            f"Ninguna empresa activa con id en {empresas_mapeadas} (ver EMPRESA_A_COMP_BRA_MAP). Revisar configuración."
        )

    creadas: list[tuple[int, str]] = []
    ya_tenian: list[tuple[int, str]] = []

    for empresa in empresas:
        existing = session.execute(
            select(func.count())
            .select_from(Caja)
            .where(
                Caja.empresa_id == empresa.id,
                Caja.moneda == "USD",
                Caja.activo.is_(True),
            )
        ).scalar_one()

        if existing > 0:
            ya_tenian.append((empresa.id, empresa.nombre))
            continue

        caja = Caja(
            nombre=f"Caja USD {empresa.nombre}",
            empresa_id=empresa.id,
            moneda="USD",
            saldo_inicial=Decimal("0.00"),
            saldo_actual=Decimal("0.00"),
            activo=True,
        )
        if not dry_run:
            session.add(caja)
            session.flush()
        creadas.append((empresa.id, empresa.nombre))
        logger.info(
            "caja_usd_creada",
            extra={"empresa_id": empresa.id, "empresa_nombre": empresa.nombre, "dry_run": dry_run},
        )

    print(
        f"    Empresas evaluadas: {len(empresas)} | "
        f"con caja USD preexistente: {len(ya_tenian)} | "
        f"creadas: {len(creadas)} {'(DRY RUN)' if dry_run else ''}"
    )
    for emp_id, nombre in creadas:
        print(f"      + Caja USD {nombre} (empresa_id={emp_id})")

    # Smoke post-seed
    if not dry_run:
        faltantes = (
            session.execute(
                select(Empresa.id, Empresa.nombre).where(
                    Empresa.id.in_(empresas_mapeadas),
                    Empresa.activo.is_(True),
                    ~Empresa.id.in_(select(Caja.empresa_id).where(Caja.moneda == "USD", Caja.activo.is_(True))),
                )
            )
        ).all()
        if faltantes:
            raise CheckFailed(f"Post-seed smoke: empresas SIN caja USD activa: {list(faltantes)}")


# ──────────────────────────────────────────────────────────────────────────
# Check 2 — Seeds del módulo (CRÍTICO)
# ──────────────────────────────────────────────────────────────────────────


def verificar_seeds_compras(session: Session, dry_run: bool = False) -> None:  # noqa: ARG001
    """
    Verifica que los seeds estáticos del módulo hayan corrido.

    - tb_sale_document debe tener >= 43 filas (COMPRAS-1.2b).
    - Permisos nuevos deben existir con es_critico=True.
    """
    # Seed tb_sale_document
    total_sd = session.execute(select(func.count()).select_from(SaleDocument)).scalar_one()
    if total_sd < MIN_SALE_DOCUMENT_ROWS:
        raise CheckFailed(
            f"tb_sale_document tiene {total_sd} filas, esperado >= {MIN_SALE_DOCUMENT_ROWS} "
            f"(ver migración compras_009_seed_tb_sale_document). "
            "Correr `alembic upgrade head` antes del deploy."
        )

    # Permisos críticos nuevos
    permisos_encontrados = (
        session.execute(select(Permiso).where(Permiso.codigo.in_(PERMISOS_CRITICOS_NUEVOS))).scalars().all()
    )
    if len(permisos_encontrados) != len(PERMISOS_CRITICOS_NUEVOS):
        codigos_encontrados = {p.codigo for p in permisos_encontrados}
        faltantes = set(PERMISOS_CRITICOS_NUEVOS) - codigos_encontrados
        raise CheckFailed(
            f"Permisos críticos faltantes en tabla `permisos`: {sorted(faltantes)}. "
            "Correr migración compras_010_seed_permisos_compras."
        )
    no_criticos = [p.codigo for p in permisos_encontrados if not p.es_critico]
    if no_criticos:
        raise CheckFailed(f"Permisos nuevos sin es_critico=true: {no_criticos}. Esto es un bug del seed.")

    print(f"    tb_sale_document: {total_sd} filas | permisos críticos nuevos: {len(permisos_encontrados)}/2 presentes")


# ──────────────────────────────────────────────────────────────────────────
# Check 3 — Permisos asignados (WARNING, no bloqueante)
# ──────────────────────────────────────────────────────────────────────────


def verificar_permisos_asignados(session: Session, dry_run: bool = False) -> None:  # noqa: ARG001
    """
    WARNING: si los permisos críticos no están asignados a ningún rol ni usuario,
    el módulo queda bloqueado operativamente tras el deploy.

    NO bloquea el deploy porque la asignación debe hacerla el admin manualmente
    DESPUÉS del deploy (R8 del proposal — sin asignación default).
    """
    warnings: list[str] = []
    for codigo in PERMISOS_CRITICOS_NUEVOS:
        permiso = session.execute(select(Permiso).where(Permiso.codigo == codigo)).scalar_one_or_none()
        if permiso is None:
            warnings.append(f"  permiso '{codigo}' no existe (ver check 2)")
            continue

        roles_count = session.execute(
            select(func.count()).select_from(RolPermisoBase).where(RolPermisoBase.permiso_id == permiso.id)
        ).scalar_one()

        users_count = session.execute(
            select(func.count())
            .select_from(UsuarioPermisoOverride)
            .where(
                UsuarioPermisoOverride.permiso_id == permiso.id,
                UsuarioPermisoOverride.concedido.is_(True),
            )
        ).scalar_one()

        if roles_count == 0 and users_count == 0:
            warnings.append(
                f"  permiso '{codigo}' sin asignación a ningún rol ni usuario "
                "(esperado pre-deploy; asignar manualmente en /admin)"
            )

    if warnings:
        print("    ⚠ WARNING (no bloqueante):")
        for w in warnings:
            print(w)
        print(
            "    → Post-deploy: asignar desde /admin/usuarios a los roles correspondientes:\n"
            "      - administracion.aprobar_ordenes_compra → rol aprobadores (ej: GERENTE)\n"
            "      - administracion.ejecutar_pagos        → rol tesorería (ej: ADMIN)"
        )
    else:
        print("    Todos los permisos críticos tienen asignación.")


# ──────────────────────────────────────────────────────────────────────────
# Check 4 — Sync ERP reciente (WARNING si se queda atrás)
# ──────────────────────────────────────────────────────────────────────────


def verificar_sync_erp_reciente(session: Session, dry_run: bool = False) -> None:  # noqa: ARG001
    """
    El hook de matching ERP depende de que `tb_commercial_transactions`
    esté sincronizado. Si MAX(ct_date) < today - 2, el sync se quedó atrás
    y el matching inline no tiene datos frescos para matchear.

    WARNING (no bloqueante): el admin puede desear deployar igual
    y arrancar el sync después.
    """
    max_ct_date = session.execute(select(func.max(CommercialTransaction.ct_date))).scalar_one()
    if max_ct_date is None:
        print("    ⚠ WARNING: tb_commercial_transactions está VACÍA. ¿Primer deploy?")
        return

    max_date = max_ct_date.date() if hasattr(max_ct_date, "date") else max_ct_date
    hoy = date.today()
    gap_dias = (hoy - max_date).days

    if gap_dias > SYNC_ERP_FRESHNESS_DIAS:
        print(
            f"    ⚠ WARNING: MAX(ct_date) = {max_date.isoformat()} "
            f"(gap={gap_dias} días, umbral={SYNC_ERP_FRESHNESS_DIAS}). "
            "El cron sync_commercial_transactions_guid.py puede estar detenido."
        )
    else:
        print(f"    MAX(ct_date) = {max_date.isoformat()} (gap={gap_dias} días, OK)")


# ──────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-deploy checks modulo-compras")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="No hacer commits (solo chequear + simular acciones).",
    )
    args = parser.parse_args()

    session = SessionLocal()
    checks = [
        ("Cajas USD por empresa [CRÍTICO]", verificar_cajas_usd_por_empresa),
        ("Seeds compras [CRÍTICO]", verificar_seeds_compras),
        ("Permisos asignados [WARNING]", verificar_permisos_asignados),
        ("Sync ERP reciente [WARNING]", verificar_sync_erp_reciente),
    ]
    try:
        for nombre, fn in checks:
            print(f"[CHECK] {nombre}...")
            fn(session, dry_run=args.dry_run)
            print("  ✓ OK")

        if args.dry_run:
            session.rollback()
            print("\n✅ Pre-deploy checks PASSED (DRY RUN — no commits)")
        else:
            session.commit()
            print("\n✅ Pre-deploy checks PASSED")
        return 0
    except CheckFailed as e:
        session.rollback()
        print(f"\n❌ Pre-deploy check FAILED: {e}", file=sys.stderr)
        print(
            "   → ABORT deploy, corregir el problema y re-correr.",
            file=sys.stderr,
        )
        return 1
    except Exception as e:
        session.rollback()
        print(f"\n❌ Error inesperado durante pre-deploy check: {e}", file=sys.stderr)
        return 2
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
