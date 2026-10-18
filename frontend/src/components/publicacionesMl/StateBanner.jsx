import { Info } from 'lucide-react';
import styles from './StateBanner.module.css';

/**
 * The honest-state banner: says WHY a column may read "—" instead of letting
 * the operator guess. Built from the `data_state` block that rides on every
 * list response (`view/status_block.py`), so it costs no extra request.
 *
 * A status that could not be read is NEUTRAL: it is not the operator's
 * problem and the list below is still valid.
 */
const SECONDS_PER_DAY = 86400;

const FLAG_MESSAGES = {
  events: 'Eventos desactivados: no hay último evento ni filtro por evento.',
  links: 'Vínculos con productos desactivados: la columna Vínculo puede estar incompleta.',
  refresh: 'La actualización de publicaciones está desactivada: los datos pueden estar desactualizados.',
};

const RESOURCE_NAMES = {
  sale_price: 'precio de oferta',
  stock: 'stock Full y Propio',
};

/**
 * The block fires when the p95 age passes the threshold, so at least the oldest
 * 5% is stale. It says the real share when the status counted it, and the
 * percentile it measured otherwise: never "most of the data".
 */
function staleMessage(degradation) {
  const days = degradation.stale_days ?? Math.floor((degradation.p95_age_seconds ?? 0) / SECONDS_PER_DAY);
  const { stale_rows: staleRows, checked_rows: checkedRows } = degradation;
  const share =
    Number.isFinite(staleRows) && Number.isFinite(checkedRows) && checkedRows > 0
      ? `el ${Math.max(1, Math.round((100 * staleRows) / checkedRows))}% de las publicaciones`
      : 'el 5% más antiguo';
  return `Parte de los datos está desactualizada: ${share} se actualizó hace más de ${days} días.`;
}

function lines(dataState) {
  if (dataState.available === false) {
    return {
      tone: 'neutral',
      messages: ['No pudimos verificar el estado de la sincronización. La lista se muestra igual.'],
    };
  }
  const messages = [];
  if (dataState.store_empty) messages.push('Todavía no se sincronizó ninguna publicación.');
  const degradations = dataState.degradations ?? [];
  if (dataState.kill_switch) messages.push('La sincronización está pausada (interruptor general): los datos pueden estar desactualizados.');
  for (const degradation of degradations) {
    if (degradation.code === 'flag_disabled' && FLAG_MESSAGES[degradation.flag]) {
      messages.push(FLAG_MESSAGES[degradation.flag]);
    }
    if (degradation.code === 'stale_data') messages.push(staleMessage(degradation));
  }
  const missing = degradations
    .filter((d) => d.code === 'resource_not_collected' && RESOURCE_NAMES[d.resource])
    .map((d) => RESOURCE_NAMES[d.resource]);
  if (missing.length > 0) {
    messages.push(`Solo se sincronizan los datos básicos: no se recolecta ${missing.join(' ni ')}.`);
  }
  if ((dataState.sections_failed ?? []).length > 0) {
    messages.push('No se pudieron leer algunas secciones del estado de la sincronización.');
  }
  return { tone: 'warning', messages };
}

export default function StateBanner({ dataState }) {
  if (!dataState) return null;
  const { tone, messages } = lines(dataState);
  if (messages.length === 0) return null;
  return (
    <div className={styles.banner} role="status" data-tone={tone}>
      <Info size={16} aria-hidden="true" className={styles.icon} />
      <ul className={styles.list}>
        {messages.map((message) => (
          <li key={message}>{message}</li>
        ))}
      </ul>
    </div>
  );
}
