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
ROUTERS = Path(__file__).resolve().parents[3] / "app" / "routers"
DEPLOY = Path(__file__).resolve().parents[4] / "deploy"

QUEUE_TABLE = "ml_pub_refresh_queue"
# Only the queue table may be deleted from, and only by the queue module.
DELETE_ALLOWED = {"queue.py": {QUEUE_TABLE}}

FORBIDDEN_ERP_NAMES = ("tb_mercadolibre_items_publicados", "publicaciones_ml", "productos_erp", "ProductoERP")
# The linking module is the single accepted reader of our product catalog (design D20). Its router is
# allow-listed below as the only HTTP surface of the linking module, and it reads the catalog ONLY through
# that module. Everything else about GBP and the other ERP-mirror tables stays forbidden for both.
PRODUCT_CATALOG_NAMES = {"productos_erp", "ProductoERP"}
PRODUCT_CATALOG_READERS = {"links.py"}
# The one router allowed to use `app.services.ml_publications.links` (PR5L2).
LINKS_ROUTERS = {"ml_publications_links.py"}
LINKS_IMPORT = re.compile(r"app\.services\.ml_publications(?:\s+import\s+[^\n]*\blinks\b|\.links\b)")
GBP_NAME_PATTERN = re.compile(r"GBPClient|gbp_client|wsBasicQuery")
# The bridge keeps its own promotion mirror (`ml_item_promotions`); the store gets promotions only from the
# ML API into its own `ml_item_seller_promotions` and never reads or writes the mirror (spec "Bridge mirror untouched").
BRIDGE_PROMOTION_MIRROR = re.compile(r"\bml_item_promotions\b")
HANDLERS = Path(__file__).resolve().parents[3] / "app" / "workers" / "handlers" / "ml_publications.py"
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


def erp_violations(name: str, source: str) -> list[str]:
    """`erp_references` minus the product catalog names, which only the allow-listed readers may use."""
    hits = erp_references(source)
    if name in PRODUCT_CATALOG_READERS:
        return [hit for hit in hits if hit not in PRODUCT_CATALOG_NAMES]
    return hits


def router_sources() -> list[tuple[str, str]]:
    return [(p.name, p.read_text(encoding="utf-8")) for p in sorted(ROUTERS.glob("*.py"))]


def uses_links_module(source: str) -> bool:
    return LINKS_IMPORT.search(source) is not None


def bridge_mirror_references(source: str) -> list[str]:
    return BRIDGE_PROMOTION_MIRROR.findall(source)


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

    def test_the_allow_list_only_opens_the_product_catalog_to_the_linking_module(self) -> None:
        catalog = "from app.models.producto import ProductoERP"
        assert erp_violations("links.py", catalog) == []
        assert erp_violations("store.py", catalog) == ["ProductoERP"]
        assert erp_violations("links.py", "select * from publicaciones_ml") == ["publicaciones_ml"]
        assert erp_violations("links.py", "from app.services.gbp_client import x") != []

    def test_links_import_scanner_sees_both_import_spellings(self) -> None:
        assert uses_links_module("from app.services.ml_publications import links")
        assert uses_links_module("from app.services.ml_publications import events, links")
        assert uses_links_module("from app.services.ml_publications.links import coverage")
        assert not uses_links_module("from app.services.ml_publications import settings_store")

    def test_bridge_mirror_scanner_flags_the_mirror_table_but_not_the_store_table(self) -> None:
        assert bridge_mirror_references("SELECT * FROM ml_item_promotions WHERE mla = :m") == ["ml_item_promotions"]
        assert bridge_mirror_references("INSERT INTO ml_item_promotions (mla) VALUES (1)") == ["ml_item_promotions"]
        assert bridge_mirror_references("ml_item_seller_promotions") == []
        assert bridge_mirror_references("ml_item_promotions_extra") == []

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
        offenders = {name: found for name, source in package_sources() if (found := erp_violations(name, source))}
        assert offenders == {}

    def test_only_the_linking_module_reads_the_product_catalog(self) -> None:
        readers = {name for name, source in package_sources() if PRODUCT_CATALOG_NAMES & set(erp_references(source))}
        assert readers == PRODUCT_CATALOG_READERS

    def test_the_links_router_is_the_only_router_using_the_linking_module(self) -> None:
        users = {name for name, source in router_sources() if uses_links_module(source)}
        assert users == LINKS_ROUTERS

    def test_the_links_router_reaches_the_product_catalog_only_through_the_linking_module(self) -> None:
        sources = dict(router_sources())
        for name in LINKS_ROUTERS:
            assert erp_references(sources[name]) == [], name

    def test_nothing_reads_or_writes_the_bridge_promotion_mirror(self) -> None:
        sources = [*package_sources(), (HANDLERS.name, HANDLERS.read_text(encoding="utf-8"))]
        assert {"subresource_store.py", "ml_publications.py"} <= {name for name, _ in sources}
        offenders = {name: found for name, source in sources if (found := bridge_mirror_references(source))}
        assert offenders == {}

    def test_no_cron_timer_or_listen_notify_machinery(self) -> None:
        offenders = {name: found for name, source in package_sources() if (found := scheduling_references(source))}
        assert offenders == {}

    def test_no_systemd_timer_for_the_store_is_shipped(self) -> None:
        if not DEPLOY.is_dir():
            return
        assert [p.name for p in DEPLOY.rglob("*.timer") if "ml" in p.name and "pub" in p.name] == []
