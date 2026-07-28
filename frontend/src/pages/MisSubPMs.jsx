import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { Save } from 'lucide-react';
import { marcasPmAPI } from '../services/api';
import { ModalAlert, ModalLoading } from '../components/ModalTesla';
import ParesTable from '../components/ParesTable';
import { parKey } from '../components/parKey';
import { clavesDesdePayload } from './misSubPMsHelpers';
import { useAuthStore } from '../store/authStore';
import { usePermisos } from '../contexts/PermisosContext';
import styles from './MisSubPMs.module.css';

/**
 * Builds the collision-proof set-arithmetic (Slice 3's T3.1, deferred here
 * since it is a container concern, not a presentational one): what a save
 * would grant/revoke, comparing the current `checked` Set against the
 * `baseline` Set loaded for the selected user. Both Sets hold `parKey`
 * values — never raw strings.
 */
function diffContraBaseline(checked, baseline) {
  const toGrant = [...checked].filter((key) => !baseline.has(key));
  const toRevoke = [...baseline].filter((key) => !checked.has(key));
  return { toGrant, toRevoke };
}

function esDirty(checked, baseline) {
  if (checked.size !== baseline.size) return true;
  for (const key of checked) {
    if (!baseline.has(key)) return true;
  }
  return false;
}

/**
 * Backend error detail helper (Slice 3's T3.3/T3.4, deferred here). The bulk
 * PUT's 403 sends `detail` as a DICT with `pares_rechazados` (marcas_pm.py
 * :775-781); every other error path on this page still sends `detail` as a
 * plain string. Both shapes must resolve to a real message — never blank.
 */
function extraerError(err, fallback) {
  const detail = err?.response?.data?.detail;
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const rechazados = Array.isArray(detail.pares_rechazados) ? detail.pares_rechazados : [];
    const mensaje = detail.mensaje || fallback;
    return { texto: mensaje, rechazados };
  }
  if (typeof detail === 'string' && detail) return { texto: detail, rechazados: [] };
  return { texto: fallback, rechazados: [] };
}

/**
 * MisSubPMs — user-first sub-PM bulk assignment container
 * (sub-pm-bulk-assignment Slice 4). Replaces the former pair-first flow
 * (seleccionarPar cycled nuevoUsuarioId per click, O(N) clicks to delegate
 * one user across N pairs) with: pick the target user, pre-check their
 * current grants, edit the full set, confirm a named diff, one PUT.
 *
 * Pair source stays split by contract, same as before: admin
 * (`admin.gestionar_pms`) -> GET /marcas-pm (`listarTodosLosPares`,
 * includes pairs with no titular); titular -> GET /marcas-pm/mis-titularidades
 * (`misTitularidades`, NEVER unioned with sub-PM data). `admin.gestionar_pms`
 * can be granted as a permiso override to a non-admin role, but GET
 * /marcas-pm is ROLE-gated (403) — fall back to titular scope ONLY on 403;
 * any other failure (500, network) surfaces as an error instead of
 * silently narrowing the pair list.
 */
