import { useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { pxqAPI } from '../../services/api';
import { useLazyResource } from '../../hooks/useLazyResource';
import { usePermisos } from '../../contexts/PermisosContext';
import styles from './promociones.module.css';

const MAX_TIERS = 5;

// `err.response.data.detail` reaches this file in ONE OF TWO SHAPES, and every
// reader below accepts both:
//   - a STRING, for every ordinary error — the response interceptor in
//     `services/api.js` flattens validation arrays and untyped dicts into one;
//   - the backend's TYPED error OBJECT, passed through untouched because it
//     carries fields a string cannot express (`status`, `conflicts`,
//     `divergences`).
// See `normalizeErrorDetail` in `services/api.js` for the predicate that tells
// them apart, and for the `http_exception_handler` quirk that puts the typed
// object at the ROOT of the response body instead of under `detail`. That
// interceptor used to flatten the typed shape too, which is why the
// `adopt_conflict` and `divergence` branches below shipped unreachable.
//
// The fallback is a PARAMETER, not a constant, because this helper is shared by
// three actions — create, edit and delete — and a single hardcoded sentence is
// guaranteed to name the wrong verb for two of them. The default keeps the
// create and edit wording verbatim, so only the caller that needs a different
// verb has to say so.
function extractErrorMessage(err, fallback = 'No se pudo guardar el tramo.') {
  const detail = err?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && typeof detail.reason === 'string') return detail.reason;
  return fallback;
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
  // Distinct from `deletingId` on purpose: `deletingId` answers "which row has
  // its confirmation open", `deleting` answers "is a DELETE outstanding". They
  // are cleared at different moments — see `handleConfirmDelete`.
  const [deleting, setDeleting] = useState(false);
  // `{ tierId, message }`, never a bare string: the error is rendered INSIDE
  // the row loop, so a component-wide string would paint the same failure on
  // every tier at once. Keyed by tier so only the row that actually failed
  // accuses itself.
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

  function startDelete(tierId) {
    setDeletingId(tierId);
    // Opening another row's confirmation retires the previous row's failure:
    // otherwise tier 1 keeps accusing itself while the operator is already
    // looking at tier 2.
    setDeleteError(null);
  }

  function cancelDelete() {
    setDeletingId(null);
    setDeleteError(null);
  }

  async function handleConfirmDelete(tierId) {
    setDeleting(true);
    setDeleteError(null);
    try {
      await pxqAPI.deleteTier(itemId, tierId);
      // Cleared ONLY on success, and deliberately NOT in the `finally` below: a
      // failed delete has to leave the confirmation standing so the retry and
      // the cancel stay one click away, with the reason still on screen.
      // Closing it on failure would send the operator hunting for the row again
      // — and this is the one authoring action whose failure path never
      // reloads, so the inline message is the only feedback there is.
      setDeletingId(null);
      await onChanged();
    } catch (err) {
      setDeleteError({ tierId, message: extractErrorMessage(err, 'No se pudo eliminar el tramo.') });
    } finally {
      // The in-flight flag, unlike `deletingId`, IS cleared unconditionally:
      // leaving it set after a failure would disable the retry button the
      // still-open confirmation exists to offer.
      setDeleting(false);
    }
  }

  return (
    <div className={styles.pxqAuthoring}>
      <div className={styles.pxqColumnTitle}>Editar tramos</div>
      {mirrorTiers.map((tier) =>
        editingId === tier.id ? (
          <form
            key={tier.id}
            className={styles.pxqTierForm}
            onSubmit={(event) => {
              event.preventDefault();
              handleSaveEdit(tier.id);
            }}
          >
            <div className={styles.pxqField}>
              <label className={styles.pxqFieldLabel} htmlFor={`pxq-edit-cantidad-${tier.id}`}>
                Cantidad mínima
              </label>
              <input
                id={`pxq-edit-cantidad-${tier.id}`}
                className={styles.pxqInput}
                type="number"
                min="2"
                value={editForm.cantidad_minima}
                onChange={(e) => setEditForm((f) => ({ ...f, cantidad_minima: e.target.value }))}
                required
              />
            </div>
            <div className={styles.pxqField}>
              <label className={styles.pxqFieldLabel} htmlFor={`pxq-edit-precio-${tier.id}`}>
                Precio unitario
              </label>
              <input
                id={`pxq-edit-precio-${tier.id}`}
                className={styles.pxqInput}
                type="number"
                min="0"
                step="0.01"
                value={editForm.precio_unitario}
                onChange={(e) => setEditForm((f) => ({ ...f, precio_unitario: e.target.value }))}
                required
              />
            </div>
            <div className={styles.pxqField}>
              <label className={styles.pxqFieldLabel} htmlFor={`pxq-edit-envio-${tier.id}`}>
                Costo de envío del bulto
              </label>
              <input
                id={`pxq-edit-envio-${tier.id}`}
                className={styles.pxqInput}
                type="number"
                min="0"
                step="0.01"
                value={editForm.costo_envio_total}
                onChange={(e) => setEditForm((f) => ({ ...f, costo_envio_total: e.target.value }))}
              />
            </div>
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
                <button type="button" className="btn-tesla sm" onClick={() => handleConfirmDelete(tier.id)} disabled={deleting}>
                  Confirmar
                </button>
                <button type="button" className="btn-tesla ghost sm" onClick={cancelDelete} disabled={deleting}>
                  Cancelar
                </button>
              </span>
            ) : (
              <button type="button" className={`btn-tesla ghost sm ${styles.removeBtn}`} onClick={() => startDelete(tier.id)}>
                Eliminar
              </button>
            )}
            {deleteError?.tierId === tier.id && <span className={styles.feedbackError}>{deleteError.message}</span>}
          </div>
        ),
      )}

      {editingId === null && (
        <form className={styles.pxqTierForm} onSubmit={handleCreate}>
          <div className={styles.pxqField}>
            <label className={styles.pxqFieldLabel} htmlFor="pxq-new-cantidad">
              Cantidad mínima
            </label>
            <input
              id="pxq-new-cantidad"
              className={styles.pxqInput}
              type="number"
              min="2"
              value={createForm.cantidad_minima}
              onChange={(e) => setCreateForm((f) => ({ ...f, cantidad_minima: e.target.value }))}
              required
            />
          </div>
          <div className={styles.pxqField}>
            <label className={styles.pxqFieldLabel} htmlFor="pxq-new-precio">
              Precio unitario
            </label>
            <input
              id="pxq-new-precio"
              className={styles.pxqInput}
              type="number"
              min="0"
              step="0.01"
              value={createForm.precio_unitario}
              onChange={(e) => setCreateForm((f) => ({ ...f, precio_unitario: e.target.value }))}
              required
            />
          </div>
          <div className={styles.pxqField}>
            <label className={styles.pxqFieldLabel} htmlFor="pxq-new-envio">
              Costo de envío del bulto
            </label>
            <input
              id="pxq-new-envio"
              className={styles.pxqInput}
              type="number"
              min="0"
              step="0.01"
              value={createForm.costo_envio_total}
              onChange={(e) => setCreateForm((f) => ({ ...f, costo_envio_total: e.target.value }))}
            />
          </div>
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
    return { kind: 'error', text: 'No tenés permiso para actualizar precios en MercadoLibre.' };
  }
  switch (backendStatus) {
    case 'disabled':
      return {
        kind: 'error',
        text: 'La actualización de precios en MercadoLibre está deshabilitada temporalmente (función apagada, no un problema de permisos).',
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
        text: 'No se pudo confirmar el resultado de la actualización: MercadoLibre puede o no haber aplicado los precios nuevos. Volvé a leer el estado en vivo antes de reintentar.',
      };
    default:
      return { kind: 'error', text: 'No se pudieron actualizar los precios en MercadoLibre.' };
  }
}

