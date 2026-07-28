import { formatPppMonto, formatPppFecha } from '../hooks/useProductosOffsets';

/**
 * Subordinate companion line for a PPP (informational purchase cost) figure.
 * Renders under the real cost/markup value it accompanies, visually
 * de-emphasised (smaller/dimmer) — never competes with the real value.
 *
 * - `ppp` is the product's `ppp` payload (`{ costo, fecha, markups }`) or
 *   `null`/`undefined` when the product has no qualifying PPP row.
 * - `markupKey` selects which entry of `ppp.markups` to render. When omitted,
 *   renders `ppp.costo` instead (the cost-cell companion line).
 *
 * Display-only: never reads `p.costo` or any list-cost markup as a
 * substitute when `ppp` is absent — that state renders an explicit
 * "sin PPP" marker instead.
 */
export default function PppLine({ ppp, markupKey }) {
  if (!ppp) {
    return <div className="ppp-line ppp-line--empty">sin PPP</div>;
  }

  const fecha = formatPppFecha(ppp.fecha);

  if (!markupKey) {
    const monto = ppp.costo_display ?? ppp.costo;
    const moneda = ppp.costo_display_moneda ?? 'ARS';
    return (
      <div className="ppp-line">
        ppp: {moneda} ${monto?.toFixed(2)} {fecha && `(${fecha})`}
      </div>
    );
  }

  const monto = formatPppMonto(ppp.markups?.[markupKey], markupKey);
  if (monto === null) {
    return <div className="ppp-line ppp-line--empty">sin PPP</div>;
  }

  return (
    <div className="ppp-line">
      ppp: {monto} {fecha && `(${fecha})`}
    </div>
  );
}
