import { ChevronDown, ChevronRight, CornerDownRight, Cpu, Tag, TriangleAlert } from 'lucide-react';
import { TableShell } from '../../kit';
import { buildColumns } from '../columns';
import { BranchState, NodeSummary } from '../NodeCells';
import MarkupCell from '../MarkupCell';
import {
  AgeingCell,
  GrossCell,
  LastSaleCell,
  MarkupRealCell,
  MarkupTrendCell,
  StockQuantity,
  TotalGaussCell,
  UnitsCell,
  UnitsTrendCell,
} from '../MetricsCells';
import { formatRatio, formatUnits } from '../../../utils/metricasMlFormat';
import { auditMarkup, auditMetrics, drillOf, fromVariants, isPack, salesSplit, valueOf } from './stockAuditRows';
import { AUDIT_GROUPS } from './auditOptions';
import cellStyles from '../cells.module.css';
import nodeStyles from '../NodeCells.module.css';
import styles from './StockAudit.module.css';

/**
 * The Auditoría de stock table (approved mock v2): marca › categoría › product › variante › publicación
 * (auditoria-stock-niveles S1, the table starting at the level the view asks), grouped columns Stock
 * (unidades), Valor stock (USD · ARS), Ventas (unidades), Markup con sell in / sell out, Resultado and Rotación. Every column
 * but the first can be hidden (`AUDIT_COLUMN_OPTIONS`, the page's picker); the sortable ones send their key as the
 * backend's `orden`. A publication row draws the list's own cells (`buildColumns`), so it reads like everywhere else.
 */

const { STOCK, VALOR, VENTAS, MARKUP, RESULTADO, ROTACION } = AUDIT_GROUPS;

const MONEY = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 0 });
const dash = <span className={cellStyles.empty}>—</span>;

/** "ERP n · Full n" under a sales figure (auditoria-stock-niveles S3): Full = shipped from ML's Full warehouse, ERP =
 * the rest, out of the own stock: colecta, Flex, Turbo and retiro (a sale without shipping data is a pickup at the
 * store, owner L3). Nothing without the split. */
function SalesSplit({ split }) {
  if (!split) return null;
  return <span className={styles.split}>{`ERP ${formatUnits(split.erp)} · Full ${formatUnits(split.full)}`}</span>;
}

/** "ERP x · Full y" under Días de cobertura and Rotación (auditoria-stock-niveles S4), already formatted. */
function OriginSplit({ erp, full }) {
  return <span className={styles.split}>{`ERP ${erp} · Full ${full}`}</span>;
}

/** A figure with an optional note under it ("12 de variantes", "25 packs") and its ERP / Full split. */
function Figure({ children, note, split, strong = false }) {
  return (
    <div className={`${cellStyles.stack} ${cellStyles.stackEnd}`}>
      <span className={strong ? styles.strong : undefined}>{children}</span>
      {note && <span className={styles.figureNote}>{note}</span>}
      <SalesSplit split={split} />
    </div>
  );
}

/** A stock value: USD on the first line, ARS under it in the muted mono; "—" when unknown. `note` goes under it. */
function Value({ money, strong = false, note = null }) {
  if (!money || (money.usd == null && money.ars == null)) return dash;
  return (
    <div className={`${cellStyles.stack} ${cellStyles.stackEnd}`}>
      <span className={`${styles.usd} ${strong ? styles.strong : ''}`}>{money.usd == null ? '—' : MONEY.format(money.usd)}</span>
      <span className={styles.ars}>{money.ars == null ? '—' : `$ ${MONEY.format(money.ars)}`}</span>
      {note}
    </div>
  );
}

/** "N productos sin costo" beside a group's values (auditoria-stock-niveles S2): they are its costed products' only,
 * as the KPI cards say. */
function NoCostNote({ count }) {
  if (!count) return null;
  return (
    <span className={styles.noCost}>
      <TriangleAlert size={11} aria-hidden="true" />
      {count} {count === 1 ? 'producto' : 'productos'} sin costo
    </span>
  );
}

const units = (value, strong = false) => (
  <span className={`${cellStyles.units} ${strong ? styles.strong : ''}`}>{formatUnits(value)}</span>
);

