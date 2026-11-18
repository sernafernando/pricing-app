import { useState } from 'react';
import { createPortal } from 'react-dom';
import { usePermisos } from '../../contexts/PermisosContext';
import { promocionesAPI, publicacionesMlAPI } from '../../services/api';
import ModalTesla from '../ModalTesla';
import { resolverParams } from './bulkParams';
import { BATCH_SIZE } from './BulkStatusActions';
import formStyles from '../promociones/CriteriosAplicacionPanel.module.css';
import styles from './BulkActions.module.css';

const REGION = 'Aplicar criterios de hay mejores';
const AUTO_ON_HINT =
  'Marcá Auto solo para prenderlo en las seleccionadas. Destildado no cambia Auto (no lo apaga). Activarlo es tu responsabilidad.';

const plural = (n, one, many) => (n === 1 ? one : many);

function emptyForm() {
  return {
    c1_activo: false,
    c1_markup_min: '',
    c1_markup_max: '',
    c2_activo: false,
    c2_solo_markup_positivo: true,
    c6_activo: false,
    c6_solo_via_promo: false,
    c6_gap_min: '5000',
    c6_distancia_objetivo: '100',
    auto_aplicacion: false,
  };
}

function toPayload(form) {
  const numOrNull = (value) => {
    if (value === '' || value == null) return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  };
  const payload = {
    c1_activo: form.c1_activo,
    c1_markup_min: numOrNull(form.c1_markup_min),
    c1_markup_max: numOrNull(form.c1_markup_max),
    c2_activo: form.c2_activo,
    c2_solo_markup_positivo: form.c2_solo_markup_positivo,
    c6_activo: form.c6_activo,
    c6_solo_via_promo: form.c6_solo_via_promo,
    c6_gap_min: Number(form.c6_gap_min) || 5000,
    c6_distancia_objetivo: Number(form.c6_distancia_objetivo) || 100,
  };
  // Unchecked = leave Auto as-is on each MLA (never silent mass-OFF).
  if (form.auto_aplicacion) {
    payload.auto_aplicacion = true;
  }
  return payload;
}

function scopeOf(checked) {
  const itemIds = checked?.itemIds ?? [];
  const productIds = checked?.productIds ?? [];
  const rows = itemIds.length + productIds.length;
  if (rows === 0) return { checked: false, suffix: 'las del filtro' };
  const suffix =
    productIds.length > 0
      ? `las de ${rows} ${plural(rows, 'fila marcada', 'filas marcadas')}`
      : plural(rows, 'la marcada', `las ${rows} marcadas`);
  return { checked: true, suffix, itemIds, productIds };
}

function describeResolveError(error, scope) {
  const message = error?.response?.data?.error?.message;
  if (error?.response?.status === 422 && message) return message;
  if (error?.response?.status === 503)
    return scope.checked
      ? 'La consulta tardó demasiado: marcá menos filas o reintentá.'
      : 'La consulta tardó demasiado: acotá los filtros o reintentá.';
  return scope.checked
    ? 'No se pudieron resolver las publicaciones marcadas.'
    : 'No se pudieron resolver las publicaciones del filtro.';
}

/**
 * Bulk apply Criterios de aplicación (C1/C2/C6/Auto) on filter or checked rows.
 * Portals a menuitem into Acciones masivas; confirm modal stays mounted here.
 */
