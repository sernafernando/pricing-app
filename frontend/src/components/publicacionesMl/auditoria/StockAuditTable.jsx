import { ChevronDown, ChevronRight, Cpu, Tag, TriangleAlert } from 'lucide-react';
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
import { auditMarkup, auditMetrics, fromVariants, isPack, valueOf } from './stockAuditRows';
import cellStyles from '../cells.module.css';
import nodeStyles from '../NodeCells.module.css';
import styles from './StockAudit.module.css';

/**
 * The Auditoría de stock table (approved mock v2): product › variante › publicación, grouped columns Stock
 * (unidades), Valor stock (USD · ARS), Ventas (unidades), Markup con sell in / sell out, Resultado and Rotación. Every column
 * but the first can be hidden (`AUDIT_COLUMN_OPTIONS`, the page's picker); the sortable ones send their key as the
 * backend's `orden`. A publication row draws the list's own cells (`buildColumns`), so it reads like everywhere else.
 */

const STOCK = 'Stock (unidades)';
const VALOR = 'Valor stock (USD · ARS)';
const VENTAS = 'Ventas (unidades)';
const MARKUP = 'Markup con sell in / sell out';
const RESULTADO = 'Resultado';
const ROTACION = 'Rotación';

const MONEY = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 0 });
const dash = <span className={cellStyles.empty}>—</span>;

/** A figure with an optional note under it ("12 de variantes", "25 packs"). */
function Figure({ children, note, strong = false }) {
  return (
    <div className={`${cellStyles.stack} ${cellStyles.stackEnd}`}>
      <span className={strong ? styles.strong : undefined}>{children}</span>
      {note && <span className={styles.figureNote}>{note}</span>}
    </div>
  );
}