const plural = (count, one, many) => `${formatUnits(count)} ${count === 1 ? one : many}`;

/** The first cell of a product or a variant: toggle, name and its second line. */
function NodeTitleCell({ row, onToggle }) {
  const { node, type, expanded } = row;
  const product = type === 'product';
  const openable = node.publications_count > 0 || (product && node.variantes.length > 0);
  const Icon = expanded ? ChevronDown : ChevronRight;
  const kind = product ? (node.tipo === 'pc' ? null : 'Producto') : node.tipo === 'pack' ? 'Combo' : 'Variante';
  const parts = [
    product && node.variantes.length > 0 && plural(node.variantes.length, node.variantes.some((v) => v.tipo === 'pack') ? 'combo' : 'variante', node.variantes.some((v) => v.tipo === 'pack') ? 'combos' : 'variantes'),
    plural(
      node.publications_count + (product ? node.variantes.reduce((sum, v) => sum + v.publications_count, 0) : 0),
      'publicación',
      'publicaciones',
    ),
  ].filter(Boolean);
  return (
    <div className={nodeStyles.node}>
      {openable ? (
        <button
          type="button"
          className={cellStyles.toggle}
          aria-expanded={expanded}
          aria-label={`${expanded ? 'Cerrar' : 'Abrir'} ${node.descripcion}`}
          onClick={(event) => {
            event.stopPropagation();
            onToggle(row);
          }}
        >
          <Icon size={14} aria-hidden="true" />
        </button>
      ) : (
        <span className={styles.togglePlaceholder} aria-hidden="true" />
      )}
      <div className={nodeStyles.nodeText}>
        <span className={`${nodeStyles.nodeLabel} ${styles.nodeName}`} title={node.descripcion}>
          {node.descripcion}
        </span>
        <span className={styles.nodeNote}>
          {kind && <span>{kind}</span>}
          {node.tipo === 'pc' && (
            <span className={styles.pcTag}>
              <Cpu size={11} aria-hidden="true" />
              PC
            </span>
          )}
          {node.codigo && <span className={styles.code}>{node.codigo}</span>}
          <span>· {parts.join(' · ')}</span>
          {product && !node.publicacion_activa && (
            <span className={styles.warning}>
              <TriangleAlert size={11} aria-hidden="true" />
              Con stock sin publicación activa
            </span>
          )}
        </span>
      </div>
    </div>
  );
}

const GROUP_KINDS = { marca: 'Marca', categoria: 'Categoría' };

/** The first cell of a brand or a category: toggle, name, how many products, and the way into it. */
function GroupTitleCell({ row, onToggle, onDrill }) {
  const { node, expanded } = row;
  const Icon = expanded ? ChevronDown : ChevronRight;
  const target = node.tipo === 'marca' ? 'categorías' : 'productos';
  return (
    <div className={nodeStyles.node}>
      <button
        type="button"
        className={cellStyles.toggle}
        aria-expanded={expanded}
        aria-label={`${expanded ? 'Cerrar' : 'Abrir'} ${node.descripcion}`}
        onClick={(event) => {
          event.stopPropagation();
          onToggle(row);
        }}
      >
        <Icon size={14} aria-hidden="true" />
      </button>
      <div className={nodeStyles.nodeText}>
        <span className={`${nodeStyles.nodeLabel} ${styles.groupName}`} title={node.descripcion}>
          {node.descripcion}
        </span>
        <span className={styles.nodeNote}>
          <span>{GROUP_KINDS[node.tipo]}</span>
          <span>· {plural(node.productos ?? 0, 'producto', 'productos')}</span>
          {onDrill && (
            <button
              type="button"
              className={styles.drill}
              aria-label={`Ver ${target} de ${node.descripcion}`}
              title={`Ver solo ${target} de ${node.descripcion}`}
              onClick={(event) => {
                event.stopPropagation();
                onDrill(drillOf(node));
              }}
            >
              <CornerDownRight size={11} aria-hidden="true" />
              Ver {target}
            </button>
          )}
        </span>
      </div>
    </div>
  );
}