export default function BulkCriteriosAplicacion({
  filters,
  canSeeMargin,
  onDone,
  checked,
  menuSlot = null,
  onChose,
}) {
  const { tienePermiso } = usePermisos();
  const [run, setRun] = useState(null);
  const [form, setForm] = useState(emptyForm);
  const [descartar, setDescartar] = useState(false);
  const canAuto = tienePermiso('promos.auto_aplicacion');

  if (!tienePermiso('promos.escribir')) return null;

  const scope = scopeOf(checked);
  const setField = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  const start = async () => {
    onChose?.();
    setForm(emptyForm());
    setDescartar(false);
    setRun({ phase: 'resolving' });
    try {
      const { data } = scope.checked
        ? await publicacionesMlAPI.hayMejoresCriteriosItemIdsChecked({
            item_ids: scope.itemIds,
            producto_ids: scope.productIds,
          })
        : await publicacionesMlAPI.hayMejoresCriteriosItemIds(resolverParams(filters, canSeeMargin));
      setRun({
        phase: 'editing',
        itemIds: data.item_ids ?? [],
        noAplican: data.no_aplican ?? 0,
      });
    } catch (error) {
      setRun({ phase: 'refused', error: describeResolveError(error, scope) });
    }
  };

  const confirm = async () => {
    const itemIds = run.itemIds ?? [];
    if (!itemIds.length) return;
    const payload = toPayload(form);
    let done = 0;
    let descartadas = 0;
    let omitidas = 0;
    let autoOn = 0;
    let stopped = false;
    setRun({ ...run, phase: 'sending', done: 0 });
    for (let startIdx = 0; startIdx < itemIds.length; startIdx += BATCH_SIZE) {
      try {
        const { data } = await promocionesAPI.setHayMejoresCriteriosBulk({
          ...payload,
          item_ids: itemIds.slice(startIdx, startIdx + BATCH_SIZE),
          descartar_sugerencias: descartar,
        });
        done += data.count ?? 0;
        descartadas += (data.descartadas ?? []).length;
        omitidas += (data.omitidas_auto_fail ?? []).length;
        autoOn += data.auto_on_previas ?? 0;
        setRun((current) => ({ ...current, done }));
      } catch {
        stopped = true;
        break;
      }
    }
    setRun({
      phase: 'done',
      done,
      stopped,
      total: itemIds.length,
      descartadas,
      omitidas,
      autoOn,
    });
    if (done > 0) onDone?.();
  };

  const close = () => {
    if (run?.phase === 'sending') return;
    setRun(null);
  };

  const total = run?.itemIds?.length ?? run?.total ?? 0;
  const menuItem = (
    <button type="button" role="menuitem" className={styles.item} onClick={start}>
      {`Aplicar criterios de hay mejores ${scope.suffix}`}
    </button>
  );

  const modal = run && (
    <ModalTesla
      isOpen
      onClose={close}
      title={REGION}
      size="md"
      closeOnOverlay={false}
      closeOnEsc={run.phase !== 'sending'}
      showCloseButton={run.phase !== 'sending'}
    >
      <section aria-label={REGION} className={styles.statusBody}>
        {run.phase === 'resolving' && <p>Calculando las publicaciones…</p>}
        {run.phase === 'refused' && <p role="alert">{run.error}</p>}
        {run.phase === 'editing' && total === 0 && (
          <p>Ninguna publicación del alcance puede recibir criterios.</p>
        )}
        {run.phase === 'editing' && total > 0 && (
          <>
            <p>
              Se van a aplicar estos criterios a {total}{' '}
              {plural(total, 'publicación', 'publicaciones')}. Los cambios valen para corridas nuevas
              (no re-evalúan flags ya abiertos).
            </p>
            {run.noAplican > 0 && (
              <p className={styles.note}>
                {run.noAplican} {plural(run.noAplican, 'publicación no se toca', 'publicaciones no se tocan')}{' '}
                (borrada o inexistente).
              </p>
            )}
            <div className={formStyles.panel}>
              <label className={formStyles.checkRow}>
                <input
                  type="checkbox"
                  checked={form.c1_activo}
                  onChange={(e) => setField('c1_activo', e.target.checked)}
                />
                C1 — Límite de markup
              </label>
              {form.c1_activo && (
                <div className={formStyles.fieldRow}>
                  <label className={formStyles.field}>
                    <span className={formStyles.fieldLabel}>Mín %</span>
                    <input
                      type="number"
                      step="any"
                      className={formStyles.input}
                      value={form.c1_markup_min}
                      onChange={(e) => setField('c1_markup_min', e.target.value)}
                    />
                  </label>
                  <label className={formStyles.field}>
                    <span className={formStyles.fieldLabel}>Máx %</span>
                    <input
                      type="number"
                      step="any"
                      className={formStyles.input}
                      value={form.c1_markup_max}
                      onChange={(e) => setField('c1_markup_max', e.target.value)}
                    />
                  </label>
                </div>
              )}
              <label className={formStyles.checkRow}>
                <input
                  type="checkbox"
                  checked={form.c2_activo}
                  onChange={(e) => setField('c2_activo', e.target.checked)}
                />
                C2 — Ganar catálogo
              </label>
              {form.c2_activo && (
                <label className={formStyles.checkRowNested}>
                  <input
                    type="checkbox"
                    checked={form.c2_solo_markup_positivo}
                    onChange={(e) => setField('c2_solo_markup_positivo', e.target.checked)}
                  />
                  Solo con markup positivo (&gt; 0)
                </label>
              )}
              <label className={formStyles.checkRow}>
                <input
                  type="checkbox"
                  checked={form.c6_activo}
                  onChange={(e) => setField('c6_activo', e.target.checked)}
                />
                C6 — Techo por monopolio
              </label>
              {form.c6_activo && (
                <>
                  <label className={formStyles.checkRowNested}>
                    <input
                      type="checkbox"
                      checked={form.c6_solo_via_promo}
                      onChange={(e) => setField('c6_solo_via_promo', e.target.checked)}
                    />
                    Solo vía promo
                  </label>
                  <div className={formStyles.fieldRow}>
                    <label className={formStyles.field}>
                      <span className={formStyles.fieldLabel}>Gap mín $</span>
                      <input
                        type="number"
                        step="any"
                        min="0"
                        className={formStyles.input}
                        value={form.c6_gap_min}
                        onChange={(e) => setField('c6_gap_min', e.target.value)}
                      />
                    </label>
                    <label className={formStyles.field}>
                      <span className={formStyles.fieldLabel}>Distancia $</span>
                      <input
                        type="number"
                        step="any"
                        min="0"
                        className={formStyles.input}
                        value={form.c6_distancia_objetivo}
                        onChange={(e) => setField('c6_distancia_objetivo', e.target.value)}
                      />
                    </label>
                  </div>
                </>
              )}
              {canAuto && (
                <>
                  <label className={formStyles.checkRow}>
                    <input
                      type="checkbox"
                      checked={form.auto_aplicacion}
                      onChange={(e) => setField('auto_aplicacion', e.target.checked)}
                    />
                    Auto-aplicación
                  </label>
                  {form.auto_aplicacion && <p className={formStyles.autoHint}>{AUTO_ON_HINT}</p>}
                </>
              )}
              <label className={formStyles.checkRow}>
                <input
                  type="checkbox"
                  checked={descartar}
                  onChange={(e) => setDescartar(e.target.checked)}
                />
                Descartar sugerencias abiertas del alcance (default: no)
              </label>
              {descartar && (
                <p className={styles.note}>
                  No se tocan las sugerencias por fallo de Autoapply. Si alguna publicación ya tenía Auto ON,
                  el aviso de hay mejores puede quedar inconsistente hasta la próxima corrida.
                </p>
              )}
            </div>
          </>
        )}
        {run.phase === 'sending' && <p role="status">{`Aplicando ${run.done} de ${total}…`}</p>}
        {run.phase === 'done' && (
          <div className={styles.summary}>
            {run.stopped && (
              <p role="alert">{`Se cortó después de ${run.done} de ${total}. Las que faltan no se enviaron.`}</p>
            )}
            <p>{`${run.done} ${plural(run.done, 'publicación actualizada', 'publicaciones actualizadas')}.`}</p>
            {run.descartadas > 0 && (
              <p>{`${run.descartadas} sugerencia${run.descartadas === 1 ? '' : 's'} descartada${run.descartadas === 1 ? '' : 's'}.`}</p>
            )}
            {run.omitidas > 0 && (
              <p>{`${run.omitidas} Auto-fail omitida${run.omitidas === 1 ? '' : 's'} (siguen abiertas).`}</p>
            )}
            {run.autoOn > 0 && (
              <p className={styles.note}>
                {`${run.autoOn} ya tenían Auto-aplicación ON antes del lote.`}
              </p>
            )}
          </div>
        )}
        <div className={styles.statusButtons}>
          {run.phase === 'editing' && total > 0 && (
            <button type="button" className="btn-tesla primary sm" onClick={confirm}>
              Aplicar
            </button>
          )}
          {run.phase !== 'sending' && (
            <button type="button" className="btn-tesla ghost sm" onClick={close}>
              {run.phase === 'done' ? 'Cerrar' : 'Cancelar'}
            </button>
          )}
        </div>
      </section>
    </ModalTesla>
  );

  return (
    <>
      {menuSlot ? createPortal(menuItem, menuSlot) : null}
      {modal}
    </>
  );
}