export default function MisSubPMs() {
  const currentUserId = useAuthStore((s) => s.user?.id);
  const { tienePermiso } = usePermisos();
  const esAdmin = tienePermiso('admin.gestionar_pms');

  const [pares, setPares] = useState([]);
  const [loadingPares, setLoadingPares] = useState(true);

  const [usuarios, setUsuarios] = useState([]);
  const [conteos, setConteos] = useState({}); // usuario_id -> total
  const [conteosError, setConteosError] = useState(false); // counts failed to load; render "?" instead of a fake (0)

  // Normalized to Number|null at the boundary (the `<select>`'s onChange),
  // matching `usuario_id`'s type everywhere else — avoids scattering
  // `String(...)`/`Number(...)` coercions across every comparison and API
  // call (review finding #6).
  const [targetUserId, setTargetUserId] = useState(null);
  const [loadingGrants, setLoadingGrants] = useState(false);
  const [baseline, setBaseline] = useState(new Set());
  const [checked, setChecked] = useState(new Set());

  const [confirmando, setConfirmando] = useState(false);
  const [usuarioPendiente, setUsuarioPendiente] = useState(null); // usuarioId chosen while dirty, awaiting confirmation
  const [saving, setSaving] = useState(false);

  const [alerta, setAlerta] = useState(null); // { tipo, texto }
  const [rechazados, setRechazados] = useState([]);

  const showError = useCallback((err, fallback) => {
    const { texto, rechazados: pares_rechazados } = extraerError(err, fallback);
    const sufijo = pares_rechazados.length ? ' No se aplicó ningún cambio.' : '';
    setAlerta({ tipo: 'error', texto: `${texto}${sufijo}` });
    setRechazados(pares_rechazados);
  }, []);
  const showSuccess = useCallback((texto) => {
    setAlerta({ tipo: 'success', texto });
    setRechazados([]);
  }, []);

  const cargarPares = useCallback(async () => {
    setLoadingPares(true);
    try {
      let nuevosPares;
      if (esAdmin) {
        try {
          const { data } = await marcasPmAPI.listarTodosLosPares();
          nuevosPares = Array.isArray(data) ? data : [];
        } catch (err) {
          if (err?.response?.status !== 403) throw err;
          const { data } = await marcasPmAPI.misTitularidades();
          nuevosPares = Array.isArray(data?.pares) ? data.pares : [];
        }
      } else {
        const { data } = await marcasPmAPI.misTitularidades();
        nuevosPares = Array.isArray(data?.pares) ? data.pares : [];
      }
      setPares(nuevosPares);
    } catch (err) {
      console.error('Error al cargar pares marca/categoría', err);
      setPares([]);
      showError(err, esAdmin ? 'Error al cargar las marcas/categorías' : 'Error al cargar tus marcas/categorías');
    } finally {
      setLoadingPares(false);
    }
  }, [showError, esAdmin]);

  useEffect(() => {
    cargarPares();
  }, [cargarPares]);

  // Two independent calls with independent failure handling (review finding
  // #3): a counts failure must NOT empty the user picker — the picker is
  // still fully usable without counts, it just can't show them. And a real
  // zero grants (the everyday case: production launches with none) must
  // render differently from "counts never loaded", or the screen looks
  // broken/empty when it's actually just quiet.
  //
  // The two failures also must not compete for the single shared `alerta`
  // banner (review finding #4): a users-list failure is BLOCKING (the whole
  // picker goes empty) and must always be visible; a counts failure is
  // COSMETIC (`?` instead of a number) and gets its own small inline notice
  // next to the picker instead, so it can never mask the blocking one.
  //
  // Security invariant (restored — do NOT drop this again): the global PM
  // user list is potentially sensitive, so it must only be fetched once we
  // KNOW the caller has at least one pair in their writable scope (admin or
  // titular). Someone who navigates here holding zero pairs must never
  // trigger `GET /usuarios/pms` — the picker instead stays disabled with an
  // honest "no pairs in scope" message (see `hayParesEnScope` below). The
  // counts call is gated identically: there is nothing to count for.
  const hayParesEnScope = !loadingPares && pares.length > 0;

  useEffect(() => {
    if (!hayParesEnScope) return;
    (async () => {
      try {
        const { data } = await marcasPmAPI.listarUsuariosPM();
        setUsuarios(Array.isArray(data) ? data : []);
      } catch (err) {
        console.error('Error al cargar la lista de usuarios PM', err);
        setUsuarios([]);
        setAlerta({ tipo: 'error', texto: 'Error al cargar los usuarios; probá recargar la página.' });
      }
    })();
  }, [hayParesEnScope]);

  useEffect(() => {
    if (!hayParesEnScope) return;
    (async () => {
      try {
        const { data } = await marcasPmAPI.obtenerConteosSubPMs();
        const items = Array.isArray(data?.conteos) ? data.conteos : [];
        setConteos(Object.fromEntries(items.map((c) => [c.usuario_id, c.total])));
        setConteosError(false);
      } catch (err) {
        console.error('Error al cargar los conteos de sub-PMs', err);
        setConteosError(true);
      }
    })();
  }, [hayParesEnScope]);

  // A titular is never a valid delegation target for their own pairs (the
  // backend also rejects self-grant with 400).
  const usuariosDisponibles = useMemo(
    () => usuarios.filter((u) => u.id !== currentUserId),
    [usuarios, currentUserId],
  );

  const pairsByKey = useMemo(() => {
    const map = new Map();
    for (const par of pares) map.set(parKey(par.marca, par.categoria), par);
    return map;
  }, [pares]);

  // Tracks the CURRENT target user id synchronously, written the instant it
  // changes (inside `seleccionarUsuario`, before any `await`). React STATE
  // (`targetUserId`) is frozen at the render that captured a given async
  // closure — an async continuation reading `targetUserId` later only ever
  // sees the value from when it started, never a real subsequent change.
  // Only a ref can observe a later change from inside an already-running
  // async function. Shared by two independent race guards:
  //   1. `seleccionarUsuario`'s own pre-check response guard (finding #1,
  //      CRITICAL): pick Ana (slow response) -> pick Beto (fast response,
  //      resolves first) -> Ana's response lands late and must NOT overwrite
  //      Beto's baseline. Any response — success OR error — whose id no
  //      longer matches `targetUserIdRef.current` is for a superseded pick
  //      and must be discarded entirely.
  //   2. `guardar()`'s post-save identity check (a later gate finding): the
  //      FIRST version of this check compared `targetUserId` (closure state)
  //      against `usuarioGuardado`, itself assigned from that SAME closure
  //      state — comparing a constant against itself, unconditionally true,
  //      not a guard at all. Comparing against `targetUserIdRef.current`
  //      instead means the check reads LIVE reality, not a frozen copy.
  const targetUserIdRef = useRef(null);

  const seleccionarUsuario = async (usuarioId) => {
    targetUserIdRef.current = usuarioId;
    setTargetUserId(usuarioId);
    setConfirmando(false);
    setAlerta(null);
    setRechazados([]);
    if (usuarioId == null) {
      setBaseline(new Set());
      setChecked(new Set());
      setLoadingGrants(false);
      return;
    }
    setLoadingGrants(true);
    try {
      const { data } = await marcasPmAPI.obtenerGrantsUsuario(usuarioId);
      if (targetUserIdRef.current !== usuarioId) return; // superseded by a later pick
      const grantKeys = new Set((data?.pares || []).map((p) => parKey(p.marca, p.categoria)));
      setBaseline(grantKeys);
      setChecked(new Set(grantKeys));
    } catch (err) {
      console.error('Error al cargar los sub-PMs delegados a este usuario', err);
      if (targetUserIdRef.current !== usuarioId) return; // superseded by a later pick
      setBaseline(new Set());
      setChecked(new Set());
      showError(err, 'Error al cargar los sub-PMs delegados a este usuario');
    } finally {
      // A superseded request's `finally` must NOT turn off a spinner that a
      // NEWER, still in-flight request legitimately turned on — every early
      // `return` above (identity-guard discards) skipped the old
      // `setLoadingGrants(false)` calls that used to live in the success/
      // error branches themselves; moving it here, behind the same guard,
      // is what makes it unconditionally reachable exactly once per request
      // that is still the current one when it settles.
      if (targetUserIdRef.current === usuarioId) setLoadingGrants(false);
    }
  };

  const toggle = (marca, categoria) => {
    const key = parKey(marca, categoria);
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const seleccionarTodoFiltrado = (paresVisibles) => {
    setChecked((prev) => {
      const next = new Set(prev);
      for (const { marca, categoria } of paresVisibles) next.add(parKey(marca, categoria));
      return next;
    });
  };

  const { toGrant, toRevoke } = diffContraBaseline(checked, baseline);
  const dirty = esDirty(checked, baseline);

  const usuarioSeleccionado = usuariosDisponibles.find((u) => u.id === targetUserId) || null;
  const usuarioPendienteNombre =
    usuarioPendiente != null
      ? usuariosDisponibles.find((u) => u.id === usuarioPendiente)?.nombre || `usuario #${usuarioPendiente}`
      : null;

  // Dirty-guard: switching the target user while there are unsaved checked
  // edits must NOT silently discard them (the whole point of this redesign
  // is to stop wasting the user's clicks). While a confirmation is pending,
  // `targetUserId` (and therefore the controlled <select> value) is left
  // untouched — the picker must never visually jump to the new value and
  // then revert, it must stay put until the user confirms.
  //
  // Review finding #1 (merge-blocking): switching target user while a save
  // is IN FLIGHT can race the async response — `guardar()`'s `.then` would
  // otherwise apply the OLD user's `checked` snapshot as the NEW user's
  // baseline once it resolves, silently corrupting a permissions screen.
  // The `<select disabled={saving}>` above is the UX guard; this early
  // return is the correctness guard — it must hold even if the event fires
  // through the disabled attribute (e.g. a programmatic dispatch).
  const pedirCambioUsuario = (nuevoId) => {
    if (saving) return;
    if (dirty) {
      setUsuarioPendiente(nuevoId);
      return;
    }
    seleccionarUsuario(nuevoId);
  };

  const confirmarCambioUsuario = () => {
    if (saving) return; // belt-and-braces, mirrors the guard in pedirCambioUsuario
    const nuevoId = usuarioPendiente;
    setUsuarioPendiente(null);
    seleccionarUsuario(nuevoId);
  };

  const cancelarCambioUsuario = () => {
    setUsuarioPendiente(null);
  };

  const guardar = async () => {
    if (targetUserId == null) return;
    // Snapshot the target user and the checked set being saved. The select
    // is disabled and switching is blocked (via `saving`) for the whole
    // duration of this call — see `pedirCambioUsuario`/`confirmarCambioUsuario`
    // — so, AS THE CODE STANDS TODAY, `targetUserIdRef.current` cannot
    // actually diverge from `usuarioGuardado` by the time the awaited call
    // below settles; this was verified by attempting to drive the false
    // branch in an integration test and confirming it cannot be reached
    // through any exposed interaction. The check is kept anyway, compared
    // against the REF (not `targetUserId` again) as defense-in-depth against
    // a future change that loosens those `saving` guards — if it ever does,
    // this is what stops one user's diff from being written onto another's
    // baseline. Comparing against the ref, rather than a second copy of the
    // same closure-frozen `targetUserId`, is the actual fix: the previous
    // version compared `targetUserId` to itself and was unconditionally
    // true regardless of anything happening at runtime — not a guard.
    const usuarioGuardado = targetUserId;
    const checkedAlGuardar = checked;
    setSaving(true);
    setAlerta(null);
    setRechazados([]);
    try {
      const paresDeseados = [];
      let omitidos = 0;
      for (const key of checkedAlGuardar) {
        const par = pairsByKey.get(key);
        if (!par) {
          // A checked key can outlive its pair (titular reassigned, pair
          // list narrowed since the grant was pre-checked). This is an
          // expected, documented condition — not a failure — so no
          // console.error here (review finding #3); it's counted and
          // surfaced to the user in the success message below instead.
          // Dropped rather than sent: the backend's fail-closed
          // authorization would reject an unknown pair and roll back the
          // WHOLE request anyway, which would be worse — the user would
          // lose every other change too for a pair the UI can't even show.
          omitidos += 1;
          continue;
        }
        paresDeseados.push({ marca: par.marca, categoria: par.categoria });
      }
      const { data } = await marcasPmAPI.asignarSubPMsBulk(usuarioGuardado, paresDeseados);
      if (targetUserIdRef.current === usuarioGuardado) {
        // Keyed by `usuarioGuardado`, so this would be correct even outside
        // the guard — but it stays inside it so every post-save state update
        // obeys the same rule. A future refactor that loosens the `saving`
        // block should not have to notice that one of them opted out.
        setConteos((prev) => ({ ...prev, [usuarioGuardado]: data.total }));
        // Baseline (and `checked`, in lockstep) must reflect what the server
        // actually accepted — built from `paresDeseados`, NOT from the
        // pre-filter `checkedAlGuardar` — or a ghost pair the server never
        // received would sit in `baseline` claiming to be granted, and stay
        // ticked in `checked` implying the same false thing (review finding).
        const nuevaBase = clavesDesdePayload(paresDeseados);
        setBaseline(nuevaBase);
        setChecked(nuevaBase);
        setConfirmando(false);
      }
      const nombreGuardado =
        usuariosDisponibles.find((u) => u.id === usuarioGuardado)?.nombre || `usuario #${usuarioGuardado}`;
      const sufijoOmitidos =
        omitidos > 0
          ? ` ${omitidos} par${omitidos === 1 ? '' : 'es'} omitido${omitidos === 1 ? '' : 's'} porque ya no está${omitidos === 1 ? '' : 'n'} disponible${omitidos === 1 ? '' : 's'}.`
          : '';
      showSuccess(
        `Cambios guardados para ${nombreGuardado}: ${data.otorgados} otorgados, ${data.revocados} revocados.${sufijoOmitidos}`,
      );
    } catch (err) {
      console.error('Error al guardar sub-PMs en bloque', err);
      if (targetUserIdRef.current === usuarioGuardado) setConfirmando(false);
      showError(err, 'Error al guardar los cambios');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.container}>
      <h1 className={styles.title}>{esAdmin ? 'Sub-PMs' : 'Mis Sub-PMs'}</h1>
      <p className={styles.subtitle}>
        {esAdmin
          ? 'Gestioná los sub-PMs de cualquier marca/categoría, incluso las que no tienen titular asignado.'
          : 'Delegá la gestión de tus marcas/categorías a otros usuarios sin cederles la titularidad.'}
      </p>

      {alerta && <ModalAlert type={alerta.tipo === 'success' ? 'success' : 'error'}>{alerta.texto}</ModalAlert>}
      {rechazados.length > 0 && (
        <div className={styles.rechazadosBox}>
          <span>Pares rechazados:</span>
          <ul>
            {rechazados.map((p) => (
              <li key={parKey(p.marca, p.categoria)}>{p.marca} / {p.categoria}</li>
            ))}
          </ul>
        </div>
      )}

      <div className={styles.pickerRow}>
        <label className={styles.pickerLabel} htmlFor="misSubPMsUsuario">Usuario</label>
        <select
          id="misSubPMsUsuario"
          className={styles.select}
          value={targetUserId ?? ''}
          disabled={saving || !hayParesEnScope}
          onChange={(e) => pedirCambioUsuario(e.target.value === '' ? null : Number(e.target.value))}
        >
          <option value="">Elegí un usuario...</option>
          {hayParesEnScope &&
            usuariosDisponibles.map((u) => (
              <option key={u.id} value={u.id}>
                {u.nombre} ({conteosError ? '?' : conteos[u.id] ?? 0})
              </option>
            ))}
        </select>
        {!hayParesEnScope && (
          <span className={styles.conteosAviso}>
            {loadingPares ? 'Cargando marcas/categorías...' : 'No tenés marcas/categorías en tu scope; no hay usuarios para gestionar.'}
          </span>
        )}
        {hayParesEnScope && conteosError && (
          <span className={styles.conteosAviso}>No se pudieron cargar los conteos de sub-PMs; el picker sigue disponible sin ellos.</span>
        )}
      </div>

      {usuarioPendiente != null && (
        <div className={styles.confirmBox}>
          <span>
            Tenés cambios sin guardar para {usuarioSeleccionado?.nombre || `usuario #${targetUserId}`}:
            {' '}<strong>+{toGrant.length}</strong> / <strong>−{toRevoke.length}</strong> pares.
            {' '}¿Descartarlos y cambiar a {usuarioPendienteNombre}?
          </span>
          <div className={styles.confirmActions}>
            <button className="btn-tesla outline-subtle-primary sm" onClick={confirmarCambioUsuario}>
              Sí, cambiar
            </button>
            <button
              className="btn-tesla ghost sm"
              onClick={cancelarCambioUsuario}
              aria-label="Cancelar cambio de usuario"
            >
              Cancelar
            </button>
          </div>
        </div>
      )}

      {loadingPares ? (
        <ModalLoading message="Cargando..." />
      ) : (
        <>
          {loadingGrants ? (
            <ModalLoading message="Cargando sub-PMs delegados..." />
          ) : (
            <ParesTable
              pares={pares}
              checked={checked}
              onToggle={toggle}
              onSelectAllFiltered={seleccionarTodoFiltrado}
            />
          )}

          {targetUserId == null && (
            <div className={styles.emptyDetail}>Elegí un usuario para guardar cambios de delegación.</div>
          )}

          {confirmando && (
            <div className={styles.confirmBox} data-testid="confirmarGuardarBox">
              <span>
                ¿Confirmás guardar los cambios para {usuarioSeleccionado?.nombre || `usuario #${targetUserId}`}?
                {' '}Se otorgarán <strong>+{toGrant.length}</strong> pares y se revocarán <strong>−{toRevoke.length}</strong> pares.
              </span>
              <div className={styles.confirmActions}>
                <button className="btn-tesla outline-subtle-primary sm" onClick={guardar} disabled={saving}>
                  {saving ? 'Guardando...' : 'Sí, guardar'}
                </button>
                <button className="btn-tesla ghost sm" onClick={() => setConfirmando(false)} disabled={saving}>
                  Cancelar
                </button>
              </div>
            </div>
          )}

          <div className={styles.addRow}>
            <button
              className="btn-tesla outline-subtle-primary sm"
              onClick={() => setConfirmando(true)}
              disabled={targetUserId == null || !dirty || saving || usuarioPendiente != null}
            >
              <Save size={14} />
              Guardar cambios
            </button>
          </div>
        </>
      )}
    </div>
  );
}