/** Units sold in base units with "N packs" under a pack's (own count) figure. */
function packNote(variant, count) {
  return isPack(variant) && count != null ? `${formatUnits(count)} packs` : null;
}

/** One side of the Promos aplicadas cell: the promo badge's tag and how many publications; nothing for none. */
function PromoSide({ count, applied }) {
  if (!count) return null;
  const label = `${count} ${count === 1 ? 'publicación' : 'publicaciones'} ${applied ? 'con' : 'sin'} promo aplicada`;
  return (
    <span className={applied ? styles.promoCon : styles.promoSin} aria-label={label} title={label}>
      <Tag size={12} aria-hidden="true" />
      {formatUnits(count)}
    </span>
  );
}

/** A product's or a variant's publications with and without an applied promo (promos-fila S2); "—" when the
 * promotions database could not be read (L8), never 0. A publication keeps its own "Promo aplicada" badge (L4). */
function PromoCounts({ counts }) {
  if (counts == null) {
    return (
      <span className={cellStyles.empty} title="Promociones no disponibles">
        —
      </span>
    );
  }
  if (!counts.con && !counts.sin) return null;
  return (
    <span className={styles.promoCounts}>
      <PromoSide count={counts.con} applied />
      <PromoSide count={counts.sin} applied={false} />
    </span>
  );
}

const STOCK_UNITS = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 });

// The Rotación group is the whole product's whatever the filter (L2): every figure's tooltip says so.
const WHOLE_PRODUCT = 'del producto completo, sin filtros';
// What each figure is (auditoria-ventas-erp-full L2): its header's tooltip, the formula `stock_audit` computes.
const COVERAGE_HINT =
  'Días que alcanza el stock al ritmo de venta de los últimos 30 días: stock ÷ (vendidas en 30 días ÷ 30). ∞: hay stock y no hubo ventas.';
const ROTATION_HINT =
  'Veces que se vendió el stock en 30 días: vendidas en 30 días ÷ stock promedio de los días con foto del stock (sin fotos, el stock actual).';
const COUNT = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 0 });

/** Días de cobertura (rotacion S2): the stock now at the last 30 days' pace; "∞" with stock and no sale (L1 Q2). */
function CoverageCell({ ventas }) {
  const known = ventas?.stock_actual != null && ventas?.vendidas_30d != null;
  if (ventas?.cobertura_infinita) {
    const title = known
      ? `${COUNT.format(ventas.stock_actual)} en stock y ninguna venta en 30 días: no se agota al ritmo actual, ${WHOLE_PRODUCT}`
      : `Con stock y sin ventas en 30 días, ${WHOLE_PRODUCT}`;
    return (
      <span className={`${styles.rotationFigure} ${styles.infinite}`} aria-label="Días de cobertura" title={title}>
        ∞
      </span>
    );
  }
  if (ventas?.dias_cobertura == null) return dash;
  const days = Math.round(ventas.dias_cobertura);
  // A month is 30 days, the formula's own window.
  const title = known
    ? `Días que alcanza el stock al ritmo de venta de 30 días: ${COUNT.format(ventas.stock_actual)} ÷ (${COUNT.format(ventas.vendidas_30d)} ÷ 30) = ${COUNT.format(days)} días (≈ ${COUNT.format(Math.round(days / 30))} ${Math.round(days / 30) === 1 ? 'mes' : 'meses'}), ${WHOLE_PRODUCT}`
    : `Ventas 30D, ${WHOLE_PRODUCT}`;
  return (
    <span className={styles.rotationFigure} aria-label="Días de cobertura" title={title}>
      {`${formatUnits(days)} d`}
    </span>
  );
}

/** Rotación (veces): units sold in 30 days over the average stock of the days photographed; with no photo yet the
 * stock now stands in, marked "≈" (L1). The tooltip says which. */
