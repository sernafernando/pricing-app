import { formatPct } from '../../utils/metricasMlFormat';
import styles from './cells.module.css';

/** Why the backend could not compute a markup (`view/markup.py` `REASON_*`). */
export const MARKUP_REASONS = {
  sin_vinculo: 'La publicación no está vinculada a un producto',
  sin_costo: 'El producto vinculado no tiene costo',
  sin_comision: 'No hay comisión para la lista de precios de la publicación',
  sin_precio: 'La publicación no tiene precio',
  ads_sin_ventas: 'Hay costo de Ads pero no hubo unidades vendidas',
};
const UNKNOWN_REASON = 'No se pudo calcular el markup';

/**
 * "12,0% – 18,0%" for a range, "15,0%" when every variation agrees. The figures
 * are the server's (P6); a null range is "—" with the reason as tooltip, never
 * 0. A real 0% stays "0,0%".
 */
export function formatMarkupRange(min, max) {
  return min === max ? formatPct(min) : `${formatPct(min)} – ${formatPct(max)}`;
}

/** Markup of a publication (`row.markup`, only with `ml_metricas.ver_ganancia`). */
export default function MarkupCell({ markup }) {
  if (markup == null) return <span className={styles.empty}>—</span>;
  if (markup.min == null || markup.max == null) {
    return (
      <span className={styles.empty} title={MARKUP_REASONS[markup.reason] ?? UNKNOWN_REASON}>
        —
      </span>
    );
  }
  const partial = markup.partial ?? 0;
  return (
    <div className={`${styles.stack} ${styles.stackEnd}`}>
      <span className={styles.markup} data-negative={markup.any_negative ? '' : undefined}>
        {formatMarkupRange(markup.min, markup.max)}
      </span>
      {partial > 0 && (
        <span
          className={styles.note}
          title={`${partial} ${partial === 1 ? 'variación sin costo no entra' : 'variaciones sin costo no entran'} en el rango`}
        >
          (parcial)
        </span>
      )}
    </div>
  );
}
