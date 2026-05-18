"""
Garantiza que todo permiso referenciado en código (frontend + backend) esté
definido por una migración Alembic, y avisa de permisos definidos en
migraciones que ya no se usan en ningún lado.

La fuente de verdad de los permisos es la DB (poblada por migraciones
Alembic individuales). Este test parsea ambos lados estáticamente — no
necesita DB ni Node — y previene el caso real que motivó su existencia:
referenciar un código de permiso que en realidad no existe (o que existe
pero significa otra cosa), generando bugs silenciosos donde un rol ve algo
que no debería o donde un check siempre cae a False sin que nadie note.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "backend"
FRONTEND_SRC = REPO_ROOT / "frontend" / "src"
MIGRATIONS_DIR = BACKEND_ROOT / "alembic" / "versions"

PERMISO_CODE_RE = r"[a-z][a-z0-9_]+\.[a-z][a-z0-9_]+"

# Refs de frontend (JS/JSX) — uno por patrón
_FE_PATTERNS = [
    # tienePermiso('x.y') / tienePermiso("x.y")
    re.compile(r"""tienePermiso\(\s*['"](""" + PERMISO_CODE_RE + r""")['"]"""),
    # permiso="x.y" en JSX props
    re.compile(r"""\bpermiso\s*=\s*['"](""" + PERMISO_CODE_RE + r""")['"]"""),
    # permiso: 'x.y' en config objects (Sidebar)
    re.compile(r"""\bpermiso\s*:\s*['"](""" + PERMISO_CODE_RE + r""")['"]"""),
]

# tieneAlgunPermiso / tieneTodosPermisos toman array — extraemos strings adentro
_FE_ARRAY_FN = re.compile(
    r"""(?:tieneAlgunPermiso|tieneTodosPermisos)\s*\(\s*\[([^\]]+)\]""",
    re.DOTALL,
)
_QUOTED_CODE = re.compile(r"""['"](""" + PERMISO_CODE_RE + r""")['"]""")

# Refs de backend (Python)
_BE_PATTERNS = [
    # verificar_permiso(db, user, "x.y")
    re.compile(r"""verificar_permiso\([^)]*?['"](""" + PERMISO_CODE_RE + r""")['"]"""),
    # PermisoRequerido("x.y")
    re.compile(r"""PermisoRequerido\(\s*['"](""" + PERMISO_CODE_RE + r""")['"]"""),
    # @requiere_permiso("x.y")
    re.compile(r"""@requiere_permiso\(\s*['"](""" + PERMISO_CODE_RE + r""")['"]"""),
]

# Migraciones — formatos de definición de permisos que conviven en alembic/versions/:
#   1. SQL multi-row:  VALUES ('codigo', 'nombre', ...), ('codigo2', ...), ...
#   2. Listas Python:  PERMISOS = [("codigo", "Label", ...), ...]
#   3. Tuplas inline:  ("codigo", "Label", "descripcion", ...)
#   4. Dicts:          {"codigo": "x.y", "nombre": "..."}
#   5. Constante:      CODIGO = "x.y"  (seguida de su INSERT más abajo)
_PATTERNS_INSERT = [
    # (1)(2)(3) "primer elemento de tupla"
    re.compile(r"""\(\s*['"](""" + PERMISO_CODE_RE + r""")['"]\s*,"""),
    # (4) dict con clave "codigo"
    re.compile(r"""['"]codigo['"]\s*:\s*['"](""" + PERMISO_CODE_RE + r""")['"]"""),
    # (5) constante Python al tope del módulo
    re.compile(r"""^\s*CODIGO\s*=\s*['"](""" + PERMISO_CODE_RE + r""")['"]""", re.MULTILINE),
]
_DELETE_PERMISO = re.compile(
    r"""DELETE\s+FROM\s+permisos\s+WHERE\s+codigo\s*=\s*['"](""" + PERMISO_CODE_RE + r""")['"]""",
    re.IGNORECASE,
)
# Heurística para evitar falsos positivos: solo contamos códigos extraídos
# de migraciones que mencionen explícitamente la tabla permisos.
_MENCIONA_TABLA_PERMISOS = re.compile(r"\bpermisos\b", re.IGNORECASE)


def _split_upgrade_downgrade(text: str) -> tuple[str, str]:
    """Separa el cuerpo de upgrade() y downgrade() en un archivo de migración.

    Solo el bloque de upgrade refleja lo que efectivamente vive en producción.
    Los DELETE de downgrade() son operaciones de rollback que casi nunca corren.
    """
    # Heurística simple: cortar en la primera línea que define downgrade()
    m = re.search(r"^def\s+downgrade\s*\(", text, re.MULTILINE)
    if m:
        return text[: m.start()], text[m.start() :]
    return text, ""


def _scan_migrations() -> set[str]:
    """Conjunto efectivo de códigos de permiso definidos por migraciones.

    Solo considera migraciones que mencionan la tabla `permisos` y solo
    inspecciona el cuerpo de upgrade() (los DELETE de downgrade no aplican
    en producción).
    """
    inserted: set[str] = set()
    deleted: set[str] = set()
    for mig in MIGRATIONS_DIR.glob("*.py"):
        text = mig.read_text(encoding="utf-8")
        if not _MENCIONA_TABLA_PERMISOS.search(text):
            continue
        upgrade_body, _ = _split_upgrade_downgrade(text)
        for pat in _PATTERNS_INSERT:
            inserted.update(pat.findall(upgrade_body))
        deleted.update(_DELETE_PERMISO.findall(upgrade_body))
    return inserted - deleted