function RotationCell({ ventas }) {
  if (ventas?.rotacion == null) return dash;
  const days = ventas.stock_promedio_dias;
  const stock = `${STOCK_UNITS.format(ventas.stock_promedio)} u.`;
  const approximate = !days;
  const sold = ventas.vendidas_30d;
  let title;
  if (sold == null) {
    title = approximate
      ? `Aproximado: sobre el stock actual (${stock}), todavía no hay fotos diarias del stock, ${WHOLE_PRODUCT}`
      : `Ventas 30D sobre el stock promedio de ${formatUnits(days)} ${days === 1 ? 'día' : 'días'} (${stock}), ${WHOLE_PRODUCT}`;
  } else {
    const base = approximate
      ? `${STOCK_UNITS.format(ventas.stock_promedio)} de stock actual (aproximado: todavía no hay fotos diarias del stock)`
      : `${STOCK_UNITS.format(ventas.stock_promedio)} de stock promedio (${formatUnits(days)} ${days === 1 ? 'día' : 'días'})`;
    title = `Veces que se vendió el stock en 30 días: ${COUNT.format(sold)} vendidas ÷ ${base} = ${formatRatio(ventas.rotacion)}, ${WHOLE_PRODUCT}`;
  }
  return (
    <span className={styles.rotationFigure} aria-label="Rotación (veces)" title={title}>
      {`${approximate ? '≈ ' : ''}${formatRatio(ventas.rotacion)}×/30d`}
    </span>
  );
}

/** One origin's coverage (`ventas.por_origen.erp`): "∞" with stock and no sale, 0 with sales and no stock (out of
 * stock), "—" only with neither. */
const originCoverage = (origin) =>
  origin?.cobertura_infinita ? '∞' : origin?.dias_cobertura == null ? '—' : formatUnits(Math.round(origin.dias_cobertura));
/** One origin's rotation: "∞" when it sold with an average stock of 0 (out of stock: sold ÷ 0 has no number). */
const originRotation = (origin) =>
  origin?.rotacion_infinita ? '∞' : origin?.rotacion == null ? '—' : formatRatio(origin.rotacion);

/** A Rotación figure with its "ERP · Full" line under it, when the row has one. */
function RotationFigure({ children, ventas, of }) {
  const origin = ventas?.por_origen;
  if (!origin) return children;
  return (
    <div className={`${cellStyles.stack} ${cellStyles.stackEnd}`}>
      {children}
      <OriginSplit erp={of(origin.erp)} full={of(origin.full)} />
    </div>
  );
}

/** The Board's last sale and ageing of a product or variant, in the list cells' shape. */
const lastSaleOf = (ventas) => (ventas ? { last_sale_at: ventas.ultima_venta, ageing_days: ventas.ageing_dias } : null);

// The first column says the tree the level starts.
const TREE_HEADERS = {
  marca: 'Marca › Categoría › Producto',
  categoria: 'Categoría › Producto › Variante',
  producto: 'Producto › Variante › Publicación',
};

/** A state row of a category's products: the publications' (`BranchState`) but its own empty line. */
function AuditBranchState({ row, onMore }) {
  if (row.branchKind === 'products' && row.type === 'state' && row.state === 'empty') {
    return <span className={cellStyles.note}>Sin productos con los filtros actuales</span>;
  }
  return <BranchState row={row} onMore={onMore} onRetry={onMore} />;
}

