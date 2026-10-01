import { ChevronRight } from 'lucide-react';
import styles from '../../pages/VentasML.module.css';
import AlertIcon from './AlertIcon';
import ProductCell from './ProductCell';
import RecalculatingBadge from './RecalculatingBadge';
import StatusPill from './StatusPill';
import { Money, MarkupChip, ProvisionalPill, ShippingId } from './ventasMlCells';
import {
  formatAmount,
  formatDateTime,
  couponAmountOf,
  moneyTitle,
  netoTooltip,
  OPERATION_STATUS_LABELS,
  GOODS_STATUS_LABELS,
  MODO_LOGISTICO_LABELS,
  groupItems,
  groupCategory,
  orderAlertReason,
  groupAlertReason,
} from '../../utils/ventasMlFormat';
import {
  markupTone,
  moneyTone,
  shippingStatusLabel,
  OPERATION_STATUS_TONE,
  GOODS_STATUS_TONE,
  MODO_LOGISTICO_TONE,
} from '../../utils/ventasMlTone';

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
// render needs — see the group-row / member-row cell contexts in
// `VentasML.jsx`.
//
// NINE columns, laid out like the Stitch `listado` design: each cell carries
// a primary value and a muted second line instead of spending a column per
// fact. The old eleven-column layout gave the date, and each status axis,
// a column of its own, which is what left ~90px per money column on a
// 1366px laptop and pushed badges into the next column. Nothing was
// dropped: the date is the Orden cell's second line, the city the
// Comprador's, and both status axes stay visible -- stacked in Estado, each
// still its own pill and its own filter.
//
// `size` is expressed in PIXELS, measured against the real content. They are
// RATIOS, not absolute widths: `VentasML.jsx` renders each one as
// `size / total-of-visible * 100%` in the `<colgroup>`, so the table still
// compresses to whatever room it has instead of overflowing past the card's
// edge.
//
// `minSize` is the narrowest the operator can drag a column, in real pixels
// (`useColumnResize` clamps with it): it is what keeps one column from being
// dragged over its neighbour -- the Producto/Orden overlap bug.

const orderMeta = (ctx) => (ctx.kind === 'group' ? ctx.loneOrder || ctx.orders[0] : ctx.order);

// The shipment every order of a pack shares, or `null` when they disagree
// (then the cell says how many there are instead of picking one).
const sharedShippingId = (orders) => {
  const ids = new Set(orders.map((o) => o.shipping_id).filter((v) => v !== null && v !== undefined));
  return ids.size === 1 ? [...ids][0] : null;
};

const shippingIdCount = (orders) =>
  new Set(orders.map((o) => o.shipping_id).filter((v) => v !== null && v !== undefined)).size;

