import { useEffect, useState } from 'react';
import { productosAPI } from '../../../services/api';
import { Change } from './FeedParts';
import styles from './panel.module.css';

/** The kinds of change the app logs (`TipoAccion`). An unknown one gets a generic label, never its code. */
const KIND_LABELS = {
  modificar_precio_clasica: 'Precio Clásica',
  modificar_precio_web: 'Precio Web',
  activar_rebate: 'Activar rebate',
  desactivar_rebate: 'Desactivar rebate',
  modificar_porcentaje_rebate: '% de rebate',
  marcar_out_of_cards: 'Out of Cards activado',
  desmarcar_out_of_cards: 'Out of Cards desactivado',
  activar_web_transferencia: 'Web transferencia activada',
  desactivar_web_transferencia: 'Web transferencia desactivada',
  modificacion_masiva: 'Modificación masiva',
  tn_despublicar: 'Despublicado en Tienda Nube',
  tn_publicar: 'Publicado en Tienda Nube',
  pxq_precio_publicado: 'Precio PxQ publicado',
  ml_vinculo_manual: 'Vínculo manual a publicación',
  ml_vinculo_sin_producto: 'Publicación marcada sin producto',
  ml_vinculo_automatico: 'Vínculo automático a publicación',
  sell_in_compra_creada: 'Compra de sell in cargada',
  sell_in_compra_anulada: 'Compra de sell in anulada',
  sell_in_bono_creado: 'Bono de sell in cargado',
  sell_in_bono_editado: 'Bono de sell in editado',
  sell_in_bono_anulado: 'Bono de sell in anulado',
  sell_in_compra_bono_actualizada: 'Compra de sell in actualizada por bono',
  sell_out_campana_creada: 'Campaña de sell out cargada',
  sell_out_campana_editada: 'Campaña de sell out editada',
  sell_out_campana_anulada: 'Campaña de sell out anulada',
  sell_out_campana_tc_definido: 'Tipo de cambio de campaña definido',
};

const GENERIC_KIND_LABEL = 'Otro cambio';

const NUMBER = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 2 });

// The server stores the moment in UTC without a zone; shown in Buenos Aires, like Productos' history.
const WHEN = new Intl.DateTimeFormat('es-AR', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
  timeZone: 'America/Argentina/Buenos_Aires',
});

function when(value) {
  const at = new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`);
  return Number.isNaN(at.getTime()) ? value : WHEN.format(at).replace(', ', ' ');
}

/** A logged value in words; a side the change does not have stays `null`. */
function show(value) {
  if (value === undefined || value === null) return null;
  if (typeof value === 'boolean') return value ? 'Sí' : 'No';
  if (typeof value === 'number') return NUMBER.format(value);
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

/** `precio_lista_ml` as "Precio lista ml". */
const fieldLabel = (key) => {
  const words = key.replace(/_/g, ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
};

/** Every field either side logged, in the order they first appear. */
function lines(before, after) {
  const keys = [...new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})])];
  return keys.map((key) => ({ key, before: show(before?.[key]), after: show(after?.[key]) }));
}

function describeError(error) {
  if (error?.response?.status === 403) return 'No tenés permiso para ver el historial de cambios.';
  return 'No se pudo cargar el historial de cambios.';
}

function Entry({ entry }) {
  return (
    <li>
      <article className={styles.entry}>
        <div className={styles.entryHead}>
          <h4 className={`${styles.entryTitle} ${styles.changeKind}`}>{KIND_LABELS[entry.tipo_accion] ?? GENERIC_KIND_LABEL}</h4>
          <time className={styles.entryWhen} dateTime={entry.fecha_cambio}>
            {when(entry.fecha_cambio)}
          </time>
        </div>
        <span className={styles.note}>
          {entry.usuario_nombre} · {entry.usuario_email}
        </span>
        <div className={styles.lines}>
          {lines(entry.valores_anteriores, entry.valores_nuevos).map((line) => (
            <div key={line.key} className={styles.line} data-line="">
              <span className={styles.lineLabel}>{fieldLabel(line.key)}</span>
              <Change before={line.before} after={line.after} />
            </div>
          ))}
        </div>
        {entry.comentario && <p className={styles.note}>{entry.comentario}</p>}
      </article>
    </li>
  );
}

/**
 * The changes made in the app to one product, newest first: the same log Productos' "Historial de Cambios" reads
 * (`GET /productos/{id}/auditoria`), with who made each one. Not Mercado Libre's own history (a publication's
 * Historial tab). Self-contained so the panel can place it anywhere; mount it with `key={productItemId}`.
 *
 * @param {object} props
 * @param {number} props.productItemId The ERP product.
 */
export default function ProductChangesTab({ productItemId }) {
  const [feed, setFeed] = useState({ status: 'loading', entries: [], error: null });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let current = true;
    productosAPI
      .auditoria(productItemId)
      .then(({ data }) => current && setFeed({ status: 'ready', entries: Array.isArray(data) ? data : [], error: null }))
      .catch((error) => current && setFeed({ status: 'error', entries: [], error }));
    return () => {
      current = false;
    };
  }, [productItemId, attempt]);

  const retry = () => {
    setFeed({ status: 'loading', entries: [], error: null });
    setAttempt((n) => n + 1);
  };

  if (feed.status === 'loading') {
    return (
      <p className={styles.note} role="status">
        Cargando historial de cambios…
      </p>
    );
  }
  if (feed.status === 'error') {
    return (
      <div className={styles.error} role="alert">
        <span>{describeError(feed.error)}</span>
        <button type="button" className="btn-tesla outline sm" onClick={retry}>
          Reintentar
        </button>
      </div>
    );
  }
  if (feed.entries.length === 0) return <p className={styles.note}>No hay cambios hechos desde la app en este producto.</p>;
  return (
    <ul className={styles.entries}>
      {feed.entries.map((entry) => (
        <Entry key={entry.id} entry={entry} />
      ))}
    </ul>
  );
}