function buildAuditColumns({ canSeeSales, canSeeMargin, rate, nivel, onToggle, onDrill, onMore, arrange }) {
  // A publication draws the list's own cells (Tipo, Estado, sales, markups, Total Gauss).
  const list = Object.fromEntries(buildColumns({ eventsEnabled: false, canSeeSales, canSeeMargin }).map((column) => [column.key, column]));
  const item = (key, row) => list[key].render(row.item);

  // A pack's units in base units: its figures and its ERP / Full split alike, so ERP + Full is the total shown.
  const factorOf = (row) => (row.type === 'variant' && isPack(row.node) ? Number(row.node.cantidad) : 1);
  const metricsOf = (row) => auditMetrics(row.node.ventas, factorOf(row));
  const splitOf = (row, window) =>
    row.type === 'item' ? salesSplit(row.item.metrics?.envio?.[window]) : salesSplit(row.node.ventas?.envio?.[window], factorOf(row));
  // A product's or a group's own figures (a group is its products' sum).
  const own = (row) => row.type === 'product' || row.type === 'group';
  // A publication's Full value: its units at its node's cost.
  const itemFull = (row) => valueOf(row.item.stock?.full ?? null, row.owner, rate);

  const columns = [
    {
      key: 'descripcion',
      header: TREE_HEADERS[nivel] ?? TREE_HEADERS.producto,
      label: 'Producto',
      width: 400,
      minWidth: 260,
      fill: true,
      resizable: true,
      resizeLabel: 'Producto',
      sortable: true,
      render: (row) => {
        if (row.type === 'group') return <GroupTitleCell row={row} onToggle={onToggle} onDrill={onDrill} />;
        if (row.type === 'product' || row.type === 'variant') return <NodeTitleCell row={row} onToggle={onToggle} />;
        if (row.type === 'item') return item('titulo', row);
        return <AuditBranchState row={row} onMore={onMore} />;
      },
    },
    {
      key: 'tipo',
      header: 'Tipo',
      width: 110,
      render: (row) =>
        row.type === 'item' ? item('tipo', row) : row.node ? <NodeSummary column="tipo" node={{ kindCounts: row.node.kind_counts }} /> : null,
    },
    {
      key: 'estado',
      header: 'Estado',
      width: 110,
      render: (row) =>
        row.type === 'item' ? item('estado', row) : row.node ? <NodeSummary column="estado" node={{ statusCounts: row.node.status_counts }} /> : null,
    },
    {
      key: 'promos_aplicadas',
      header: 'Promos',
      label: 'Promos aplicadas',
      width: 96,
      sortable: true,
      align: 'center',
      fit: true,
      render: (row) => (row.node ? <PromoCounts counts={row.node.promo_counts} /> : null),
    },
    {
      key: 'unidades_erp',
      group: STOCK,
      header: 'ERP',
      label: 'Stock ERP',
      width: 72,
      sortable: true,
      align: 'center',
      fit: true,
      render: (row) => (own(row) ? <StockQuantity value={row.node.erp.unidades} /> : row.node || row.item ? dash : null),
    },
    {
      key: 'unidades_full',
      group: STOCK,
      header: 'Full',
      label: 'Stock Full',
      width: 96,
      sortable: true,
      align: 'center',
      fit: true,
      render: (row) => {
        if (row.type === 'group') return units(row.node.full.unidades);
        if (row.type === 'product') {
          const { full, source } = fromVariants(row.node);
          return <Figure note={full > 0 ? `${formatUnits(full)} ${source}` : null}>{units(row.node.full.unidades)}</Figure>;
        }
        if (row.type === 'variant') {
          return <Figure note={packNote(row.node, row.node.full.unidades)}>{units(row.node.full_unidades_base)}</Figure>;
        }
        if (row.type === 'item') return row.item.stock?.full == null ? dash : units(row.item.stock.full);
        return null;
      },
    },
    {
      key: 'unidades_total',
      group: STOCK,
      header: 'Total',
      label: 'Stock total',
      width: 72,
      sortable: true,
      align: 'center',
      fit: true,
      render: (row) => {
        if (own(row)) return units(row.node.total.unidades, true);
        if (row.type === 'variant') return units(row.node.full_unidades_base, true);
        return row.item ? dash : null;
      },
    },
    {
      key: 'valor_erp',
      group: VALOR,
      header: 'ERP',
      label: 'Valor ERP',
      width: 118,
      sortable: true,
      align: 'center',
      fit: true,
      render: (row) => (own(row) ? <Value money={row.node.erp} /> : row.node || row.item ? dash : null),
    },
    {
      key: 'valor_full',
      group: VALOR,
      header: 'Full',
      label: 'Valor Full',
      width: 118,
      sortable: true,
      align: 'center',
      fit: true,
      render: (row) => {
        if (row.node) return <Value money={row.node.full} />;
        if (row.type === 'item') return <Value money={itemFull(row)} />;
        return null;
      },
    },
    {
      key: 'valor_total',
      group: VALOR,
      header: 'Total',
      label: 'Valor total',
      width: 124,
      sortable: true,
      align: 'center',
      fit: true,
      render: (row) => {
        if (row.type === 'group') return <Value money={row.node.total} strong note={<NoCostNote count={row.node.productos_sin_costo} />} />;
        if (row.type === 'product') return <Value money={row.node.total} strong />;
        if (row.type === 'variant') return <Value money={row.node.full} strong />;
        return row.item ? dash : null;
      },
    },
  ];
  if (canSeeSales) {
    columns.push(
      {
        key: 'unidades_7d',
        group: VENTAS,
        header: '7D',
        label: 'Ventas 7D',
        width: 72,
        sortable: true,
        align: 'center',
        fit: true,
        render: (row) => {
          if (row.type === 'item') {
            return (
              <Figure note={isPack(row.owner) ? 'packs' : null} split={splitOf(row, '7d')}>
                {item('unidades_7d', row)}
              </Figure>
            );
          }
          if (!row.node) return null;
          const metrics = metricsOf(row);
          const note = row.type === 'variant' ? packNote(row.node, row.node.ventas?.unidades_7d) : null;
          return (
            <Figure note={note} split={splitOf(row, '7d')}>
              <UnitsCell value={metrics?.units_7d} />
            </Figure>
          );
        },
      },
      {
        key: 'unidades_30d',
        group: VENTAS,
        header: '30D',
        label: 'Ventas 30D',
        width: 100,
        sortable: true,
        align: 'center',
        fit: true,
        render: (row) => {
          if (row.type === 'item') {
            return (
              <Figure note={isPack(row.owner) ? 'packs' : null} split={splitOf(row, '30d')}>
                {item('unidades_30d', row)}
              </Figure>
            );
          }
          if (!row.node) return null;
          const metrics = metricsOf(row);
          const note = row.type === 'variant' ? packNote(row.node, row.node.ventas?.unidades_30d) : null;
          return (
            <Figure note={note} split={splitOf(row, '30d')}>
              <UnitsCell value={metrics?.units_30d} strong />
            </Figure>
          );
        },
      },
      {
        key: 'units_trend',
        group: VENTAS,
        header: 'Tendencia',
        label: 'Tendencia de ventas',
        width: 112,
        align: 'center',
        fit: true,
        render: (row) => (row.type === 'item' ? item('units_trend', row) : row.node ? <UnitsTrendCell metrics={metricsOf(row)} /> : null),
      },
    );
  }
  if (canSeeMargin) {
    columns.push({
      key: 'markup',
      group: MARKUP,
      header: 'Actual',
      label: 'Markup actual',
      width: 100,
      sortable: true,
      align: 'center',
      fit: true,
      render: (row) => (row.type === 'item' ? item('markup', row) : row.node ? <MarkupCell markup={auditMarkup(row.node.markup_actual)} /> : null),
    });
    if (canSeeSales) {
      columns.push(
        {
          key: 'markup_30d',
          group: MARKUP,
          header: 'Real 30D',
          label: 'Markup real 30D',
          width: 84,
          sortable: true,
          align: 'center',
          fit: true,
          render: (row) => (row.type === 'item' ? item('markup_30d', row) : row.node ? <MarkupRealCell metrics={metricsOf(row)} /> : null),
        },
        {
          key: 'markup_trend',
          group: MARKUP,
          header: 'Tendencia',
          label: 'Tendencia de markup',
          width: 112,
          align: 'center',
          fit: true,
          render: (row) => (row.type === 'item' ? item('markup_trend', row) : row.node ? <MarkupTrendCell metrics={metricsOf(row)} /> : null),
        },
      );
    }
  }
  if (canSeeSales) {
    columns.push({
      key: 'facturado_30d',
      group: RESULTADO,
      header: 'Facturado 30D',
      label: 'Facturado 30D',
      width: 130,
      sortable: true,
      align: 'center',
      fit: true,
      render: (row) => (row.type === 'item' ? item('facturado_30d', row) : row.node ? <GrossCell metrics={metricsOf(row)} /> : null),
    });
    if (canSeeMargin) {
      columns.push({
        key: 'total_gauss_30d',
        group: RESULTADO,
        header: 'Total Gauss 30D',
        label: 'Total Gauss 30D',
        width: 130,
        sortable: true,
        align: 'center',
        fit: true,
        render: (row) => (row.type === 'item' ? item('total_gauss_30d', row) : row.node ? <TotalGaussCell metrics={metricsOf(row)} /> : null),
      });
    }
    // Rotación (rotacion S2): a publication shows its own last sale and ageing; its coverage and rotation are its
    // product's (the ERP stock is shared), so they stay on the product and variant rows. A product's or variant's
    // figures are the whole product's, whatever the filter (L2).
    columns.push(
      {
        key: 'ultima_venta',
        group: ROTACION,
        header: 'Última venta',
        label: 'Última venta',
        width: 104,
        sortable: true,
        align: 'center',
        fit: true,
        render: (row) => (row.type === 'item' ? item('last_sale', row) : row.node ? <LastSaleCell metrics={lastSaleOf(row.node.ventas)} note={WHOLE_PRODUCT} /> : null),
      },
      {
        key: 'ageing',
        group: ROTACION,
        header: 'Ageing',
        label: 'Ageing',
        width: 76,
        sortable: true,
        align: 'center',
        fit: true,
        render: (row) => (row.type === 'item' ? item('ageing', row) : row.node ? <AgeingCell metrics={lastSaleOf(row.node.ventas)} note={`Ageing ${WHOLE_PRODUCT}`} /> : null),
      },
      {
        key: 'cobertura',
        group: ROTACION,
        header: <span title={COVERAGE_HINT}>Cobertura</span>,
        label: 'Días de cobertura',
        width: 92,
        sortable: true,
        align: 'center',
        fit: true,
        render: (row) =>
          row.node ? (
            <RotationFigure ventas={row.node.ventas} of={originCoverage}>
              <CoverageCell ventas={row.node.ventas} />
            </RotationFigure>
          ) : row.item ? (
            dash
          ) : null,
      },
      {
        key: 'rotacion',
        group: ROTACION,
        header: <span title={ROTATION_HINT}>Veces</span>,
        label: 'Rotación (veces)',
        width: 76,
        sortable: true,
        align: 'center',
        fit: true,
        render: (row) =>
          row.node ? (
            <RotationFigure ventas={row.node.ventas} of={originRotation}>
              <RotationCell ventas={row.node.ventas} />
            </RotationFigure>
          ) : row.item ? (
            dash
          ) : null,
      },
    );
  }
  // `arrange` (the page's saved layout, pubml-columnas-presets S1-S2) picks and orders them.
  return arrange(columns);
}