def _scan_frontend_refs() -> dict[str, set[str]]:
    """{ permiso_code: set(archivos) } para refs en frontend."""
    refs: dict[str, set[str]] = {}
    for ext in ("*.js", "*.jsx", "*.ts", "*.tsx"):
        for path in FRONTEND_SRC.rglob(ext):
            text = path.read_text(encoding="utf-8", errors="ignore")
            rel = str(path.relative_to(REPO_ROOT))
            for pat in _FE_PATTERNS:
                for code in pat.findall(text):
                    refs.setdefault(code, set()).add(rel)
            for arr in _FE_ARRAY_FN.findall(text):
                for code in _QUOTED_CODE.findall(arr):
                    refs.setdefault(code, set()).add(rel)
    return refs


def _scan_backend_refs() -> dict[str, set[str]]:
    """{ permiso_code: set(archivos) } para refs en backend Python."""
    refs: dict[str, set[str]] = {}
    for path in (BACKEND_ROOT / "app").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = str(path.relative_to(REPO_ROOT))
        for pat in _BE_PATTERNS:
            for code in pat.findall(text):
                refs.setdefault(code, set()).add(rel)
    return refs


# Deuda conocida: permisos que se referencian en código pero NO tienen migración
# Alembic que los inserte. Existen en producción porque fueron seedeados a mano
# (vía scripts SQL como backend/scripts/deploy_alertas.sql o inserts manuales).
# Una instalación fresca del repo SIN estos seeds tendría esos checks rotos.
#
# Este allowlist permite que el test pase mientras la deuda existe, pero si
# aparece un permiso nuevo sin migración va a fallar.
#
# Para limpiarla: por cada entrada, crear una migración Alembic con el INSERT
# correspondiente y removerla de este set. Cuando este set quede vacío,
# borrarlo y el test va a ser más estricto automáticamente.
PERMISOS_SIN_MIGRACION_CONOCIDOS = {
    "admin.gestionar_produccion_banlist",
    "alertas.configurar",
    "alertas.gestionar",
    "ordenes.gestionar_turbo_routing",
    "produccion.marcar_prearmado",
}


def test_permisos_referenciados_existen_en_migraciones() -> None:
    """Cada permiso usado en código debe estar definido por una migración."""
    definidos = _scan_migrations()
    assert definidos, "No se encontraron permisos en migraciones — revisar regex o ubicación de migraciones"

    fe_refs = _scan_frontend_refs()
    be_refs = _scan_backend_refs()

    faltantes: dict[str, set[str]] = {}
    for code, files in fe_refs.items():
        if code not in definidos and code not in PERMISOS_SIN_MIGRACION_CONOCIDOS:
            faltantes.setdefault(code, set()).update(files)
    for code, files in be_refs.items():
        if code not in definidos and code not in PERMISOS_SIN_MIGRACION_CONOCIDOS:
            faltantes.setdefault(code, set()).update(files)

    if faltantes:
        lineas = ["Permisos referenciados en código que NO existen en migraciones Alembic:\n"]
        for code in sorted(faltantes):
            lineas.append(f"  - {code}")
            for f in sorted(faltantes[code]):
                lineas.append(f"      · {f}")
        lineas.append("\nCada uno necesita una migración Alembic que lo INSERTE en la tabla")
        lineas.append("permisos, o el ref en código debe corregirse / eliminarse.")
        lineas.append("\nSi es deuda conocida (permiso ya en prod pero sin migración), agregarlo")
        lineas.append("al set PERMISOS_SIN_MIGRACION_CONOCIDOS de este test con explicación.")
        pytest.fail("\n".join(lineas))


def test_allowlist_solo_contiene_permisos_realmente_referenciados() -> None:
    """Sanity check del allowlist: si un permiso ya no se usa, sacarlo de la lista."""
    usados = set(_scan_frontend_refs()) | set(_scan_backend_refs())
    stale = PERMISOS_SIN_MIGRACION_CONOCIDOS - usados
    if stale:
        pytest.fail(
            "Entradas en PERMISOS_SIN_MIGRACION_CONOCIDOS que ya no se referencian "
            "en código (quitar del allowlist):\n  " + "\n  ".join(sorted(stale))
        )


def test_allowlist_no_oculta_permisos_que_si_tienen_migracion() -> None:
    """Si un permiso del allowlist ya tiene migración, debe salir del allowlist."""
    definidos = _scan_migrations()
    overlap = PERMISOS_SIN_MIGRACION_CONOCIDOS & definidos
    if overlap:
        pytest.fail(
            "Entradas en PERMISOS_SIN_MIGRACION_CONOCIDOS que YA tienen migración "
            "(quitar del allowlist, deuda saldada):\n  " + "\n  ".join(sorted(overlap))
        )


def test_permisos_definidos_sin_uso_en_codigo() -> None:
    """Warning suave: permisos en DB que nadie referencia (posible deadcode)."""
    definidos = _scan_migrations()
    usados = set(_scan_frontend_refs()) | set(_scan_backend_refs())

    huerfanos = sorted(definidos - usados)
    if huerfanos:
        # No fallar: pueden ser permisos legítimos consultados solo desde la UI de admin
        # de roles, o reservados para features que se vienen. Pero los listamos para auditoría.
        pytest.skip(
            f"{len(huerfanos)} permisos definidos en migraciones no se referencian en código:\n  "
            + "\n  ".join(huerfanos)
            + "\n\nRevisar si son código muerto, reservados a futuro, o consultados solo "
            "desde el panel de administración de roles."
        )
