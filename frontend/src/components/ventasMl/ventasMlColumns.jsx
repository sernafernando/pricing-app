import { ChevronRight } from 'lucide-react';
import styles from '../../pages/VentasML.module.css';
import AlertIcon from './AlertIcon';
import ProductCell from './ProductCell';
import RecalculatingBadge from './RecalculatingBadge';
import {
  formatDate,
  formatMoney,
  moneyTitle,
  netoTooltip,
  OPERATION_STATUS_LABELS,
  OPERATION_STATUS_BADGE_CLASS,
  GOODS_STATUS_LABELS,
  GOODS_STATUS_BADGE_CLASS,
  MODO_LOGISTICO_LABELS,
  MODO_LOGISTICO_BADGE_CLASS,
  groupItems,
  groupCategory,
  orderAlertReason,
  groupAlertReason,
} from '../../utils/ventasMlFormat';

// Single source of truth for the Ventas ML table's columns
// (ventas-ml-columnas): both the header (via `@tanstack/react-table`, used
// ONLY as a column-geometry engine — see `ventasMlTableHelpers.js`) AND the
// body cells — for BOTH the group row and its expanded pack-member rows —
// render from this one list, so adding/removing/hiding a column can never
// desync the header from either row kind (T4: the member rows MUST render
// the exact same visible columns, in the same order, as their parent —
// otherwise every cell after a hidden column shifts and money ends up
// under the wrong header).
//
// `cell(ctx)` is called once per row with a context object carrying
// EITHER a group row (`ctx.kind === 'group'`) or a single pack-member
// order (`ctx.kind === 'member'`) plus whatever per-row handlers that
// render needs — see `the group-row cell context`/`the member-row cell context` in
// `VentasML.jsx`.
//
// `size` is in PIXELS, measured against the real content (see
// `odd/tasks/ventas-ml-columnas.md`), not a percentage — that is the whole
// point of this change: a percentage table can shrink `colProducto` to
// eight characters and there is no way to tell from the CSS alone that
// this will happen.
export const COLUMNS = [
  {
    id: 'alerta',
    header: '',
    headerAriaLabel: 'Alerta',
    size: 32,
    align: 'center',
    // The alert column has no useful thing to hide behind a picker entry
    // for — it is 32px and carries no information a user would trade away
    // — but it is not in the "must stay visible" set either; it is simply
    // never offered. `enableHiding: false` keeps it out of the picker via
    // `table.getAllLeafColumns()` filtering in `ColumnPicker`.
    enableHiding: false,
    cell: (ctx) =>
      ctx.kind === 'group' ? (
        <AlertIcon level={ctx.groupLevel} reason={groupAlertReason(ctx.orders, ctx.groupLevel)} />
      ) : (
        <AlertIcon level={ctx.order.alert_level} reason={orderAlertReason(ctx.order)} />
      ),
  },
  {
    id: 'producto',
    header: 'Producto',
    size: 320,
    // T6: without Producto the row says nothing — it can never be hidden.
    enableHiding: false,
    cell: (ctx) =>
      ctx.kind === 'group' ? (
        <ProductCell items={groupItems(ctx.orders)} category={groupCategory(ctx.orders)} />
      ) : (
        <ProductCell items={ctx.order.items} category={ctx.order.item_category} />
      ),
  },
  {
    id: 'orden',
    header: 'Orden',
    size: 120,
    cell: (ctx) => {
      if (ctx.kind === 'member') {
        return <span className={styles.memberOrden}>{ctx.order.order_id}</span>;
      }
      const { group, orders, isPack, isOpen, toggleExpanded } = ctx;
      if (!isPack) {
        return <span className={styles.orden}>{orders[0]?.order_id ?? group.group_key}</span>;
      }
      return (
        <button
          type="button"
          className={styles.packToggle}
          aria-expanded={isOpen}
          onClick={(e) => {
            e.stopPropagation();
            toggleExpanded(group.group_key);
          }}
        >
          <ChevronRight
            size={14}
            className={`${styles.chevron} ${isOpen ? styles.chevronOpen : ''}`}
            aria-hidden="true"
          />
          <span>
            <span className={styles.orden}>Pack {group.pack_id}</span>
            <span className={styles.subline}>{orders.length} órdenes</span>
          </span>
        </button>
      );
    },
    // NOT hideable, and not because of the data it shows: this cell holds
    // `packToggle` (`aria-expanded`), the ONLY control that expands a pack and
    // reveals the orders inside it. Hidden, a pack's members are unreachable
    // by mouse and by keyboard alike -- and the choice is persisted in
    // localStorage, so the operator stays stuck with it across reloads with
    // nothing on screen explaining why packs stopped opening. Hiding a column
    // is meant to drop information you do not need, never functionality.
    enableHiding: false,
  },
  {
    id: 'fecha',
    header: 'Fecha',
    size: 90,
    cell: (ctx) => formatDate(ctx.kind === 'group' ? ctx.group.date_created : ctx.order.date_created),
    cellProps: () => ({ className: styles.fecha }),
  },
  {
    id: 'comprador',
    header: 'Comprador',
    size: 130,
    cell: (ctx) => {
      // A pack-member row never carries its own buyer cell — the buyer is
      // a property of the parcel, shown once on the group row.
      if (ctx.kind === 'member') return null;
      return ctx.group.buyer_nickname || '—';
    },
    cellProps: (ctx) =>
      ctx.kind === 'group' ? { title: ctx.group.buyer_nickname || undefined, className: styles.buyer } : {},
  },
  {
    id: 'operacion',
    header: 'Operación',
    size: 120,
    cell: (ctx) => {
      const status = ctx.kind === 'group' ? ctx.group.operation_status : ctx.order.operation_status;
      return (
        <span className={`badge ${OPERATION_STATUS_BADGE_CLASS[status] || 'badge-neutral'}`}>
          {OPERATION_STATUS_LABELS[status] || status}
        </span>
      );
    },
  },
  {
    id: 'mercaderia',
    header: 'Mercadería',
    size: 155,
    cell: (ctx) => {
      const status = ctx.kind === 'group' ? ctx.group.goods_status : ctx.order.goods_status;
      return (
        <span className={`badge ${GOODS_STATUS_BADGE_CLASS[status] || 'badge-neutral'}`}>
          {GOODS_STATUS_LABELS[status] || status}
        </span>
      );
    },
  },
  {
    id: 'envio',
    header: 'Envío',
    size: 110,
    cell: (ctx) => {
      if (ctx.kind === 'member') {
        const order = ctx.order;
        return (
          <>
            <span className={`badge ${MODO_LOGISTICO_BADGE_CLASS[order.modo_logistico] || 'badge-neutral'}`}>
              {MODO_LOGISTICO_LABELS[order.modo_logistico] || order.modo_logistico}
            </span>
            {(order.city || order.province || order.shipping_substatus) && (
              <span className={styles.subline}>
                {[order.city, order.province].filter(Boolean).join(', ') || '—'}
                {order.shipping_substatus ? ` · ${order.shipping_substatus}` : ''}
              </span>
            )}
          </>
        );
      }
      const { group, loneOrder } = ctx;
      return (
        <>
          <span className={`badge ${MODO_LOGISTICO_BADGE_CLASS[group.modo_logistico] || 'badge-neutral'}`}>
            {MODO_LOGISTICO_LABELS[group.modo_logistico] || group.modo_logistico}
          </span>
          {/* PR14 review fix P1: a lone sale has no pack-member block to
              render this in -- it must carry its own subline. */}
          {loneOrder && (loneOrder.city || loneOrder.province || loneOrder.shipping_substatus) && (
            <span className={styles.subline}>
              {[loneOrder.city, loneOrder.province].filter(Boolean).join(', ') || '—'}
              {loneOrder.shipping_substatus ? ` · ${loneOrder.shipping_substatus}` : ''}
            </span>
          )}
        </>
      );
    },
  },
  {
    id: 'importe',
    header: 'Importe',
    size: 115,
    numeric: true,
    cell: (ctx) => {
      const entity = ctx.kind === 'group' ? ctx.group : ctx.order;
      return formatMoney(entity.total_amount, entity.currency_id);
    },
    cellProps: (ctx) => {
      const entity = ctx.kind === 'group' ? ctx.group : ctx.order;
      return { title: moneyTitle(entity.total_amount, entity.currency_id) };
    },
  },
  {
    id: 'neto',
    header: 'Neto',
    size: 115,
    numeric: true,
    cell: (ctx) => {
      if (ctx.kind === 'member') {
        const order = ctx.order;
        const isRecalc = order.metrics_state && order.metrics_state !== 'ok';
        return (
          // PR14 review fix P2: this button IS the keyboard route to the
          // detail panel -- it must survive every metrics_state, carrying
          // the badge as its content instead of being replaced by it.
          <button
            type="button"
            className={styles.netoButton}
            aria-label="Ver desglose de costos"
            title={isRecalc ? undefined : netoTooltip(order.neto_depositado, order.retenciones_recuperables)}
            onClick={(e) => {
              e.stopPropagation();
              ctx.openDrawer(order.order_id);
            }}
          >
            {isRecalc ? <RecalculatingBadge state={order.metrics_state} /> : formatMoney(order.neto, order.currency_id)}
          </button>
        );
      }
      const { group, metricsState, isRowClickable, openGroupPanel } = ctx;
      const content =
        metricsState !== 'ok' ? (
          <RecalculatingBadge state={metricsState} />
        ) : (
          formatMoney(group.neto, group.currency_id)
        );
      if (isRowClickable) {
        return (
          // PR19: opens the SAME panel the row itself opens -- pack-scoped
          // for a pack, order-scoped for a lone sale.
          <button
            type="button"
            className={styles.netoButton}
            aria-label="Ver desglose de costos"
            title={metricsState === 'ok' ? netoTooltip(group.neto_depositado, group.retenciones_recuperables) : undefined}
            onClick={(e) => {
              e.stopPropagation();
              openGroupPanel();
            }}
          >
            {content}
          </button>
        );
      }
      return content;
    },
    // NOT hideable, same reason as `orden`: this cell holds the
    // `aria-label="Ver desglose de costos"` button, which is the KEYBOARD
    // route into the breakdown panel (the row's own click handler is a
    // mouse-only shortcut). Hide this column and the panel has no keyboard
    // route at all, on group rows and member rows both.
    enableHiding: false,
  },
  {
    id: 'total_gauss',
    header: 'Total Gauss',
    size: 120,
    numeric: true,
    // T6: Total Gauss is the other column the screen cannot lose meaning
    // without -- can never be hidden.
    enableHiding: false,
    cell: (ctx) => {
      if (ctx.kind === 'member') {
        const order = ctx.order;
        if (order.metrics_state && order.metrics_state !== 'ok') {
          return <RecalculatingBadge state={order.metrics_state} />;
        }
        return (
          <>
            {formatMoney(order.total_gauss, order.currency_id)}
            {order.total_gauss_provisional && (
              <span
                className={`badge badge-warning ${styles.provisionalBadge}`}
                title={`Calculado sin ${(order.total_gauss_provisional_falta || 'Envío Flex').toLowerCase()}: todavía no se cargó la etiqueta de envío.`}
              >
                Provisorio
              </span>
            )}
            {order.markup !== null && order.markup !== undefined && (
              <span className={styles.markup}>
                {new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 }).format(order.markup)}%
              </span>
            )}
          </>
        );
      }
      const { group, metricsState, loneOrder } = ctx;
      if (metricsState !== 'ok') {
        return <RecalculatingBadge state={metricsState} />;
      }
      return (
        <>
          {formatMoney(group.total_gauss, group.currency_id)}
          {/* total-gauss-provisorio: the pack sum already includes a
              member's provisional figure -- the badge says so at THIS
              level too. */}
          {group.total_gauss_provisional && (
            <span
              className={`badge badge-warning ${styles.provisionalBadge}`}
              title={`Calculado sin ${(group.total_gauss_provisional_falta || 'Envío Flex').toLowerCase()}: todavía no se cargó la etiqueta de envío.`}
            >
              Provisorio
            </span>
          )}
          {/* PR14 review fix P1: markup was only ever rendered inside the
              pack-member block -- a lone sale must carry its own. */}
          {loneOrder && loneOrder.markup !== null && loneOrder.markup !== undefined && (
            <span className={styles.markup}>
              {new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 }).format(loneOrder.markup)}%
            </span>
          )}
        </>
      );
    },
    cellProps: (ctx) => {
      const entity = ctx.kind === 'group' ? ctx.group : ctx.order;
      const metricsState = ctx.kind === 'group' ? ctx.metricsState : ctx.order.metrics_state;
      return { title: moneyTitle(entity.total_gauss, entity.currency_id, metricsState) };
    },
  },
];

export const LOCKED_VISIBLE_COLUMN_IDS = COLUMNS.filter((c) => c.enableHiding === false).map((c) => c.id);
