import { formatPppMonto, formatPppFecha } from '../hooks/useProductosOffsets';

/**
 * Subordinate companion line for a PPP (informational purchase cost) figure.
 * Renders under the real cost/markup value it accompanies, visually
 * de-emphasised (smaller/dimmer) — never competes with the real value.
 *
 * - `ppp` is the product's `ppp` payload
 *   (`{ estado, costo, moneda, fecha, markups }`) or `null`/`undefined` when
 *   the product has no qualifying PPP row at all (state 3).
 * - `ppp.estado === "fuera_de_rango"` (state 2, 2026-07-30): the row EXISTS
 *   but is broken and not recoverable (see `costo_ppp_service.py` module
 *   docstring's "Scale sanity guard" / "Recovering USD footprints"
 *   sections). Renders a short "fuera de rango" marker — NEVER a number,
 *   NEVER a markup — distinct from the plain "sin PPP" (no row at all)
 *   state, because this one is actionable (the ERP value needs fixing).
 * - `markupKey` selects which entry of `ppp.markups` to render. When omitted,
 *   renders `ppp.costo` in `ppp.moneda` instead (the cost-cell companion
 *   line) — `costo` is NEVER converted, EXCEPT for a recovered USD-footprint
 *   row (already converted server-side to `ppp.moneda`, the list cost's own
 *   currency, at today's rate — see the backend module docstring). Always
 *   read the currency from `ppp.moneda` (never hardcode/assume it).
 *
 * Display-only: never reads `p.costo` or any list-cost markup as a
 * substitute when `ppp` is absent/unusable — those states render an
 * explicit marker instead.
 */
export default function PppLine({ ppp, markupKey }) {
  if (!ppp) {
    return <div className="ppp-line ppp-line--empty">sin PPP</div>;
  }

  if (ppp.estado === 'fuera_de_rango') {
    return <div className="ppp-line ppp-line--empty">ppp: fuera de rango</div>;
  }

  const fecha = formatPppFecha(ppp.fecha);

  if (!markupKey) {
    const monto = ppp.costo;
    const moneda = ppp.moneda ?? 'ARS';
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