export const COLUMNS = [
  {
    id: 'alerta',
    header: '',
    headerAriaLabel: 'Alerta',
    size: 36,
    minSize: 36,
    enableResizing: false,
    align: 'center',
    // The alert column has no useful thing to hide behind a picker entry
    // for — it is narrow and carries no information a user would trade away
    // — so it is simply never offered.
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
    size: 315,
    minSize: 200,
    // T6: without Producto the row says nothing — it can never be hidden.
    enableHiding: false,
    cell: (ctx) =>
      ctx.kind === 'group' ? (
        <ProductCell items={groupItems(ctx.orders)} category={groupCategory(ctx.orders)} isPack={ctx.isPack} />
      ) : (
        <ProductCell items={ctx.order.items} category={ctx.order.item_category} variant="member" />
      ),
  },
  {
    id: 'orden',
    header: 'Orden',
    // A 16-digit ML id in mono plus the pack chevron, on one line: the
    // narrowest this column can be without clipping the id.
    size: 170,
    minSize: 150,
    cell: (ctx) => {
      if (ctx.kind === 'member') {
        return <span className={styles.memberOrden}>{ctx.order.order_id}</span>;
      }
      const { group, orders, isPack, isOpen, toggleExpanded } = ctx;
      if (!isPack) {
        return (
          <>
            <span className={styles.orden}>{orders[0]?.order_id ?? group.group_key}</span>
            <span className={styles.subline}>{formatDateTime(group.date_created)}</span>
          </>
        );
      }
      return (
        <>
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
            {/* "Pack " is read by assistive tech as part of the button's
                name; on screen the word lives on the line below, so the
                id alone has the column's width. */}
            <span className={styles.srOnly}>Pack</span> <span className={styles.orden}>{group.pack_id}</span>
          </button>
          <span className={styles.subline}>
            <span className={styles.packLabel}>Pack</span> · <span>{orders.length} órdenes</span> ·{' '}
            {formatDateTime(group.date_created)}
          </span>
        </>
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
    id: 'comprador',
    header: 'Comprador',
    size: 135,
    minSize: 90,
    cell: (ctx) => {
      // A pack-member row never carries its own buyer cell — the buyer is
      // a property of the parcel, shown once on the group row.
      if (ctx.kind === 'member') return null;
      const meta = orderMeta(ctx);
      const where = meta?.city || meta?.province;
      return (
        <>
          <span className={styles.buyer} title={ctx.group.buyer_nickname || undefined}>
            {ctx.group.buyer_nickname || '—'}
          </span>
          {where && (
            <span className={styles.sublineClip} title={[meta.city, meta.province].filter(Boolean).join(', ')}>
              {where}
            </span>
          )}
        </>
      );
    },
  },
  {
    id: 'estado',
    header: 'Estado',
    size: 130,
    minSize: 100,
    // Two pills, one per axis: the money (operación) above the goods
    // (mercadería). They stay independent -- a cancellation with the goods
    // back in the warehouse and one the buyer kept must read differently.
    cell: (ctx) => {
      const entity = ctx.kind === 'group' ? ctx.group : ctx.order;
      return (
        <span className={styles.pillStack}>
          <StatusPill tone={OPERATION_STATUS_TONE[entity.operation_status]} title="Operación (el dinero)">
            {OPERATION_STATUS_LABELS[entity.operation_status] || entity.operation_status}
          </StatusPill>
          <StatusPill tone={GOODS_STATUS_TONE[entity.goods_status]} title="Mercadería (el producto)">
            {GOODS_STATUS_LABELS[entity.goods_status] || entity.goods_status}
          </StatusPill>
        </span>
      );
    },
  },
  {
    id: 'envio',
    header: 'Envío',
    size: 150,
    minSize: 110,
    // The ML shipping id is the identifier an operator pastes into ML's
    // own tools, so it is the cell's identity; the carrier tracking number
    // lives (demoted) in the detail panel.
    cell: (ctx) => {
      const orders = ctx.kind === 'group' ? ctx.orders : [ctx.order];
      const modo = ctx.kind === 'group' ? ctx.group.modo_logistico : ctx.order.modo_logistico;
      const meta = orderMeta(ctx);
      const status = shippingStatusLabel({ status: meta?.shipping_status, substatus: meta?.shipping_substatus });
      const shippingId = sharedShippingId(orders);
      const count = shippingIdCount(orders);
      return (
        <>
          <span className={styles.envioTop}>
            <StatusPill tone={MODO_LOGISTICO_TONE[modo]}>{MODO_LOGISTICO_LABELS[modo] || modo}</StatusPill>
            {status && <span className={styles.envioStatus}>{status}</span>}
          </span>
          {shippingId !== null ? (
            <ShippingId value={shippingId} />
          ) : (
            count > 1 && <span className={styles.subline}>{count} envíos</span>
          )}
        </>
      );
    },
  },
  {
    id: 'importe',
    header: 'Importe',
    size: 125,
    minSize: 100,
    numeric: true,
    cell: (ctx) => {
      const entity = ctx.kind === 'group' ? ctx.group : ctx.order;
      const coupon = couponAmountOf(ctx.kind === 'group' ? ctx.orders : [ctx.order]);
      return (
        <>
          <Money value={entity.total_amount} currencyId={entity.currency_id} />
          {coupon !== null && <span className={styles.subline}>cupón ML $ {formatAmount(coupon)}</span>}
        </>
      );
    },
    cellProps: (ctx) => {
      const entity = ctx.kind === 'group' ? ctx.group : ctx.order;
      return { title: moneyTitle(entity.total_amount, entity.currency_id) };
    },
  },
  {
    id: 'neto',
    header: 'Neto',
    size: 125,
    minSize: 100,
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
            {isRecalc ? (
              <RecalculatingBadge state={order.metrics_state} />
            ) : (
              <Money value={order.neto} currencyId={order.currency_id} tone="headline" />
            )}
          </button>
        );
      }
      const { group, metricsState, isRowClickable, openGroupPanel } = ctx;
      const content =
        metricsState !== 'ok' ? (
          <RecalculatingBadge state={metricsState} />
        ) : (
          <Money value={group.neto} currencyId={group.currency_id} tone="headline" />
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
    size: 135,
    minSize: 110,
    numeric: true,
    // T6: Total Gauss is the other column the screen cannot lose meaning
    // without -- can never be hidden.
    enableHiding: false,
    // The amount sits alone on its line, right-aligned on the same edge as
    // every other money column; the markup and the "Provisorio" flag share
    // the line UNDER it. Beside the amount, the badge pushed the number off
    // that edge and out of the column.
    cell: (ctx) => {
      const entity = ctx.kind === 'group' ? ctx.group : ctx.order;
      const metricsState = ctx.kind === 'group' ? ctx.metricsState : ctx.order.metrics_state || 'ok';
      if (metricsState !== 'ok') {
        return <RecalculatingBadge state={metricsState} />;
      }
      // PR14 review fix P1: a lone sale carries its own markup; a pack row
      // has no single markup of its own (its members show theirs).
      const markup = ctx.kind === 'group' ? ctx.loneOrder?.markup : ctx.order.markup;
      const tone = moneyTone(entity.total_gauss);
      return (
        <>
          <Money
            value={entity.total_gauss}
            currencyId={entity.currency_id}
            tone={tone === 'negative' ? 'negative' : tone === 'positive' ? 'positive' : null}
          />
          {(markupTone(markup) !== null || entity.total_gauss_provisional) && (
            <span className={styles.moneyMeta} data-testid="total-gauss-meta">
              <MarkupChip value={markup} />
              {/* total-gauss-provisorio: the pack sum already includes a
                  member's provisional figure -- flagged at THIS level too. */}
              {entity.total_gauss_provisional && <ProvisionalPill falta={entity.total_gauss_provisional_falta} />}
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
