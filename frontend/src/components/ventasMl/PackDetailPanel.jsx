/**
 * PackDetailPanel — the PACK-scoped counterpart of `SaleDetailPanel`
 * (ventas-ml-rediseno PR19, design D14, spec PANEL R22/R23).
 *
 * A pack row opens THIS panel, keyed by `pack_id`, never the order-scoped
 * panel of an arbitrary member order (the bug this PR fixes — see
 * `VentasML.jsx`'s pack row handler). It fetches
 * `GET /ml-ventas-ops/packs/{pack_id}` (BREAKDOWN R36) and renders the
 * pack's own `monto_operacion`, aggregated product list, Total Gauss
 * chain and markup — all pack-wide, never a single member's figures.
 *
 * The member order list lets the operator navigate to any one member's
 * own order-scoped `SaleDetailPanel` (PANEL R23 scenario 10) via
 * `onSelectOrder`, which `VentasML.jsx` wires to `selectOrder` — that
 * switches the URL selection from `pack` to `orden`, so the two panels
 * stay mutually exclusive.
 *
 * Reuses `SaleDetailPanel.module.css`'s section/total/line classes
 * verbatim (same panel shell, same design tokens) instead of duplicating
 * them — only the member-list styling is its own.
 */

import { useCallback, useState } from 'react';
import { X, TriangleAlert } from 'lucide-react';
import { usePackDetail } from '../../hooks/usePackDetail';
import saleStyles from './SaleDetailPanel.module.css';
import styles from './PackDetailPanel.module.css';

const ITEM_LINES_RAZON_LABELS = {
  item_lines_no_items: 'Este pack no tiene ítems cargados.',
  item_lines_orden_sin_items:
    'Una de las órdenes de este pack no tiene ítems cargados, así que el monto de la operación estaría incompleto.',
  item_lines_item_sin_cantidad:
    'Uno o más ítems no tienen cantidad cargada, así que no se puede calcular el monto de la operación.',
  item_lines_item_sin_precio:
    'Uno o más ítems no tienen precio unitario cargado, así que no se puede calcular el monto de la operación.',
};

function formatAmount(value) {
  if (value === null || value === undefined) return '—';
  return new Intl.NumberFormat('es-AR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(value));
}

export default function PackDetailPanel({ packId, onClose, onSelectOrder }) {
  const { pack, loading, errorKind } = usePackDetail(packId);
  const [expandedMembers, setExpandedMembers] = useState(true);
  const toggleMembers = useCallback(() => setExpandedMembers((prev) => !prev), []);

  const itemLines = pack?.item_lines || [];
  const memberOrderIds = pack?.member_order_ids || [];

  return (
    <>
      <div className={saleStyles.header}>
        <h2 className={saleStyles.title}>Desglose del pack {packId}</h2>
        <button
          type="button"
          className={saleStyles.closeButton}
          onClick={onClose}
          aria-label="Cerrar"
        >
          <X size={18} />
        </button>
      </div>

      <div className={saleStyles.body}>
        {loading && <p className={saleStyles.stateText}>Cargando desglose…</p>}

        {!loading && errorKind === 'not_found' && (
          <p className={saleStyles.stateText}>Pack no encontrado.</p>
        )}

        {!loading && errorKind === 'generic' && (
          <p className={saleStyles.stateText}>Error al cargar el desglose del pack.</p>
        )}

        {!loading && !errorKind && !pack && (
          <p className={saleStyles.stateText}>Este pack todavía no tiene desglose disponible.</p>
        )}

        {!loading && !errorKind && pack && (
          <>
            <div className={saleStyles.total}>
              <span className={saleStyles.totalLabel}>Monto de la operación</span>
              <span className={saleStyles.totalMonto}>{formatAmount(pack.monto_operacion)}</span>
            </div>

            {itemLines.length > 0 && (
              <ul className={saleStyles.itemLineList} aria-label="Detalle de productos">
                {itemLines.map((item, index) => (
                  <li
                    key={`${index}-${item.item_id}-${item.variation_id ?? ''}`}
                    className={saleStyles.itemLine}
                  >
                    <span className={saleStyles.itemLineTitle}>
                      {item.title || item.item_id}
                      {item.quantity && item.quantity > 1 ? ` (x${item.quantity})` : ''}
                    </span>
                    <span className={saleStyles.itemLineMonto}>{formatAmount(item.monto)}</span>
                  </li>
                ))}
              </ul>
            )}
            {pack.item_lines_reconcilia === false && (
              <p className={saleStyles.itemLineWarning}>
                {ITEM_LINES_RAZON_LABELS[pack.item_lines_razon] ||
                  'No se pudo calcular el monto de la operación a partir de los productos.'}
              </p>
            )}

            <section className={saleStyles.section} aria-label="Total Gauss del pack">
              <h3 className={saleStyles.sectionTitle}>Total Gauss</h3>
              {pack.total_gauss === null ? (
                <div className={`${saleStyles.total} ${saleStyles.totalIncomplete}`}>
                  <span className={saleStyles.totalLabel}>Total Gauss</span>
                  <span className={saleStyles.totalMonto}>—</span>
                </div>
              ) : (
                <div className={saleStyles.total}>
                  <span className={saleStyles.totalLabel}>Total Gauss</span>
                  <span className={saleStyles.totalMonto}>{formatAmount(pack.total_gauss)}</span>
                </div>
              )}
              <div className={saleStyles.total}>
                <span className={saleStyles.totalLabel}>Markup</span>
                <span className={saleStyles.totalMonto}>
                  {pack.markup === null || pack.markup === undefined
                    ? '—'
                    : `${formatAmount(pack.markup)}%`}
                </span>
              </div>
            </section>

            <section className={saleStyles.section} aria-label="Órdenes del pack">
              <h3 className={saleStyles.sectionTitle}>
                <button
                  type="button"
                  className={styles.membersToggle}
                  aria-expanded={expandedMembers}
                  onClick={toggleMembers}
                >
                  Órdenes del pack ({memberOrderIds.length})
                </button>
              </h3>
              {expandedMembers && (
                <ul className={styles.memberList} aria-label="Órdenes del pack">
                  {memberOrderIds.map((orderId) => (
                    <li key={orderId} className={styles.memberItem}>
                      <button
                        type="button"
                        className={styles.memberButton}
                        onClick={() => onSelectOrder(orderId)}
                      >
                        {orderId}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        )}
      </div>
    </>
  );
}