/** A stock value: USD on the first line, ARS under it in the muted mono; "—" when unknown. */
function Value({ money, strong = false }) {
  if (!money || (money.usd == null && money.ars == null)) return dash;
  return (
    <div className={`${cellStyles.stack} ${cellStyles.stackEnd}`}>
      <span className={`${styles.usd} ${strong ? styles.strong : ''}`}>{money.usd == null ? '—' : MONEY.format(money.usd)}</span>
      <span className={styles.ars}>{money.ars == null ? '—' : `$ ${MONEY.format(money.ars)}`}</span>
    </div>
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

/** Días de cobertura (rotacion S2): the stock now at the last 30 days' pace; "∞" with stock and no sale (L1 Q2). */
function CoverageCell({ ventas }) {
  if (ventas?.cobertura_infinita) {
    return (
      <span className={`${styles.rotationFigure} ${styles.infinite}`} aria-label="Días de cobertura" title="Con stock y sin ventas en 30 días">
        ∞
      </span>
    );
  }
  if (ventas?.dias_cobertura == null) return dash;
  return (
    <span className={styles.rotationFigure} aria-label="Días de cobertura">
      {formatUnits(Math.round(ventas.dias_cobertura))}
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
  const title = approximate
    ? `Aproximado: sobre el stock actual (${stock}), todavía no hay fotos diarias del stock`
    : `Ventas 30D sobre el stock promedio de ${formatUnits(days)} ${days === 1 ? 'día' : 'días'} (${stock})`;
  return (
    <span className={styles.rotationFigure} aria-label="Rotación (veces)" title={title}>
      {approximate ? `≈ ${formatRatio(ventas.rotacion)}` : formatRatio(ventas.rotacion)}
    </span>
  );
}

/** The Board's last sale and ageing of a product or variant, in the list cells' shape. */
const lastSaleOf = (ventas) => (ventas ? { last_sale_at: ventas.ultima_venta, ageing_days: ventas.ageing_dias } : null);

function buildAuditColumns({ canSeeSales, canSeeMargin, rate, onToggle, onMore, isVisible }) {
  // A publication draws the list's own cells (Tipo, Estado, sales, markups, Total Gauss).
  const list = Object.fromEntries(buildColumns({ eventsEnabled: false, canSeeSales, canSeeMargin }).map((column) => [column.key, column]));
  const item = (key, row) => list[key].render(row.item);

  const metricsOf = (row) => {
    if (row.type === 'product') return auditMetrics(row.node.ventas);
    const factor = isPack(row.node) ? Number(row.node.cantidad) : 1;
    return auditMetrics(row.node.ventas, factor);
  };
  // A publication's Full value: its units at its node's cost.
  const itemFull = (row) => valueOf(row.item.stock?.full ?? null, row.owner, rate);

  const columns = [
    {
      key: 'descripcion',
      header: 'Producto › Variante › Publicación',
      label: 'Producto',
      width: 400,
      minWidth: 260,
      fill: true,
      resizable: true,
      resizeLabel: 'Producto',
      sortable: true,
      render: (row) => {
        if (row.type === 'product' || row.type === 'variant') return <NodeTitleCell row={row} onToggle={onToggle} />;
        if (row.type === 'item') return item('titulo', row);
        return <BranchState row={row} onMore={onMore} onRetry={onMore} />;
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
      render: (row) => (row.type === 'product' || row.type === 'variant' ? <PromoCounts counts={row.node.promo_counts} /> : null),
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
      render: (row) => (row.type === 'product' ? <StockQuantity value={row.node.erp.unidades} /> : row.node || row.item ? dash : null),
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
        if (row.type === 'product') return units(row.node.total.unidades, true);
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
      render: (row) => (row.type === 'product' ? <Value money={row.node.erp} /> : row.node || row.item ? dash : null),
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
        if (row.type === 'product' || row.type === 'variant') return <Value money={row.node.full} />;
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
          if (row.type === 'item') return <Figure note={isPack(row.owner) ? 'packs' : null}>{item('unidades_7d', row)}</Figure>;
          if (!row.node) return null;
          const metrics = metricsOf(row);
          const note = row.type === 'variant' ? packNote(row.node, row.node.ventas?.unidades_7d) : null;
          return <Figure note={note}>{<UnitsCell value={metrics?.units_7d} />}</Figure>;
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
          if (row.type === 'item') return <Figure note={isPack(row.owner) ? 'packs' : null}>{item('unidades_30d', row)}</Figure>;
          if (!row.node) return null;
          const metrics = metricsOf(row);
          let note = null;
          if (row.type === 'variant') note = packNote(row.node, row.node.ventas?.unidades_30d);
          else {
            const { sold, source } = fromVariants(row.node);
            note = sold > 0 ? `${formatUnits(sold)} ${source}` : null;
          }
          return <Figure note={note}>{<UnitsCell value={metrics?.units_30d} strong />}</Figure>;
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
    // product's (the ERP stock is shared), so they stay on the product and variant rows.
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
        render: (row) => (row.type === 'item' ? item('last_sale', row) : row.node ? <LastSaleCell metrics={lastSaleOf(row.node.ventas)} /> : null),
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
        render: (row) => (row.type === 'item' ? item('ageing', row) : row.node ? <AgeingCell metrics={lastSaleOf(row.node.ventas)} /> : null),
      },
      {
        key: 'cobertura',
        group: ROTACION,
        header: 'Cobertura',
        label: 'Días de cobertura',
        width: 92,
        sortable: true,
        align: 'center',
        fit: true,
        render: (row) => (row.node ? <CoverageCell ventas={row.node.ventas} /> : row.item ? dash : null),
      },
      {
        key: 'rotacion',
        group: ROTACION,
        header: 'Veces',
        label: 'Rotación (veces)',
        width: 76,
        sortable: true,
        align: 'center',
        fit: true,
        render: (row) => (row.node ? <RotationCell ventas={row.node.ventas} /> : row.item ? dash : null),
      },
    );
  }
  return columns.filter((column) => column.key === 'descripcion' || isVisible(column.key));
}

export default function StockAuditTable({
  audit,
  canSeeSales,
  canSeeMargin,
  isVisible,
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
    onToggle: audit.toggle,
    onMore: audit.loadMore,
    isVisible,
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
        else if (row.type === 'product' || row.type === 'variant') audit.toggle(row);
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
