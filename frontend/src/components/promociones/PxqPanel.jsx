import { useState } from 'react';
import { pxqAPI } from '../../services/api';
import { useLazyResource } from '../../hooks/useLazyResource';
import { usePermisos } from '../../contexts/PermisosContext';
import styles from './promociones.module.css';

const MAX_TIERS = 5;

function extractErrorMessage(err) {
  const detail = err?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && typeof detail.reason === 'string') return detail.reason;
  return 'No se pudo guardar el tramo.';
}

// Whole-shipment cost the user reads off ML's wholesale simulator. There is
// deliberately no default and no per-unit fallback here — that fallback is
// the exact silent-wrong-price bug the backend's `costo_envio_total`-required
// rule makes structurally impossible (see design.md). A tier missing it is
// `incompleto` and is never written to MercadoLibre.
function isIncomplete(tier) {
  return tier.costo_envio_total === null || tier.costo_envio_total === undefined;
}

function emptyForm() {
  return { cantidad_minima: '', precio_unitario: '', costo_envio_total: '' };
}

function buildBody(form) {
  return {
    cantidad_minima: Number(form.cantidad_minima),
    precio_unitario: Number(form.precio_unitario),
    costo_envio_total: form.costo_envio_total === '' ? null : Number(form.costo_envio_total),
  };
}

/**
 * The tier authoring form (PR 4c): create/edit/delete against our own CRUD
 * endpoints only — no MercadoLibre traffic. Requires `pxq.escribir`; a
 * `pxq.ver`-only user sees the read columns above with no editing affordance
 * at all, rather than buttons that would 403.
 */
