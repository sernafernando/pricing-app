/**
 * "$X transf." companion hint next to a Tienda Nube (card) price.
 *
 * The card price shown on the storefront is published by `TnPublishModal` as
 * `transferencia * (1 + porcentaje_tarjeta_tn / 100)` and then syncs back down
 * as `tn_price` / `tn_promotional_price`. Recovering the transfer price from
 * it is therefore the exact INVERSE of that surcharge — a DIVISION, not a
 * subtraction. Both sides now read the same `porcentaje_tarjeta_tn` config
 * value; this used to be a hardcoded `* 0.75` that silently disagreed with the
 * publish side as soon as anyone changed the surcharge.
 *
 * Renders nothing when the percentage is not a positive finite number (config
 * not loaded yet, or the key missing — the API degrades an unknown key to 0).
 * The caller keeps showing the raw price on its own: a missing hint is far
 * better than a NaN or a "transfer price" that is really the card price.
 */
export default function PrecioTransfHint({ precioTarjeta, porcentaje, className }) {
  const precio = Number(precioTarjeta);
  const pct = Number(porcentaje);

  if (!Number.isFinite(precio) || !Number.isFinite(pct) || pct <= 0) return null;

  const transferencia = precio / (1 + pct / 100);

  return (
    <span className={className}>
      ${transferencia.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} transf.
    </span>
  );
}
