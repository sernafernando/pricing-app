import { useState } from 'react';
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
      setFeedback({ kind: 'ok', text: 'Precios actualizados en MercadoLibre.' });
      await onSynced();
    } catch (err) {
      const httpStatus = err?.response?.status;
      const detail = err?.response?.data?.detail;
      if (httpStatus === 409 && detail && typeof detail === 'object' && Array.isArray(detail.divergences)) {
        setDivergences(detail.divergences);
        setFeedback({
          kind: 'error',
          text: 'MercadoLibre y el mirror local no coinciden. Resolvé las diferencias editando los tramos y volvé a actualizar los precios.',
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
 * message this control exists to deliver. (`PxqSyncControl` has the same shape
 * and therefore the same hole in its success message; fixing that is a separate
 * change, not something to smuggle in here.)
 */
function PxqAdoptControl({ itemId, canImport, feedback, onFeedback, onAdopted }) {
  const [adopting, setAdopting] = useState(false);

  async function handleAdoptClick() {
    setAdopting(true);
    onFeedback(null);
    try {
      const { data } = await pxqAPI.adoptLive(itemId);
      const count = data?.count ?? 0;
      if (count === 0) {
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
        onFeedback({
          kind: 'ok',
          text:
            `${count === 1 ? 'Se importó 1 tramo' : `Se importaron ${count} tramos`} desde MercadoLibre. ` +
            'Todavía no podés actualizar precios con ellos: cargá el costo de envío del bulto en cada uno.',
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

  // Outliving the control is not the same as outliving the PUBLICATION. The
  // message survives `reload()` deliberately (above); it must NOT survive a
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
          <PxqTierAuthoring itemId={itemId} mirrorTiers={mirrorTiers} onChanged={reload} />
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
            onSynced={reload}
          />
        </>
      )}
    </div>
  );
}

export default PxqPanel;