function PxqTierAuthoring({ itemId, mirrorTiers, onChanged }) {
  const [createForm, setCreateForm] = useState(emptyForm);
  const [createError, setCreateError] = useState(null);
  const [creating, setCreating] = useState(false);

  const [editingId, setEditingId] = useState(null);
  const [editForm, setEditForm] = useState(emptyForm);
  const [editError, setEditError] = useState(null);
  const [saving, setSaving] = useState(false);

  const [deletingId, setDeletingId] = useState(null);
  const [deleteError, setDeleteError] = useState(null);

  const atMax = mirrorTiers.length >= MAX_TIERS;

  function startEdit(tier) {
    setEditingId(tier.id);
    setEditError(null);
    setEditForm({
      cantidad_minima: String(tier.cantidad_minima),
      precio_unitario: String(tier.precio_unitario),
      costo_envio_total: tier.costo_envio_total === null || tier.costo_envio_total === undefined ? '' : String(tier.costo_envio_total),
    });
  }

  function cancelEdit() {
    setEditingId(null);
    setEditError(null);
  }

  async function handleCreate(event) {
    event.preventDefault();
    setCreating(true);
    setCreateError(null);
    try {
      await pxqAPI.createTier(itemId, buildBody(createForm));
      setCreateForm(emptyForm());
      await onChanged();
    } catch (err) {
      setCreateError(extractErrorMessage(err));
    } finally {
      setCreating(false);
    }
  }

  async function handleSaveEdit(tierId) {
    setSaving(true);
    setEditError(null);
    try {
      await pxqAPI.updateTier(itemId, tierId, buildBody(editForm));
      setEditingId(null);
      await onChanged();
    } catch (err) {
      setEditError(extractErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function handleConfirmDelete(tierId) {
    setDeleteError(null);
    try {
      await pxqAPI.deleteTier(itemId, tierId);
      setDeletingId(null);
      await onChanged();
    } catch (err) {
      setDeleteError(extractErrorMessage(err));
    }
  }

  return (
    <div className={styles.pxqAuthoring}>
      <div className={styles.pxqColumnTitle}>Editar tramos</div>
      {mirrorTiers.map((tier) =>
        editingId === tier.id ? (
          <form
            key={tier.id}
            className={styles.pxqTierEditRow}
            onSubmit={(event) => {
              event.preventDefault();
              handleSaveEdit(tier.id);
            }}
          >
            <label htmlFor={`pxq-edit-cantidad-${tier.id}`}>Cantidad mínima</label>
            <input
              id={`pxq-edit-cantidad-${tier.id}`}
              type="number"
              min="2"
              value={editForm.cantidad_minima}
              onChange={(e) => setEditForm((f) => ({ ...f, cantidad_minima: e.target.value }))}
              required
            />
            <label htmlFor={`pxq-edit-precio-${tier.id}`}>Precio unitario</label>
            <input
              id={`pxq-edit-precio-${tier.id}`}
              type="number"
              min="0"
              step="0.01"
              value={editForm.precio_unitario}
              onChange={(e) => setEditForm((f) => ({ ...f, precio_unitario: e.target.value }))}
              required
            />
            <label htmlFor={`pxq-edit-envio-${tier.id}`}>Costo de envío del bulto</label>
            <input
              id={`pxq-edit-envio-${tier.id}`}
              type="number"
              min="0"
              step="0.01"
              value={editForm.costo_envio_total}
              onChange={(e) => setEditForm((f) => ({ ...f, costo_envio_total: e.target.value }))}
            />
            <button type="submit" className="btn-tesla sm" disabled={saving}>
              Guardar
            </button>
            <button type="button" className="btn-tesla ghost sm" onClick={cancelEdit} disabled={saving}>
              Cancelar
            </button>
            {editError && <span className={styles.feedbackError}>{editError}</span>}
          </form>
        ) : (
          <div key={tier.id} className={styles.pxqTierEditRow}>
            <span>{tier.cantidad_minima} u.</span>
            <span>{formatMoney(tier.precio_unitario)}</span>
            <span>{isIncomplete(tier) ? formatMoney(null) : formatMoney(tier.costo_envio_total)}</span>
            {isIncomplete(tier) && (
              <span className={styles.pxqIncompleteBadge}>Incompleto: falta el costo de envío del bulto</span>
            )}
            <button type="button" className="btn-tesla ghost sm" onClick={() => startEdit(tier)}>
              Editar
            </button>
            {deletingId === tier.id ? (
              <span className={styles.applyConfirm}>
                ¿Eliminar este tramo?
                <button type="button" className="btn-tesla sm" onClick={() => handleConfirmDelete(tier.id)}>
                  Confirmar
                </button>
                <button type="button" className="btn-tesla ghost sm" onClick={() => setDeletingId(null)}>
                  Cancelar
                </button>
              </span>
            ) : (
              <button type="button" className={`btn-tesla ghost sm ${styles.removeBtn}`} onClick={() => setDeletingId(tier.id)}>
                Eliminar
              </button>
            )}
            {deleteError && deletingId === null && <span className={styles.feedbackError}>{deleteError}</span>}
          </div>
        ),
      )}

      {editingId === null && (
        <form className={styles.pxqTierEditRow} onSubmit={handleCreate}>
          <label htmlFor="pxq-new-cantidad">Cantidad mínima</label>
          <input
            id="pxq-new-cantidad"
            type="number"
            min="2"
            value={createForm.cantidad_minima}
            onChange={(e) => setCreateForm((f) => ({ ...f, cantidad_minima: e.target.value }))}
            required
          />
          <label htmlFor="pxq-new-precio">Precio unitario</label>
          <input
            id="pxq-new-precio"
            type="number"
            min="0"
            step="0.01"
            value={createForm.precio_unitario}
            onChange={(e) => setCreateForm((f) => ({ ...f, precio_unitario: e.target.value }))}
            required
          />
          <label htmlFor="pxq-new-envio">Costo de envío del bulto</label>
          <input
            id="pxq-new-envio"
            type="number"
            min="0"
            step="0.01"
            value={createForm.costo_envio_total}
            onChange={(e) => setCreateForm((f) => ({ ...f, costo_envio_total: e.target.value }))}
          />
          <button type="submit" className="btn-tesla primary sm" disabled={creating || atMax}>
            Agregar tramo
          </button>
          {atMax && <span className={styles.pxqUnavailable}>Máximo de 5 tramos alcanzado.</span>}
          {createError && <span className={styles.feedbackError}>{createError}</span>}
        </form>
      )}
    </div>
  );
}

// Every distinct backend `status` gets its own Spanish message: collapsing
// these throws away exactly what the backend's review rounds fought to keep
// separate (see module docstring below and `backend/app/routers/pxq.py`'s
// `_SYNC_STATUS_TO_HTTP`). `httpStatus` alone is not enough to disambiguate
// the two 503s or the two 502s, so `status` (from the error detail payload)
// drives the message, not the HTTP code.
function syncOutcomeMessage(httpStatus, detail) {
  const backendStatus = detail && typeof detail === 'object' ? detail.status : undefined;
  if (httpStatus === 403) {
    return { kind: 'error', text: 'No tenés permiso para sincronizar con MercadoLibre.' };
  }
  switch (backendStatus) {
    case 'disabled':
      return {
        kind: 'error',
        text: 'La sincronización con MercadoLibre está deshabilitada temporalmente (función apagada, no un problema de permisos).',
      };
    case 'rejected_not_eligible':
      return {
        kind: 'error',
        text: 'Esta publicación o la cuenta no está habilitada para precios mayoristas en MercadoLibre. Esto es permanente, no un problema temporal.',
      };
    case 'rejected_eligibility_unknown':
      return {
        kind: 'warn',
        text: 'No se pudo confirmar si esta publicación está habilitada para precios mayoristas. Podés reintentar en unos minutos.',
      };
    case 'rejected_read_unavailable':
      return {
        kind: 'warn',
        text: 'No se pudo leer el estado actual en MercadoLibre, así que no se escribió nada. Podés reintentar.',
      };
    case 'rejected_by_proxy':
      return {
        kind: 'error',
        text: `MercadoLibre rechazó el envío${detail?.reason ? `: ${detail.reason}` : '.'}`,
      };
    case 'submitted_unconfirmed':
    case 'ambiguous_needs_reconcile':
      return {
        kind: 'warn',
        text: 'No se pudo confirmar el resultado de la sincronización: MercadoLibre puede o no haber aplicado el cambio. Volvé a leer el estado en vivo antes de reintentar.',
      };
    default:
      return { kind: 'error', text: 'No se pudo sincronizar con MercadoLibre.' };
  }
}

// An empty local mirror is NOT an instruction to delete anything on ML. Three
// different facts produce an empty mirror and they stay distinct here for the
// same reason `live_tiers: null` never collapses into `[]` in the read columns
// above: "ML holds tiers we never mirrored" is a different problem from "both
// sides are genuinely empty" and from "the live read failed". Importing live
// tiers into the mirror (`adopt-live`, design.md D4) does not exist yet, so
// the first case has to say so out loud — otherwise the user reaches for
// deletion as a workaround, which is exactly how live tiers were lost.
function emptyMirrorRefusal(liveTiers, liveUnavailable) {
  if (liveUnavailable) {
    return {
      kind: 'warn',
      text: 'No se pudo leer el estado en vivo de MercadoLibre, así que no se va a tocar nada. Se puede reintentar en unos minutos.',
    };
  }
  if (liveTiers && liveTiers.length > 0) {
    return {
      kind: 'error',
      text: 'MercadoLibre tiene tramos mayoristas que no están en el mirror local. La sincronización no los va a modificar, e importarlos al mirror local todavía no está disponible.',
    };
  }
  return {
    kind: 'ok',
    text: 'No hay nada para sincronizar: ni el mirror local ni MercadoLibre tienen tramos mayoristas.',
  };
}

/**
 * Sync action + full outcome handling (PR 4d). Every non-200 `status` the
 * backend can return gets rendered distinctly — see `syncOutcomeMessage` —
 * plus a dedicated divergence banner (409).
 *
 * This control pushes the local mirror to ML and can never clear the live
 * array: with an empty mirror it refuses and explains why (see
 * `emptyMirrorRefusal`) instead of offering a wipe. It therefore needs the
 * live state, not just the mirror — deciding on the mirror alone is what made
 * "sincronizar" delete live tiers.
 */
function PxqSyncControl({ itemId, hasTiers, liveTiers, liveUnavailable, onSynced }) {
  const [syncing, setSyncing] = useState(false);
  const [feedback, setFeedback] = useState(null); // { kind: 'ok'|'warn'|'error', text }
  const [divergences, setDivergences] = useState(null);

  async function runSync() {
    setSyncing(true);
    setFeedback(null);
    setDivergences(null);
    try {
      await pxqAPI.sync(itemId);
      setFeedback({ kind: 'ok', text: 'Sincronizado con MercadoLibre.' });
      await onSynced();
    } catch (err) {
      const httpStatus = err?.response?.status;
      const detail = err?.response?.data?.detail;
      if (httpStatus === 409 && detail && typeof detail === 'object' && Array.isArray(detail.divergences)) {
        setDivergences(detail.divergences);
        setFeedback({
          kind: 'error',
          text: 'MercadoLibre y el mirror local no coinciden. Resolvé las diferencias editando los tramos y volvé a sincronizar.',
        });
      } else {
        setFeedback(syncOutcomeMessage(httpStatus, detail));
      }
    } finally {
      setSyncing(false);
    }
  }

  function handleSyncClick() {
    if (!hasTiers) {
      setDivergences(null);
      setFeedback(emptyMirrorRefusal(liveTiers, liveUnavailable));
      return;
    }
    runSync();
  }

  const feedbackClass =
    feedback?.kind === 'ok' ? styles.feedbackSuccess : feedback?.kind === 'warn' ? styles.feedbackWarn : styles.feedbackError;

  return (
    <div className={styles.pxqAuthoring}>
      <button type="button" className="btn-tesla primary sm" disabled={syncing} onClick={handleSyncClick}>
        Sincronizar con MercadoLibre
      </button>
      {feedback && <div className={feedbackClass}>{feedback.text}</div>}
      {divergences && (
        <div className={styles.pxqDivergenceBanner}>
          <div className={styles.pxqColumnTitle}>Diferencias que impiden la sincronización</div>
          {divergences.map((d, idx) => (
            <div key={d.ml_price_id ?? idx} className={styles.pxqDivergenceItem}>
              <span>{d.reason}</span>
              <span>En ML: {JSON.stringify(d.live)}</span>
              <span>Deseado: {JSON.stringify(d.desired)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Money is Decimal on the backend and arrives as a number or string here —
// this only formats it for display, it never computes or re-derives a
// markup (product decision carried over from CatalogCompetitionPanel).
function formatMoney(value) {
  if (value === null || value === undefined) return 'N/A';
  return `$${Number(value).toLocaleString('es-AR')}`;
}

/**
 * PxQ (wholesale, price-by-quantity) panel.
 *
 * Reads `GET /pxq/{item_id}/live` on open and shows live MercadoLibre state
 * side by side with the local mirror. This is the requirement that drove the
 * whole feature's design: "no me gusta que nada suceda en silencio" — live
 * state is shown ALWAYS, not only on divergence, and it renders ABOVE the
 * tier authoring form (PR 4c).
 *
 * `live_tiers: null` (the read failed/is unavailable) and `live_tiers: []`
 * (ML confirmed there genuinely are none) are DIFFERENT claims and must never
 * collapse into the same "0 tramos" rendering — see `live_status` handling
 * below and `backend/app/routers/pxq.py`'s `_unavailable_response` docstring.
 *
 * Divergences on this read-side comparison are marked purely as information;
 * nothing here resolves them. The sync action itself (`PxqSyncControl`, PR
 * 4d) lives below the authoring form and owns the 409 divergence-resolution
 * banner. It receives the live state too, because "the mirror is empty" alone
 * cannot tell a safe no-op apart from a publication whose live tiers were
 * never imported.
 */
function PxqPanel({ itemId, pxqCacheRef }) {
  const { tienePermiso } = usePermisos();
  const canRead = tienePermiso('pxq.ver');
  const canWrite = tienePermiso('pxq.escribir');

  // Gated inside the fetcher itself, not just the render: `useLazyResource`
  // fires its effect unconditionally on mount, so a plain early return after
  // the hook call would still let the fetch race the permission check.
  const fetcher = (id) => (canRead ? pxqAPI.getLive(id).then((r) => r.data) : Promise.resolve(null));
  const { data, loading, error, reload } = useLazyResource(pxqCacheRef, itemId, fetcher);

  // Invisible rather than an error/403 for a user without the permission —
  // same treatment PromoApplyControl/refresh buttons use elsewhere in this
  // tree: showing a control that only 403s helps no one.
  if (!canRead) {
    return null;
  }

  if (loading) {
    return <div className={styles.panelState}>Cargando precios mayoristas...</div>;
  }

  if (error) {
    return (
      <div className={styles.panelStateError}>
        Error al cargar precios mayoristas.{' '}
        <button type="button" className="btn-tesla ghost sm" onClick={reload}>
          Reintentar
        </button>
      </div>
    );
  }

  const liveTiers = data?.live_tiers ?? null;
  const mirrorTiers = data?.mirror_tiers || [];
  const liveUnavailable = data?.live_status === 'unavailable' || liveTiers === null;

  // Divergence is informational only here (PR 4b owns resolution): a mirror
  // tier with a synced `ml_price_id` that either has no matching live id, or
  // whose live quantity/amount differs from the mirror, is marked divergent.
  const liveById = new Map((liveTiers || []).map((tier) => [tier.id, tier]));
  function isDivergent(mirrorTier) {
    if (!mirrorTier.ml_price_id || liveUnavailable) return false;
    const liveTier = liveById.get(mirrorTier.ml_price_id);
    if (!liveTier) return true;
    return liveTier.quantity !== mirrorTier.cantidad_minima || Number(liveTier.amount) !== Number(mirrorTier.precio_unitario);
  }

  return (
    <div>
      <div className={styles.pxqColumns}>
        <div className={styles.pxqColumn}>
          <div className={styles.pxqColumnTitle}>En MercadoLibre (en vivo)</div>
          {liveUnavailable ? (
            <div className={styles.pxqUnavailable}>No se pudo leer el estado en vivo de MercadoLibre.</div>
          ) : liveTiers.length === 0 ? (
            <div className={styles.panelState}>ML no tiene tramos mayoristas para esta publicación.</div>
          ) : (
            liveTiers.map((tier) => (
              <div key={tier.id} className={styles.pxqTierRow}>
                <span>{tier.quantity} u.</span>
                <span>{formatMoney(tier.amount)}</span>
              </div>
            ))
          )}
        </div>
        <div className={styles.pxqColumn}>
          <div className={styles.pxqColumnTitle}>Mirror local</div>
          {mirrorTiers.length === 0 ? (
            <div className={styles.panelState}>Sin tramos mayoristas locales.</div>
          ) : (
            mirrorTiers.map((tier) => {
              const divergent = isDivergent(tier);
              return (
                <div
                  key={tier.id}
                  className={`${styles.pxqTierRow} ${divergent ? styles.pxqTierRowDivergent : ''}`}
                >
                  <span>{tier.cantidad_minima} u.</span>
                  <span>{formatMoney(tier.precio_unitario)}</span>
                  <span>{tier.estado}</span>
                  {divergent && <span>Diverge de ML</span>}
                </div>
              );
            })
          )}
        </div>
      </div>
      {canWrite && (
        <>
          <PxqTierAuthoring itemId={itemId} mirrorTiers={mirrorTiers} onChanged={reload} />
          <PxqSyncControl
            itemId={itemId}
            hasTiers={mirrorTiers.length > 0}
            liveTiers={liveTiers}
            liveUnavailable={liveUnavailable}
            onSynced={reload}
          />
        </>
      )}
    </div>
  );
}

export default PxqPanel;