// An empty local mirror is NOT an instruction to delete anything on ML. Three
// different facts produce an empty mirror and they stay distinct here for the
// same reason `live_tiers: null` never collapses into `[]` in the read columns
// above: "ML holds tiers we never mirrored" is a different problem from "both
// sides are genuinely empty" and from "the live read failed".
//
// The first case used to end with "importarlos al mirror local todavía no está
// disponible", which was true and is now false: `PxqAdoptControl` below imports
// them, and it renders in exactly this state. A refusal that still describes
// the missing capability would send the user back to deletion as a workaround,
// which is how live tiers were lost in the first place — so it points at the
// control instead.
//
// Register: this panel addresses the operator in voseo throughout ("No tenés
// permiso", "Resolvé las diferencias"). The both-empty branch is left alone
// because it has no second-person verb to conjugate at all — it states a fact
// about two systems and asks the reader for nothing.
function emptyMirrorRefusal(liveTiers, liveUnavailable) {
  if (liveUnavailable) {
    return {
      kind: 'warn',
      text: 'No se pudo leer el estado en vivo de MercadoLibre, así que no se va a tocar nada. Podés reintentar en unos minutos.',
    };
  }
  if (liveTiers && liveTiers.length > 0) {
    // `warn`, not `error`: nothing failed and there is an action to take. The
    // red tone belonged to the version of this message that had none.
    return {
      kind: 'warn',
      text: 'MercadoLibre tiene tramos mayoristas que no están en el mirror local. Actualizar precios no los trae acá: si los querés en el mirror, importalos con "Importar de MercadoLibre", acá arriba.',
    };
  }
  return {
    kind: 'ok',
    text: 'No hay precios para actualizar: ni el mirror local ni MercadoLibre tienen tramos mayoristas.',
  };
}

