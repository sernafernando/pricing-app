"""Static guards over `app/services/ml_publications/`.

The store never deletes history, never touches GBP/ERP data and never introduces
scheduling machinery of its own (jobs run on the existing worker runtime).
Each rule is a small scanner first proven against offending snippets, then
applied to the real package so the guard cannot pass vacuously.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[3] / "app" / "services" / "ml_publications"
DEPLOY = Path(__file__).resolve().parents[4] / "deploy"

QUEUE_TABLE = "ml_pub_refresh_queue"
# Only the queue table may be deleted from, and only by the queue module.
DELETE_ALLOWED = {"queue.py": {QUEUE_TABLE}}

FORBIDDEN_ERP_NAMES = ("tb_mercadolibre_items_publicados", "publicaciones_ml", "productos_erp", "ProductoERP")
GBP_NAME_PATTERN = re.compile(r"GBPClient|gbp_client|wsBasicQuery")
SCHEDULING_PATTERN = re.compile(r"crontab|OnCalendar|\.timer\b|pg_notify|\bLISTEN\b|\bNOTIFY\b")


def package_sources() -> list[tuple[str, str]]:
    return [(p.relative_to(PACKAGE).as_posix(), p.read_text(encoding="utf-8")) for p in sorted(PACKAGE.rglob("*.py"))]


def destructive_statements(name: str, source: str) -> list[str]:
    """DELETE/TRUNCATE/DROP aimed at anything but the queue table inside the queue module."""
    found = []
    allowed = DELETE_ALLOWED.get(name, set())
    for table in re.findall(r"DELETE\s+FROM\s+([A-Za-z_][\w.]*)", source, flags=re.IGNORECASE):
        if table not in allowed:
            found.append(f"DELETE FROM {table}")
    found += re.findall(r"TRUNCATE\b[^\n]*", source, flags=re.IGNORECASE)
    found += re.findall(r"DROP\s+TABLE\b[^\n]*", source, flags=re.IGNORECASE)
    found += [m for m in re.findall(r"\.delete\(", source)]
    return found


def erp_references(source: str) -> list[str]:
    hits = [name for name in FORBIDDEN_ERP_NAMES if re.search(rf"\b{name}\b", source)]
    hits += GBP_NAME_PATTERN.findall(source)
    try:
        tree = ast.parse(source)
    except SyntaxError:  # a bare SQL/text snippet: only the name scan applies
        return hits
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""] + [alias.name for alias in node.names]
        else:
            continue
        hits += [m for m in modules if "gbp" in m.lower()]
    return hits


def scheduling_references(source: str) -> list[str]:
    return SCHEDULING_PATTERN.findall(source)


class TestScannersCatchOffenders:
    def test_delete_scanner_flags_store_tables_but_not_the_queue_in_the_queue_module(self) -> None:
        assert destructive_statements("store.py", "DELETE FROM ml_items WHERE x") == ["DELETE FROM ml_items"]
        assert destructive_statements("queue.py", "delete from ml_change_log") == ["DELETE FROM ml_change_log"]
        assert destructive_statements("queue.py", f"DELETE FROM {QUEUE_TABLE} WHERE a") == []
        assert destructive_statements("store.py", f"DELETE FROM {QUEUE_TABLE}") == [f"DELETE FROM {QUEUE_TABLE}"]

    def test_delete_scanner_flags_truncate_drop_and_orm_deletes(self) -> None:
        assert destructive_statements("x.py", "TRUNCATE ml_items") == ["TRUNCATE ml_items"]
        assert destructive_statements("x.py", "DROP TABLE ml_items") == ["DROP TABLE ml_items"]
        assert destructive_statements("x.py", "session.query(MlItem).delete()") == [".delete("]

    def test_erp_scanner_flags_table_names_and_gbp_clients(self) -> None:
        assert erp_references("select * from productos_erp") == ["productos_erp"]
        assert erp_references("from app.services.gbp_client import x") == ["gbp_client", "app.services.gbp_client"]
        assert erp_references("import app.services.gbp as g") == ["app.services.gbp"]
        assert erp_references('"""never derived from GBP data"""\nx = 1') == []
        assert erp_references("ml_items ml_item_variations") == []

    def test_scheduling_scanner_flags_cron_timers_and_listen_notify(self) -> None:
        for snippet in ("crontab -e", "OnCalendar=daily", "SELECT pg_notify('a','b')", "LISTEN worker_jobs"):
            assert scheduling_references(snippet) != [], snippet
        assert scheduling_references("enqueue for refresh at the next tick") == []


class TestPackageIsClean:
    def test_package_is_not_empty(self) -> None:
        names = {name for name, _ in package_sources()}
        assert {"queue.py", "pacing.py", "ml_http.py", "settings_store.py"} <= names

    def test_nothing_deletes_store_history(self) -> None:
        offenders = {
            name: found for name, source in package_sources() if (found := destructive_statements(name, source))
        }
        assert offenders == {}

    def test_the_queue_module_does_delete_from_its_own_table(self) -> None:
        # Proves the delete scanner sees real code: the one allowed DELETE exists.
        source = dict(package_sources())["queue.py"]
        assert re.findall(r"DELETE\s+FROM\s+(\w+)", source) == [QUEUE_TABLE]

    def test_no_gbp_or_erp_mirror_access(self) -> None:
        offenders = {name: found for name, source in package_sources() if (found := erp_references(source))}
        assert offenders == {}

    def test_no_cron_timer_or_listen_notify_machinery(self) -> None:
        offenders = {name: found for name, source in package_sources() if (found := scheduling_references(source))}
        assert offenders == {}

    def test_no_systemd_timer_for_the_store_is_shipped(self) -> None:
        if not DEPLOY.is_dir():
            return
        assert [p.name for p in DEPLOY.rglob("*.timer") if "ml" in p.name and "pub" in p.name] == []
