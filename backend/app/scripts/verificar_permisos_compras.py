"""
Verificación de permisos del módulo compras (COMPRAS-8.2).

A diferencia de `verify_compras_pre_deploy.py` (pre-deploy gate genérico),
este script lista con detalle:

  - Qué usuarios/roles tienen cada permiso crítico del módulo.
  - Instrucciones accionables si alguno falta.

Puede correr ANTES o DESPUÉS del deploy. Es informativo, no muta nada.

Uso:
    python -m app.scripts.verificar_permisos_compras
    python -m app.scripts.verificar_permisos_compras --permiso administracion.aprobar_ordenes_compra

Idempotente (solo lee). Exit code 0 siempre, salvo que los permisos críticos
no existan en la tabla `permisos` (ahí retorna 1).

Referencias:
  - tasks.md COMPRAS-8.2
  - proposal.md R8 (permisos críticos sin asignación default)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.permiso import Permiso, RolPermisoBase, UsuarioPermisoOverride  # noqa: E402
from app.models.rol import Rol  # noqa: E402
from app.models.usuario import Usuario  # noqa: E402

PERMISOS_MODULO = (
    "administracion.ver_ordenes_compra",
    "administracion.gestionar_ordenes_compra",
    "administracion.aprobar_ordenes_compra",
    "administracion.ejecutar_pagos",
    "administracion.ver_cuentas_corrientes",
    "administracion.gestionar_cuentas_corrientes",
)

PERMISOS_CRITICOS = {
    "administracion.aprobar_ordenes_compra",
    "administracion.ejecutar_pagos",
}

INSTRUCCIONES_ASIGNACION = """
Para asignar los permisos críticos:

1. Abrir /admin/usuarios en el frontend con un usuario SUPERADMIN.
2. Para cada rol que deba tener el permiso:
   - Click en "Gestionar permisos base del rol"
   - Seleccionar el rol (ej: GERENTE para aprobar, ADMIN para ejecutar pagos)
   - Marcar el permiso en la categoría "Administración / Administración sector"
   - Guardar.
3. Alternativa por usuario individual (override):
   - Ir al detalle del usuario
   - Click en "Permisos"
   - Marcar el permiso concedido=true con motivo (auditoría)

CRITERIO ORGANIZACIONAL (proposal.md R8, REQ-PED-005):
  - NO asignar ambos permisos al mismo usuario si se quiere evitar
    auto-aprobación (técnicamente v1 no lo bloquea, pero es buena práctica
    de control interno).
  - Recomendado:
    * aprobar_ordenes_compra → rol GERENTE o ADMIN de compras
    * ejecutar_pagos        → rol ADMIN de tesorería o CFO
"""


def _listar_roles_con_permiso(session: Session, permiso_id: int) -> list[str]:
    rows = session.execute(
        select(Rol.nombre)
        .join(RolPermisoBase, RolPermisoBase.rol_id == Rol.id)
        .where(RolPermisoBase.permiso_id == permiso_id)
        .order_by(Rol.nombre)
    ).all()
    return [r[0] for r in rows]


def _listar_usuarios_con_override(session: Session, permiso_id: int) -> list[tuple[str, bool]]:
    """Retorna (username, concedido)."""
    rows = session.execute(
        select(Usuario.username, UsuarioPermisoOverride.concedido)
        .join(UsuarioPermisoOverride, UsuarioPermisoOverride.usuario_id == Usuario.id)
        .where(UsuarioPermisoOverride.permiso_id == permiso_id)
        .order_by(Usuario.username)
    ).all()
    return [(r[0], r[1]) for r in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description="Listado de permisos del módulo compras")
    parser.add_argument(
        "--permiso",
        help="Filtrar por código de permiso específico (ej: administracion.aprobar_ordenes_compra)",
    )
    args = parser.parse_args()

    permisos_a_chequear = (args.permiso,) if args.permiso else PERMISOS_MODULO

    session = SessionLocal()
    exit_code = 0
    faltan_asignaciones_criticas: list[str] = []

    try:
        print("=" * 70)
        print("VERIFICACIÓN DE PERMISOS — MÓDULO COMPRAS")
        print("=" * 70)

        for codigo in permisos_a_chequear:
            permiso = session.execute(select(Permiso).where(Permiso.codigo == codigo)).scalar_one_or_none()

            critico_tag = " [CRÍTICO]" if codigo in PERMISOS_CRITICOS else ""
            print(f"\n▸ {codigo}{critico_tag}")

            if permiso is None:
                print("    ❌ NO EXISTE en tabla `permisos`")
                print("       → Correr `alembic upgrade head` (migración compras_010)")
                exit_code = 1
                continue

            print(f"    id={permiso.id} | nombre='{permiso.nombre}' | es_critico={permiso.es_critico}")

            roles = _listar_roles_con_permiso(session, permiso.id)
            if roles:
                print(f"    Roles con permiso ({len(roles)}): {', '.join(roles)}")
            else:
                print("    Roles con permiso: NINGUNO")

            overrides = _listar_usuarios_con_override(session, permiso.id)
            if overrides:
                concedidos = [u for u, c in overrides if c]
                revocados = [u for u, c in overrides if not c]
                if concedidos:
                    print(f"    Usuarios con override + ({len(concedidos)}): {', '.join(concedidos)}")
                if revocados:
                    print(f"    Usuarios con override - ({len(revocados)}): {', '.join(revocados)}")
            else:
                print("    Usuarios con override: NINGUNO")

            # Flag operativo: crítico sin asignación
            if codigo in PERMISOS_CRITICOS and not roles and not any(c for _, c in overrides):
                faltan_asignaciones_criticas.append(codigo)
                print(
                    f"    ⚠ El permiso crítico '{codigo}' NO está asignado a ningún rol "
                    "ni usuario. El módulo queda operativamente bloqueado."
                )

        if faltan_asignaciones_criticas:
            print("\n" + "=" * 70)
            print("ACCIÓN REQUERIDA")
            print("=" * 70)
            print(
                "Los siguientes permisos críticos no tienen asignación y deben "
                "configurarse desde el panel admin tras el deploy:\n"
            )
            for c in faltan_asignaciones_criticas:
                print(f"  - {c}")
            print(INSTRUCCIONES_ASIGNACION)
        else:
            print("\n" + "=" * 70)
            print("✅ Todos los permisos críticos tienen al menos una asignación.")
            print("=" * 70)

        return exit_code
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