/**
 * Price-update action + full outcome handling (PR 4d). Every non-200 `status`
 * the backend can return gets rendered distinctly — see `syncOutcomeMessage` —
 * plus a dedicated divergence banner (409).
 *
 * This control pushes the local mirror to ML and can never clear the live
 * array: with an empty mirror it refuses and explains why (see
 * `emptyMirrorRefusal`) instead of offering a wipe. It therefore needs the
 * live state, not just the mirror — deciding on the mirror alone is what let
 * this action delete live tiers back when it was still labelled "sincronizar".
 *
 * That label is gone from the UI on purpose. The write is one-way, local -> ML;
 * "sincronizar" promised reconciliation, so the operator believed he was
 * looking when he was in fact writing. The button now names the write:
 * "Actualizar precios en MercadoLibre". The identifiers below still say `sync`
 * because they track the backend endpoint, which is unchanged.
 *
 * `feedback` and `divergences` are CONTROLLED by the panel, same shape and same
 * reason as `PxqAdoptControl`: the success path calls `onSynced()` ->
 * `useLazyResource.reload()`, which sets `loading`, so `PxqPanel` returns its
 * loading branch and unmounts this subtree. Held locally, the success message
 * was destroyed by the very refresh that proved it true and was never once
 * visible; only the failure paths, which do not reload, ever painted.
 *
 * BOTH are lifted, not just the message. They are one result: a banner left
 * behind by a remount would leave "Resolvé las diferencias" on screen with no
 * differences under it to resolve.
 *
 * `syncing` stays local on purpose — it is this button's in-flight state, not
 * an outcome, and it has nothing to survive.
 */
