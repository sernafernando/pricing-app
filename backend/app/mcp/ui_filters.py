"""Every filter of each screen, by the name the user sees, and the MCP argument that carries it (L10).

`tests/mcp/test_mcp_parity.py` checks it both ways: every argument listed here exists on its tool, and every
argument a tool takes is either a screen filter listed here or a non-filter argument with its reason. A filter
added to an endpoint therefore fails the test until it is mapped here. The PR's checklist table is built from it
(`checklist_markdown`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Arguments that are not filters of a screen, valid on any tool.
NOT_FILTERS: dict[str, str] = {
    "limit": "paging",
    "offset": "paging",
    "page": "paging",
    "page_size": "paging",
    "cursor": "paging",
}

TIENDA_PUBML = ("Tienda (tiendas oficiales; Sin tienda = `none`)", "tiendas")
TIENDA_ML = ("Tienda ML (tiendas oficiales; Sin tienda = `sin_tienda`)", "stores")

# Publicaciones ML: the filter bar and panels every view shares (`filter_query`).
PUBML_COMMON: tuple[tuple[str, str], ...] = (
    ("Búsqueda", "q"),
    ("Estado", "estado"),
    ("Estado (excluir)", "estado_excluir"),
    ("Tipo", "tipo"),
    ("Vínculo", "vinculo"),
    ("Stock", "stock"),
    TIENDA_PUBML,
    ("Promo aplicada (con / sin)", "promo_aplicada"),
    ("Promo: tipos", "promo_tipos"),
    ("Promo: estado", "promo_estado"),
    ("Con promo aplicada", "con_promo_aplicada"),
    ("Con promo sin aplicar", "con_promo_sin_aplicar"),
    ("PxQ", "con_pxq"),
    ("Hay mejores ofertas", "hay_mejores_ofertas"),
    ("Hay mejores excluido", "hay_mejores_excluido"),
    ("Marca", "marcas"),
    ("Categoría", "categorias"),
    ("Subcategoría", "subcategorias"),
    ("PM", "pms"),
    ("PM (nodo del Agrupado)", "pm_grupo"),
    ("Producto (hoja del Agrupado)", "producto"),
    ("Sin producto (hoja del Agrupado)", "sin_producto"),
    ("Familia", "familia"),
    ("Capa de color", "equipo_id"),
    ("Color", "colores"),
    ("Color por producto (vista Producto)", "color_por_producto"),
    ("Oferta por producto (vista Producto)", "oferta_por_producto"),
    ("Con rebate", "con_rebate"),
    ("Con oferta", "con_oferta"),
    ("Con web transferencia", "con_web_transf"),
    ("TN con descuento", "tn_con_descuento"),
    ("TN sin descuento", "tn_sin_descuento"),
    ("TN no publicado", "tn_no_publicado"),
    ("Out of cards", "out_of_cards"),
    ("Con precio", "con_precio"),
    ("Nuevos (últimos 7 días)", "nuevos_ultimos_7_dias"),
    ("Estado MLA", "estado_mla"),
    ("Sin MLA (vista Producto)", "con_mla"),
    ("Markup clásica positivo", "markup_clasica_positivo"),
    ("Markup rebate positivo", "markup_rebate_positivo"),
    ("Markup oferta positivo", "markup_oferta_positivo"),
    ("Markup web transferencia positivo", "markup_web_transf_positivo"),
    ("Auditoría: usuario", "audit_usuarios"),
    ("Auditoría: tipo de acción", "audit_tipos_accion"),
    ("Auditoría: desde", "audit_fecha_desde"),
    ("Auditoría: hasta", "audit_fecha_hasta"),
    ("Último evento", "evento"),
    ("Último evento desde", "evento_desde"),
)
PUBML_MARKUP_RANGE = (
    ("Markup negativo", "markup_neg"),
    ("Markup mínimo", "markup_min"),
    ("Markup máximo", "markup_max"),
)
PUBML_SORT = (("Orden (columna)", "orden"), ("Orden (dirección)", "dir"))
PUBML_ADS = {
    "restar_publicidad": "declared by the endpoint, the screen does not send it (exposed anyway)",
    "ads_desde": "declared by the endpoint, the screen does not send it (exposed anyway)",
    "ads_hasta": "declared by the endpoint, the screen does not send it (exposed anyway)",
}

# Métricas ML: the board filters (`board_filter` / `board_filter_tp`).
METRICAS_COMMON: tuple[tuple[str, str], ...] = (
    ("Período: desde", "date_from"),
    ("Período: hasta", "date_to"),
    ("Comparar con", "comparar_con"),
    ("Agrupar por", "group_by"),
    ("Dimensión", "dimension"),
    ("Búsqueda", "q"),
    ("Marca", "marcas"),
    ("Categoría", "categorias"),
    ("Subcategoría", "subcategorias"),
    ("PM", "pms"),
    TIENDA_ML,
    ("Estado de publicación", "pub_status"),
    ("Estado de publicación (excluir)", "pub_status_exclude"),
    ("Tipo de publicación", "pub_type"),
    ("Tipo de publicación (excluir)", "pub_type_exclude"),
    ("Stock", "stock"),
    ("Stock (excluir)", "stock_exclude"),
    ("Ageing", "ageing"),
    ("Ageing (excluir)", "ageing_exclude"),
    ("Alertas", "alerts"),
    ("Solo con ventas", "solo_con_ventas"),
    ("Canal (ML / por fuera / todo)", "canal"),
    ("Costo", "costo"),
    ("Empresa", "empresas"),
    ("Vendedor", "vendedores"),
    ("Publicidad", "publicidad"),
    ("Restar publicidad", "restar_publicidad"),
    ("Costos TP", "costos_tp"),
    ("Orden (columna)", "sort"),
    ("Orden (dirección)", "sort_dir"),
)


@dataclass(frozen=True)
class ToolFilters:
    screen: str
    filters: tuple[tuple[str, str], ...] = ()
    # Arguments of this tool that are not screen filters, with the reason (on top of NOT_FILTERS).
    other: dict[str, str] = field(default_factory=dict)
    has_tienda: bool = False


UI_FILTERS: dict[str, ToolFilters] = {
    # Publicaciones ML
    "pubml_items": ToolFilters(
        "Publicaciones ML › Publicación / Precios",
        PUBML_COMMON + PUBML_MARKUP_RANGE + PUBML_SORT,
        {**PUBML_ADS, "facets": "the list asks for its own facet counts"},
        has_tienda=True,
    ),
    "pubml_products": ToolFilters("Publicaciones ML › Producto", PUBML_COMMON + PUBML_SORT, has_tienda=True),
    "pubml_groups": ToolFilters(
        "Publicaciones ML › Agrupado",
        PUBML_COMMON + (("Agrupar por", "dimension"), ("Con familias", "familias"), ("Nodo abierto", "path")),
        PUBML_ADS,
        has_tienda=True,
    ),
    "pubml_kpis": ToolFilters(
        "Publicaciones ML › KPIs",
        PUBML_COMMON + (("Período (días)", "periodo"),),
        {
            "desde": "declared by the endpoint, the KPI strip only sends `periodo` (exposed anyway)",
            "hasta": "declared by the endpoint, the KPI strip only sends `periodo` (exposed anyway)",
            "comparar_con": "declared by the endpoint, the KPI strip only sends `periodo` (exposed anyway)",
        },
        has_tienda=True,
    ),
    "pubml_stats": ToolFilters(
        "Publicaciones ML › tarjetas",
        PUBML_COMMON + (("Tarjetas sin MLA (vista Producto)", "tarjetas_sin_mla"),),
        has_tienda=True,
    ),
    "pubml_stock_audit": ToolFilters(
        "Publicaciones ML › Auditoría de stock", PUBML_COMMON + PUBML_SORT, has_tienda=True
    ),
    "pubml_mejores_ofertas_count": ToolFilters("Publicaciones ML › badge mejores ofertas (tienda fija del servidor)"),
    "pubml_mejores_ofertas_por_pm": ToolFilters("Publicaciones ML › mejores ofertas por PM (tienda fija del servidor)"),
    "pubml_item": ToolFilters("Publicaciones ML › panel de la publicación", (("Publicación", "item_id"),)),
    "pubml_item_variations": ToolFilters(
        "Publicaciones ML › panel › Variaciones", (("Publicación", "item_id"),), PUBML_ADS
    ),
    "pubml_item_events": ToolFilters("Publicaciones ML › panel › Eventos", (("Publicación", "item_id"),)),
    "pubml_item_history": ToolFilters(
        "Publicaciones ML › panel › Historial", (("Publicación", "item_id"), ("Cambios técnicos", "tecnicos"))
    ),
    "pubml_product_envio": ToolFilters(
        "Publicaciones ML › panel › Envío",
        (("Publicación", "item_id"), ("Período: desde", "date_from"), ("Período: hasta", "date_to")),
    ),
    "pubml_item_product_links": ToolFilters("Publicaciones ML › panel › Vínculos", (("Publicación", "item_id"),)),
    "pubml_product_links": ToolFilters("Publicaciones ML › Vínculos", (("Clase de vínculo", "class"),)),
    "pubml_product_links_coverage": ToolFilters("Publicaciones ML › Vínculos › cobertura", (("Muestras", "samples"),)),
    "pubml_status": ToolFilters("Publicaciones ML › estado de la sincronización"),
    "pubml_settings": ToolFilters("Publicaciones ML › configuración"),
    "pubml_repair_runs": ToolFilters(
        "Publicaciones ML › Reparaciones",
        (("Tipo de trabajo", "job_type"), ("Estado", "status"), ("Desde", "desde"), ("Hasta", "hasta")),
    ),
    "pubml_repair_run": ToolFilters(
        "Publicaciones ML › Reparaciones › corrida",
        (("Corrida", "run_id"), ("Acción", "action"), ("Detalle", "detail")),
    ),
    "pubml_repair_events": ToolFilters("Publicaciones ML › Reparaciones › eventos", (("Publicación", "mla_id"),)),
    # Promos
    "promos_list": ToolFilters("Promociones (sin filtros en la app)"),
    "promos_promotion_items": ToolFilters(
        "Promociones › ítems de una promoción",
        (("Promoción", "promotion_id"), ("Tipo de promoción", "promotion_type")),
    ),
    "promos_item": ToolFilters(
        "Publicaciones ML › panel › Promociones",
        (
            ("Publicación", "mla_id"),
            ("Filtro de tipos (pestaña Promociones)", "promotion_types"),
            ("Filtro de nombres por tipo (pestaña Promociones)", "promotion_names"),
        ),
    ),
    "promos_item_markup": ToolFilters(
        "Publicaciones ML › panel › Promociones › markup para un precio",
        (("Publicación", "mla_id"), ("Precio", "price")),
    ),
    "promos_item_confirmacion_ml": ToolFilters(
        "Publicaciones ML › panel › Promociones › confirmación ML", (("Publicación", "mla_id"),)
    ),
    "catalogo_competencia": ToolFilters("Publicaciones ML › panel › Competencia", (("Publicación", "mla_id"),)),
    "promos_publicaciones": ToolFilters(
        "Promos por publicación (filtros de Publicaciones ML)",
        PUBML_COMMON + PUBML_MARKUP_RANGE + PUBML_SORT + (("PM por nombre", "pm"),),
        {**PUBML_ADS, "facets": "the list asks for its own facet counts"},
        has_tienda=True,
    ),
    # Productos
    "producto_detalle": ToolFilters("Productos › detalle", (("Producto", "item_id"),)),
    "productos_precios_listas": ToolFilters(
        "Productos › precios por lista",
        (("Búsqueda", "search"), ("Categoría", "categoria"), ("Marca", "marca"), ("Con stock", "con_stock")),
    ),
    # Métricas ML
    "metricas_board": ToolFilters("Métricas ML › tablero", METRICAS_COMMON, has_tienda=True),
    "metricas_board_publications": ToolFilters(
        "Métricas ML › tablero › publicaciones de un producto",
        (("Producto", "product_item_id"),) + METRICAS_COMMON,
        has_tienda=True,
    ),
    "metricas_board_envios": ToolFilters("Métricas ML › Envíos", METRICAS_COMMON, has_tienda=True),
    "metricas_board_group_nodes": ToolFilters(
        "Métricas ML › tablero agrupado", METRICAS_COMMON + (("Nodo abierto", "path"),), has_tienda=True
    ),
    # Ventas
    "ventas_ml": ToolFilters(
        "Ventas ML",
        (
            ("Estado de operación", "operation_status"),
            ("Estado de la mercadería", "goods_status"),
            ("Período: desde", "date_from"),
            ("Período: hasta", "date_to"),
            ("Búsqueda", "q"),
            ("Marca", "marcas"),
            ("Categoría", "categorias"),
            ("Subcategoría", "subcategorias"),
            ("PM", "pms"),
            TIENDA_ML,
            ("A revisar", "include_unknown"),
            ("En disputa", "include_in_dispute"),
            ("Mixta", "include_mixed"),
            ("Provisorio", "include_provisional"),
            ("Canceladas", "include_cancelled"),
            ("Solo con alertas", "only_alerts"),
        ),
        {
            "sort": "declared by the endpoint, the screen has no sort control (exposed anyway)",
            "sold_month": "declared by the endpoint for other callers (exposed anyway)",
        },
        has_tienda=True,
    ),
    "venta_ml": ToolFilters("Ventas ML › operación", (("Operación", "order_id"),)),
    "ventas_por_fuera": ToolFilters(
        "Ventas por fuera › operaciones",
        (("Desde", "desde"), ("Hasta", "hasta"), ("Empresa", "empresa"), ("Vendedor", "vendedor")),
    ),
    "ventas_fuera_cargas": ToolFilters(
        "Ventas por fuera › cargas de PDF",
        (("Días", "dias"), ("Empresa", "empresa"), ("Vendedor", "vendedor")),
    ),
    "pms": ToolFilters("Selector de PM", (("Solo PMs con marcas", "solo_con_marcas"),)),
}


def checklist_markdown(tool_names: list[str]) -> str:
    """The PR checklist: per tool, every filter of its screen, UI name -> MCP argument."""
    blocks = []
    for name in tool_names:
        entry = UI_FILTERS[name]
        rows = entry.filters or (("(no filters on this screen)", "—"),)
        lines = [
            f"<details><summary><code>{name}</code> · {entry.screen} · {len(entry.filters)} filters</summary>",
            "",
            "| UI filter | MCP argument | |",
            "|---|---|---|",
        ]
        lines += [f"| {label} | `{param}` | ✅ |" for label, param in rows]
        blocks.append("\n".join(lines + ["", "</details>"]))
    return "\n\n".join(blocks)
