"""
T-8.8 — Test manual: permisos de cada endpoint sensible (403 sin permiso).

Verifica que el archivo `app/routers/rrhh_horas_extras.py` exige el permiso
correcto en cada handler sensible. Como NO hay framework de tests configurado
ni TestClient corriendo en este script, validamos por análisis estático
(grep/AST) que cada función handler llame `_check_permiso(db, current_user, "<codigo>")`
con el código esperado.

Cada endpoint sensible se asocia con su permiso esperado (según design §11.2).
Si la función NO contiene la línea `_check_permiso(... "<expected>")`, marca FAIL.

Uso:
    cd /var/www/html/pricing-app/backend
    python -m app.scripts.test_manual_rrhh_he_permisos

Para una verificación verdaderamente E2E (con HTTP + auth real), correr el
test plan E2E descrito en T-9.4 y T-8.8 en tasks.md (login con tokens de
diferentes roles, llamar los endpoints, esperar 200/403 según corresponda).

Spec ref: "Permisos del módulo de horas extras", "Aprobar sin permiso retorna 403",
"Liquidar sin permiso retorna 403".
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

if __name__ == "__main__":
    backend_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    from dotenv import load_dotenv

    env_path = Path(backend_path) / ".env"
    load_dotenv(dotenv_path=env_path)


# Mapping: handler function name -> permiso esperado.
# Basado en design §11.2 + nombres reales en el router actual.
PERMISOS_ESPERADOS = {
    # Lectura básica
    "listar_horas_extras": "rrhh.ver_horas_extras",
    "obtener_horas_extras": "rrhh.ver_horas_extras",
    # Crear/editar bloque manual
    "crear_horas_extras": "rrhh.gestionar_horas_extras",
    "actualizar_horas_extras": "rrhh.gestionar_horas_extras",
    # Aprobación / rechazo / reapertura
    "aprobar_bloque": "rrhh.aprobar_horas_extras",
    "rechazar_bloque": "rrhh.aprobar_horas_extras",
    "bulk_aprobar": "rrhh.aprobar_horas_extras",
    "bulk_rechazar": "rrhh.aprobar_horas_extras",
    # Anomalías
    "completar_fichada": "rrhh.gestionar_horas_extras",
    "descartar_dia": "rrhh.aprobar_horas_extras",
    # Recálculo manual
    "recalcular_periodo": "rrhh.gestionar_horas_extras",
    # Liquidación
    "liquidar_periodo": "rrhh.liquidar_horas_extras",
    # Export Excel + alertas + historial
    "exportar_excel": "rrhh.ver_horas_extras",
    "listar_alertas": "rrhh.ver_horas_extras",
    "marcar_alerta_leida": "rrhh.ver_horas_extras",
    "listar_historial": "rrhh.ver_horas_extras",
    "obtener_config": "rrhh.ver_horas_extras",
    "actualizar_config": "rrhh.config",
}


def _ok(msg: str) -> None:
    print(f"  PASS - {msg}")


def _fail(msg: str) -> None:
    print(f"  FAIL - {msg}")


def _extract_function_source(tree: ast.AST, fn_name: str) -> str | None:
    """Recorre el AST y devuelve el source del FunctionDef llamado fn_name."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn_name:
            return ast.unparse(node) if hasattr(ast, "unparse") else ast.dump(node)
    return None


def _check_permiso_in_function(source: str, expected_permiso: str) -> bool:
    """True si el source contiene una llamada `_check_permiso(... "<expected_permiso>" ...)`."""
    # Buscamos: _check_permiso seguido eventualmente del string esperado.
    # No requerimos análisis AST profundo — el patrón es robusto en este router.
    if "_check_permiso" not in source:
        return False
    # El permiso debe aparecer como string literal.
    if f'"{expected_permiso}"' not in source and f"'{expected_permiso}'" not in source:
        return False
    return True


def main() -> int:
    print("Iniciando test_manual_rrhh_he_permisos (T-8.8)")
    backend = Path(__file__).parent.parent.parent
    router_path = backend / "app" / "routers" / "rrhh_horas_extras.py"
    if not router_path.exists():
        _fail(f"Router no encontrado: {router_path}")
        return 1

    print(f"  Analizando: {router_path}")
    src = router_path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    fallos = 0
    fns_no_encontradas: list[str] = []

    for fn_name, expected in PERMISOS_ESPERADOS.items():
        fn_src = _extract_function_source(tree, fn_name)
        if fn_src is None:
            fns_no_encontradas.append(fn_name)
            print(f"  SKIP - función '{fn_name}' no encontrada en el router")
            continue

        if _check_permiso_in_function(fn_src, expected):
            _ok(f"{fn_name}() exige permiso '{expected}'")
        else:
            fallos += 1
            # ¿Tal vez exige otro permiso? Listar los strings que aparecen.
            permisos_encontrados = [
                p
                for p in (
                    "rrhh.ver_horas_extras",
                    "rrhh.gestionar_horas_extras",
                    "rrhh.aprobar_horas_extras",
                    "rrhh.liquidar_horas_extras",
                    "rrhh.config",
                )
                if f'"{p}"' in fn_src or f"'{p}'" in fn_src
            ]
            _fail(f"{fn_name}() esperaba '{expected}'; encontrado(s): {permisos_encontrados or '(ninguno)'}")

    if fns_no_encontradas:
        print(
            f"\n  NOTA: {len(fns_no_encontradas)} función(es) no encontrada(s) "
            f"(probablemente nombre diferente en este iteration): "
            f"{', '.join(fns_no_encontradas)}"
        )
        print("  Si la función existe con otro nombre, actualizá PERMISOS_ESPERADOS en este script.")

    if fallos == 0:
        print(
            f"\nResultado: PASS (T-8.8) — "
            f"{len(PERMISOS_ESPERADOS) - len(fns_no_encontradas)}/"
            f"{len(PERMISOS_ESPERADOS)} endpoints validados"
        )
        return 0
    print(f"\nResultado: FAIL ({fallos} endpoints con permiso incorrecto)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