function PxqSyncControl({ itemId, hasTiers, liveTiers, liveUnavailable, feedback, onFeedback, divergences, onDivergences, onSynced }) {
  const [syncing, setSyncing] = useState(false);

  async function runSync() {
    setSyncing(true);
    onFeedback(null);
    onDivergences(null);
    try {
      await pxqAPI.sync(itemId);
      onFeedback({ kind: 'ok', text: 'Precios actualizados en MercadoLibre.' });
      await onSynced();
    } catch (err) {
      const httpStatus = err?.response?.status;
      const detail = err?.response?.data?.detail;
      if (httpStatus === 409 && detail && typeof detail === 'object' && Array.isArray(detail.divergences)) {
        onDivergences(detail.divergences);
        onFeedback({
          kind: 'error',
          text: 'MercadoLibre y el mirror local no coinciden. Resolvé las diferencias editando los tramos y volvé a actualizar los precios.',
        });
      } else {
        onFeedback(syncOutcomeMessage(httpStatus, detail));
      }
    } finally {
      setSyncing(false);
    }
  }

  function handleSyncClick() {
    if (!hasTiers) {
      onDivergences(null);
      onFeedback(emptyMirrorRefusal(liveTiers, liveUnavailable));
      return;
    }
    runSync();
  }

  const feedbackClass =
    feedback?.kind === 'ok' ? styles.feedbackSuccess : feedback?.kind === 'warn' ? styles.feedbackWarn : styles.feedbackError;

  return (
    <div className={styles.pxqAuthoring}>
      <button type="button" className="btn-tesla primary sm" disabled={syncing} onClick={handleSyncClick}>
        Actualizar precios en MercadoLibre
      </button>
      {feedback && <div className={feedbackClass}>{feedback.text}</div>}
      {divergences && (
        <div className={styles.pxqDivergenceBanner}>
          <div className={styles.pxqColumnTitle}>Diferencias que impiden actualizar los precios</div>
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

// The 409 payload carries the conflicting rows precisely so the operator does
// not have to hunt for them. Rendering a bare "hay conflictos" would throw away
// the one thing that makes the refusal actionable. Quantity first because that
// is what the mirror column shows on screen; id second because that is what
// tells two otherwise identical-looking rows apart.
function formatAdoptConflicts(conflicts) {
  if (!Array.isArray(conflicts) || conflicts.length === 0) return 'los tramos locales que ya existen';
  return conflicts.map((c) => `${c.cantidad_minima} u. (id ${c.tier_id})`).join(', ');
}

// Same discipline as `syncOutcomeMessage`: the backend `status` in the detail
// payload drives the message, not the bare HTTP code. Every branch ends with
// something the operator can actually do next.
function adoptOutcomeMessage(httpStatus, detail) {
  const backendStatus = detail && typeof detail === 'object' ? detail.status : undefined;
  if (httpStatus === 403) {
    return { kind: 'error', text: 'No tenés permiso para importar tramos desde MercadoLibre.' };
  }
  if (httpStatus === 404) {
    return {
      kind: 'error',
      text: 'No se encontró esta publicación, así que no se importó nada. Actualizá la vista y volvé a intentar.',
    };
  }
  if (backendStatus === 'adopt_conflict') {
    return {
      kind: 'error',
      text:
        `El mirror local ya tiene tramos, así que no se importó nada. Para importar, eliminá primero ${formatAdoptConflicts(detail.conflicts)}. ` +
        'Tené en cuenta que entre el borrado y la importación el mirror queda vacío: si justo ahí falla la lectura de MercadoLibre, vas a tener que reintentar. ' +
        'Los tramos que están en vivo en MercadoLibre no se tocan en ningún caso.',
    };
  }
  if (backendStatus === 'adopt_read_unavailable') {
    // Both 503 sub-cases land here deliberately. The second one — a live read
    // carrying MORE tiers than MercadoLibre's own platform limit of 5 — means
    // our view of ML is untrustworthy, NOT that the operator has anything to
    // go and fix; the backend refuses it as an unreadable read for that exact
    // reason. Splitting the copy would invent an action that does not exist.
    return {
      kind: 'warn',
      text: 'No se pudo leer el estado en vivo de MercadoLibre, así que no se importó nada. Podés reintentar en unos minutos.',
    };
  }
  return { kind: 'error', text: 'No se pudieron importar los tramos desde MercadoLibre.' };
}

// The backend skips `cantidad_minima < 1`, and this sentence has to state THAT
// rule. It used to say "menos de 2 unidades": the mirror refused a one-unit
// tier back then. It does not any more — a price with `min_purchase_unit: 1` is
// what makes the publication show up as "Venta para negocios" on MercadoLibre,
// so it is imported like any other tier now. Leaving the old wording here would
// have kept explaining a gap with a rule the backend no longer applies.
//
// This sentence is what accounts for the gap the operator can SEE: the live
// column renders every entry MercadoLibre reports, including the skipped one,
// and the mirror column next to it will never grow a row to match. Without
// this, a successful import leaves two columns that disagree by a row and
// nothing on screen saying why.
//
// It always ends with "sigue vivo en MercadoLibre" because the reflex on a
// money path is to read "no se importó" as "se perdió". It did not: `pxq_diff`
// re-emits every live tier no local row references as an untracked keep, so the
// skipped price is left exactly as it is.
//
// The reason is still stated as the RULE, not as a quantity read off the
// payload — the response carries `cantidad_minima` per skipped entry, but the
// copy is built from `skipped_count` alone and must not imply a number it was
// not given.
function skippedAdoptSentence(skippedCount) {
  return skippedCount === 1
    ? 'Hay 1 precio en MercadoLibre que no se importó porque la cantidad que informa no llega a 1 unidad, y este panel solo maneja tramos desde 1. Sigue vivo en MercadoLibre: no se borra ni se toca.'
    : `Hay ${skippedCount} precios en MercadoLibre que no se importaron porque la cantidad que informan no llega a 1 unidad, y este panel solo maneja tramos desde 1. Siguen vivos en MercadoLibre: no se borran ni se tocan.`;
}

/**
 * Import action (PR 4e): pulls MercadoLibre's live tiers DOWN into an empty
 * local mirror. `POST /pxq/{item_id}/adopt-live` writes only local rows and
 * calls no ML write endpoint on any path.
 *
 * Its own component, not a branch inside `PxqSyncControl`: that one already
 * carries a dozen sync outcomes plus the divergence banner, and these two verbs
 * point in opposite directions — one pushes to ML, this one only ever reads it.
 *
 * Labelled "Importar de MercadoLibre", never "sincronizar" — a word this panel
 * no longer uses for either direction, because it promised reconciliation and
 * delivered a one-way write. The push control names its own direction too now
 * ("Actualizar precios en MercadoLibre"); the principle is the same one the
 * comment above `pxqAPI.sync` states for the destructive argument: a control is
 * named for what it does.
 *
 * What this does NOT do: recover a publication whose live tiers were already
 * deleted on ML. There is nothing there to import. What it repairs is the
 * publication that still HAS live tiers against an empty mirror — a state whose
 * only offered action used to be a push that could merely destroy them.
 *
 * `feedback` is CONTROLLED by the panel rather than held here, and that is not
 * a style preference. A successful import makes the mirror non-empty, and the
 * refresh that reveals it goes through `useLazyResource.reload()`, which sets
 * `loading` — so `PxqPanel` returns its loading branch and this whole subtree
 * unmounts. Local state would take the outcome with it, and the operator would
 * never read the count or the "still needs a shipping cost" next step: the one
 * message this control exists to deliver. (`PxqSyncControl` had the same shape
 * and therefore the same hole in its success message; it is controlled by the
 * panel now for exactly this reason.)
 */
function PxqAdoptControl({ itemId, canImport, feedback, onFeedback, onAdopted }) {
  const [adopting, setAdopting] = useState(false);

  async function handleAdoptClick() {
    setAdopting(true);
    onFeedback(null);
    try {
      const { data } = await pxqAPI.adoptLive(itemId);
      const count = data?.count ?? 0;
      const skippedCount = data?.skipped_count ?? 0;
      if (count === 0 && skippedCount > 0) {
        // Its OWN branch, ahead of the one below, because that one would LIE
        // here: MercadoLibre does have prices on this publication — none of
        // them is a tier this panel can hold. Routing both through "ML ya no
        // tiene tramos" would tell the operator the listing is empty when it
        // is not, and nothing else on screen would contradict it.
        onFeedback({
          kind: 'warn',
          text: `No se importó nada. ${skippedAdoptSentence(skippedCount)}`,
        });
      } else if (count === 0) {
        // Reachable, not defensive: the mount condition reads the live state
        // fetched when the panel opened, and ML can lose its tiers between then
        // and this click. The backend answers that with 200 + count 0. Claiming
        // "se importaron 0 tramos" and then naming a next step would describe
        // work that did not happen.
        onFeedback({
          kind: 'warn',
          text: 'MercadoLibre ya no tiene tramos mayoristas para importar, así que no se importó nada.',
        });
      } else {
        // The count AND the next step, together. Imported rows land with
        // `costo_envio_total` NULL and `estado` reading `incompleto`; write
        // eligibility is decided by the cost alone (`pxq_confirm.is_priceable`)
        // and nothing in the backend ever writes `ESTADO_LISTO`. A tier that
        // silently cannot be written back to ML is a trap, so the copy says so.
        //
        // The skip is APPENDED, never substituted: both facts are true at once
        // and each has its own consequence — the shipping cost has to be loaded
        // on the rows that landed, and the operator has to know MercadoLibre
        // holds something this panel will never show him.
        onFeedback({
          kind: 'ok',
          text:
            `${count === 1 ? 'Se importó 1 tramo' : `Se importaron ${count} tramos`} desde MercadoLibre. ` +
            'Todavía no podés actualizar precios con ellos: cargá el costo de envío del bulto en cada uno.' +
            (skippedCount > 0 ? ` ${skippedAdoptSentence(skippedCount)}` : ''),
        });
      }
      await onAdopted();
    } catch (err) {
      onFeedback(adoptOutcomeMessage(err?.response?.status, err?.response?.data?.detail));
    } finally {
      setAdopting(false);
    }
  }

  const feedbackClass =
    feedback?.kind === 'ok' ? styles.feedbackSuccess : feedback?.kind === 'warn' ? styles.feedbackWarn : styles.feedbackError;

  return (
    <div className={styles.pxqAuthoring}>
      {/* The BUTTON is gated on the importable state; the MESSAGE outlives it.
          After a successful import the mirror is no longer empty, so offering
          the action again would be offering a guaranteed 409 — but the outcome
          it produced still has to be readable. */}
      {canImport && (
        <button type="button" className="btn-tesla primary sm" disabled={adopting} onClick={handleAdoptClick}>
          Importar de MercadoLibre
        </button>
      )}
      {feedback && <div className={feedbackClass}>{feedback.text}</div>}
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

// `estado` is a PERSISTED DOMAIN VALUE, not UI copy: the four members of
// `ESTADOS_VALIDOS` are pinned by the CHECK constraint
// `ck_ml_pxq_tier_estado_valido` (see `backend/app/models/ml_pxq_tier.py`). The
// panel PRESENTS it instead of echoing it. Rendering the bare enum put an
// untranslated lowercase identifier in front of the operator, and `sincronizado`
// was the LAST place the retired verb still reached him after the write button
// stopped calling itself a sync — a row claiming to be "sincronizado" re-tells
// the exact story ("both sides agree / it was reconciled") that cost four
// publications. Renaming the value itself would need a migration and buy him
// nothing, so the translation lives here.
//
// A `Map`, not an object literal: a bare `{}` resolves inherited keys, so an
// `estado` of "constructor" or "toString" would hand a FUNCTION to the fallback
// below and crash the render. `Map.get` only sees what was put in it.
const ESTADO_LABELS = new Map([
  ['incompleto', 'Incompleto'],
  ['listo', 'Listo'],
  ['sincronizado', 'Actualizado en MercadoLibre'],
  ['desconocido', 'Desconocido'],
]);

// Unmapped values fall through to the RAW value deliberately — never blank,
// never a throw. The backend can add a fifth `estado` before this map learns
// about it, and an empty cell would hide the tier's real state; an ugly one at
// least stays honest and is visibly wrong enough to get reported.
function formatEstado(estado) {
  return ESTADO_LABELS.get(estado) ?? estado;
}

// Neither read column arrives in a usable order, for two unrelated reasons.
//
// MercadoLibre returns the wholesale tiers ARBITRARILY ordered — measured in
// production for MLA1563835240 as quantities 5, 10, 2 — and the `ml-webhook`
// service preserves ML's order deliberately in both directions, having stated
// in writing that ordering is the CONSUMER's job. Nothing guarantees an order
// by `quantity`, and nothing guarantees one by `id` either.
//
// The local mirror had the same defect from the other end: the query behind
// `mirror_tiers` carried no `ORDER BY`, so the rows came back in whatever order
// storage produced. `backend/app/routers/pxq.py` now orders that query, and
// sorting here as well is NOT redundancy to delete later: the API is ordered so
// that every consumer gets a deterministic response, while the panel is ordered
// because it is the last thing standing between the data and the operator —
// including when the data comes off the `useLazyResource` cache.
//
// A tier is a QUANTITY THRESHOLD ("from 5 units, this price"), so the order is
// not decoration. Out of sequence the column stops being a scale and becomes
// three unrelated prices the reader has to sort in his head before he can
// answer the only question the panel exists for: does buying more get cheaper.
//
// COPIES before sorting, because `Array.prototype.sort` mutates in place. Both
// arrays come straight out of the fetch and live in the resource cache, and
// `mirror_tiers` has three readers: this column, `PxqTierAuthoring` (which
// gets its own sorted copy below) and the `canImportLive` computation (which
// reads the raw array). None of them depends on ORDER — two render a list, the
// third only reads `.length` — but sorting a shared array where it lies would
// still reorder it behind their backs, for good, on the first render.
function sortedByQuantity(tiers, quantityKey) {
  return [...tiers].sort((a, b) => a[quantityKey] - b[quantityKey]);
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

  // Held here, not inside `PxqAdoptControl`: a successful import calls
  // `reload()`, which flips `loading` and makes this component return its
  // loading branch — unmounting the control and every piece of state in it.
  // See the control's docstring. Declared above the early returns so the hook
  // order stays fixed whatever branch renders.
  const [adoptFeedback, setAdoptFeedback] = useState(null);

  // Same story for the price-update outcome, and for the divergence rows that
  // are part of that same outcome. See `PxqSyncControl`'s docstring.
  const [syncFeedback, setSyncFeedback] = useState(null);
  const [syncDivergences, setSyncDivergences] = useState(null);

  // Outliving the control is not the same as outliving the PUBLICATION. The
  // messages survive `reload()` deliberately (above); they must NOT survive a
  // change of `itemId`, because `useLazyResource` re-keys on the new id without
  // unmounting this component — so "Se importaron 2 tramos" would go on sitting
  // under a publication it never described, indefinitely.
  //
  // Reset during render, not in an effect: an effect runs after commit, so the
  // stale message would still paint once under the new item. Same thing the
  // operator would misread, one frame later.
  const [feedbackItemId, setFeedbackItemId] = useState(itemId);
  if (feedbackItemId !== itemId) {
    setFeedbackItemId(itemId);
    setAdoptFeedback(null);
    setSyncFeedback(null);
    setSyncDivergences(null);
  }

  // A feedback message describes the RESULT of an action taken against a state.
  // The moment the operator MUTATES that state, the message stops describing
  // what is on screen — so authoring a tier clears BOTH outcomes:
  //   - import: "cargá el costo de envío del bulto" is false as soon as he does;
  //   - price update: "Precios actualizados en MercadoLibre" is false as soon as
  //     he edits a tier, because the mirror is no longer what was sent.
  //
  // Tied to the AUTHORING callback, never to `reload()` itself. The reload the
  // import triggers, and the one the price update triggers, are precisely the
  // ones that must PRESERVE their message — that is the whole reason this state
  // lives up here. Clearing inside `reload()` would look like a simplification
  // and would silently restore the bug this file just fixed.
  async function handleAuthoringChanged() {
    setAdoptFeedback(null);
    setSyncFeedback(null);
    setSyncDivergences(null);
    await reload();
  }

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

  // Order matters in this conjunction, not just readability: `liveUnavailable`
  // is what guarantees `liveTiers` is non-null by the time it is dereferenced.
  const canImportLive = mirrorTiers.length === 0 && !liveUnavailable && liveTiers.length > 0;

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
      {/* Wired to `reload`, NOT to `handleAuthoringChanged`. Both reload, but
          that one also clears the import and price-update outcomes, and it is
          allowed to do so only because AUTHORING invalidates them — "cargá el
          costo de envío del bulto" stops being true the moment he loads it.
          Re-reading MercadoLibre invalidates nothing the operator did, so the
          messages have to survive it.

          No in-flight or disabled state: `reload()` sets `loading`, so the
          panel returns its loading branch and this button is unmounted with
          the rest of the subtree while the read is in flight. The loading
          screen is the feedback. Until now the only way to re-read ML was to
          close the panel and reopen it — "Reintentar" lives inside the error
          branch, which is the one path where the operator is NOT comparing
          the two columns. */}
      <div className={styles.pxqHeader}>
        <button
          type="button"
          className="btn-tesla outline-subtle-primary icon-only sm"
          onClick={reload}
          aria-label={`Refrescar precios mayoristas de ${itemId}`}
        >
          <RefreshCw size={14} />
        </button>
      </div>
      <div className={styles.pxqColumns}>
        <div className={styles.pxqColumn}>
          <div className={styles.pxqColumnTitle}>En MercadoLibre (en vivo)</div>
          {liveUnavailable ? (
            <div className={styles.pxqUnavailable}>No se pudo leer el estado en vivo de MercadoLibre.</div>
          ) : liveTiers.length === 0 ? (
            <div className={styles.panelState}>ML no tiene tramos mayoristas para esta publicación.</div>
          ) : (
            sortedByQuantity(liveTiers, 'quantity').map((tier) => (
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
            sortedByQuantity(mirrorTiers, 'cantidad_minima').map((tier) => {
              const divergent = isDivergent(tier);
              return (
                <div
                  key={tier.id}
                  className={`${styles.pxqTierRow} ${divergent ? styles.pxqTierRowDivergent : ''}`}
                >
                  <span>{tier.cantidad_minima} u.</span>
                  <span>{formatMoney(tier.precio_unitario)}</span>
                  <span>{formatEstado(tier.estado)}</span>
                  {divergent && <span>Diverge de ML</span>}
                </div>
              );
            })
          )}
        </div>
      </div>
      {canWrite && (
        <>
          {/* Sorted here too, not just in the read column above: the editing
              list renders the SAME rows directly underneath it, and two
              orderings of one list would make the operator map between them to
              find the row he wants. It does arrive ordered from the backend's
              `ORDER BY` today, but that is an implicit dependency on another
              service rather than a guarantee this panel holds. */}
          <PxqTierAuthoring
            itemId={itemId}
            mirrorTiers={sortedByQuantity(mirrorTiers, 'cantidad_minima')}
            onChanged={handleAuthoringChanged}
          />
          {/* The IMPORT ACTION is offered in exactly one state. An empty
              `liveTiers` means there is nothing on ML to import; a failed live
              read means we do not know what is there; a non-empty mirror means
              the backend would refuse with 409. A button in any of those three
              is a dead action the user only discovers by pressing it.
              The control is still mounted while an outcome is pending display,
              because the successful import that ends the importable state is
              also the one whose result most needs reading. */}
          {(canImportLive || adoptFeedback) && (
            <PxqAdoptControl
              itemId={itemId}
              canImport={canImportLive}
              feedback={adoptFeedback}
              onFeedback={setAdoptFeedback}
              onAdopted={reload}
            />
          )}
          <PxqSyncControl
            itemId={itemId}
            hasTiers={mirrorTiers.length > 0}
            liveTiers={liveTiers}
            liveUnavailable={liveUnavailable}
            feedback={syncFeedback}
            onFeedback={setSyncFeedback}
            divergences={syncDivergences}
            onDivergences={setSyncDivergences}
            onSynced={reload}
          />
        </>
      )}
    </div>
  );
}

export default PxqPanel;