export default function StockAuditTable({
  audit,
  canSeeSales,
  canSeeMargin,
  arrange,
  nivel,
  onDrill,
  sort,
  onSort,
  onSelectItem,
  selectedKey,
  offset,
  emptyMessage,
  columnWidths,
  onColumnResize,
}) {
  const columns = buildAuditColumns({
    canSeeSales,
    canSeeMargin,
    rate: audit.data?.tipo_cambio ?? null,
    nivel,
    onToggle: audit.toggle,
    onDrill,
    onMore: audit.loadMore,
    arrange,
  });
  const selectedRowId = selectedKey ? audit.rows.find((row) => row.type === 'item' && row.item.item_id === selectedKey)?.id : undefined;
  return (
    <TableShell
      columns={columns}
      rows={audit.rows}
      getRowKey={(row) => row.id}
      getRowDepth={(row) => row.depth}
      sort={sort}
      onSort={onSort}
      onRowClick={(row, event) => {
        if (row.type === 'item') onSelectItem(row.item, event);
        // A brand or a category drills down (the next level, inside it); without a way down it opens.
        else if (row.type === 'group' && onDrill) onDrill(drillOf(row.node));
        else if (row.node) audit.toggle(row);
      }}
      selectedKey={selectedRowId}
      offset={offset}
      emptyMessage={emptyMessage}
      ariaLabel="Auditoría de stock"
      columnWidths={columnWidths}
      onColumnResize={onColumnResize}
    />
  );
}
