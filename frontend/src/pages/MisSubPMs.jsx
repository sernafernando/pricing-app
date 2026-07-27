import { useState, useEffect, useCallback } from 'react';
import { Plus, Trash2, ShieldCheck } from 'lucide-react';
import { marcasPmAPI } from '../services/api';
import { ModalAlert, ModalLoading } from '../components/ModalTesla';
import { useAuthStore } from '../store/authStore';
import { usePermisos } from '../contexts/PermisosContext';
import styles from './MisSubPMs.module.css';

/**
 * MisSubPMs — sub-PM delegation surface (sub-pm-scope-marcas PR3).
 *
 * Two modes, both backed by the same sub-PM endpoints (the backend's
 * `_require_titular_or_admin` already authorizes admins on ANY pair):
 *
 *   - Titular mode (default): pairs come from `GET /marcas-pm/mis-titularidades`
 *     (deliberately NOT the UNION'd mis-marcas), so a titular only sees and
 *     manages their OWN pairs. Purely data-scoped, no permiso gate.
 *   - Admin mode (`admin.gestionar_pms`, same gate as GestionPM): pairs come
 *     from `GET /marcas-pm` — every (marca, categoria) pair, including pairs
 *     with NO titular assigned, which are otherwise unmanageable from the UI.
 */
export default function MisSubPMs() {
  const currentUserId = useAuthStore((s) => s.user?.id);
  const { tienePermiso } = usePermisos();
  const esAdmin = tienePermiso('admin.gestionar_pms');

  const [pares, setPares] = useState([]);
  const [loadingPares, setLoadingPares] = useState(true);
  const [selectedId, setSelectedId] = useState(null);

  const [subPMs, setSubPMs] = useState([]);
  const [loadingSubPMs, setLoadingSubPMs] = useState(false);

  const [usuarios, setUsuarios] = useState([]);
  const [nuevoUsuarioId, setNuevoUsuarioId] = useState('');
  const [otorgando, setOtorgando] = useState(false);
  const [revocandoId, setRevocandoId] = useState(null);
  const [confirmarRevocar, setConfirmarRevocar] = useState(null); // grant pending confirmation

  const [alerta, setAlerta] = useState(null); // { tipo: 'error' | 'success', texto }

  const showError = useCallback((err, fallback) => {
    setAlerta({ tipo: 'error', texto: err?.response?.data?.detail || fallback });
  }, []);
  const showSuccess = useCallback((texto) => {
    setAlerta({ tipo: 'success', texto });
  }, []);

  const cargarPares = useCallback(async () => {
    setLoadingPares(true);
    try {
      let nuevosPares;
      if (esAdmin) {
        // `admin.gestionar_pms` can be granted as an override to a non-admin
        // role, but GET /marcas-pm is role-gated (403) — fall back to the
        // titular scope instead of leaving the page empty. ONLY on 403: any
        // other failure must surface as an error, never as a silently
        // narrower pair list.
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
      setSelectedId((prevId) => {
        if (prevId != null && !nuevosPares.some((p) => p.id === prevId)) {
          setSubPMs([]);
          return null;
        }
        return prevId;
      });
    } catch (err) {
      setPares([]);
      showError(err, esAdmin ? 'Error al cargar las marcas/categorías' : 'Error al cargar tus marcas/categorías');
    } finally {
      setLoadingPares(false);
    }
  }, [showError, esAdmin]);

  const cargarSubPMs = useCallback(async (par) => {
    if (!par) return;
    setLoadingSubPMs(true);
    try {
      const { data } = await marcasPmAPI.listarSubPMs(par.marca, par.categoria);
      setSubPMs(Array.isArray(data) ? data : []);
    } catch (err) {
      setSubPMs([]);
      showError(err, 'Error al cargar los sub-PMs delegados');
    } finally {
      setLoadingSubPMs(false);
    }
  }, [showError]);

  useEffect(() => {
    cargarPares();
  }, [cargarPares]);

  // Only fetch the (potentially sensitive) global user list once we know the
  // current user is a titular of at least one pair — a non-titular hitting
  // this route directly must never trigger GET /usuarios/pms.
  useEffect(() => {
    if (loadingPares || pares.length === 0) return;
    let cancelado = false;
    (async () => {
      try {
        const { data } = await marcasPmAPI.listarUsuariosPM();
        if (!cancelado) setUsuarios(Array.isArray(data) ? data : []);
      } catch {
        // Non-blocking: the grant form just has an empty picker if this fails.
        if (!cancelado) setUsuarios([]);
      }
    })();
    return () => {
      cancelado = true;
    };
  }, [loadingPares, pares.length]);

  const selectedPar = pares.find((p) => p.id === selectedId) || null;

  const seleccionarPar = (par) => {
    setSelectedId(par.id);
    setNuevoUsuarioId('');
    setConfirmarRevocar(null);
    setAlerta(null);
    cargarSubPMs(par);
  };

  const otorgarSubPM = async () => {
    if (!selectedPar || !nuevoUsuarioId) return;
    setOtorgando(true);
    setAlerta(null);
    try {
      await marcasPmAPI.crearSubPM({
        marca: selectedPar.marca,
        categoria: selectedPar.categoria,
        usuario_id: parseInt(nuevoUsuarioId, 10),
      });
      showSuccess('Sub-PM otorgado');
      setNuevoUsuarioId('');
      await cargarSubPMs(selectedPar);
    } catch (err) {
      showError(err, 'Error al otorgar el sub-PM');
    } finally {
      setOtorgando(false);
    }
  };

  const pedirConfirmacionRevocar = (grant) => {
    setConfirmarRevocar(grant);
    setAlerta(null);
  };

  const cancelarRevocar = () => {
    setConfirmarRevocar(null);
  };

  const confirmarRevocarSubPM = async () => {
    const grant = confirmarRevocar;
    if (!grant) return;
    setRevocandoId(grant.id);
    setAlerta(null);
    try {
      await marcasPmAPI.eliminarSubPM(grant.id);
      showSuccess(`Revocaste el sub-PM de ${grant.usuario_nombre || `usuario #${grant.usuario_id}`}`);
      setConfirmarRevocar(null);
      await cargarSubPMs(selectedPar);
    } catch (err) {
      showError(err, 'Error al revocar el sub-PM');
    } finally {
      setRevocandoId(null);
    }
  };

  // The current logged-in user may be titular of several pairs; regardless
  // of which pair is selected, never offer them as a sub-PM in their own
  // picker (the backend also rejects self-grant with 400).
  const usuariosDisponibles = usuarios.filter(
    (u) => !subPMs.some((g) => g.usuario_id === u.id) && u.id !== currentUserId,
  );

  return (
    <div className={styles.container}>
      <h1 className={styles.title}>{esAdmin ? 'Sub-PMs' : 'Mis Sub-PMs'}</h1>
      <p className={styles.subtitle}>
        {esAdmin
          ? 'Gestioná los sub-PMs de cualquier marca/categoría, incluso las que no tienen titular asignado.'
          : 'Delegá la gestión de tus marcas/categorías a otros usuarios sin cederles la titularidad.'}
      </p>

      {alerta && <ModalAlert type={alerta.tipo === 'success' ? 'success' : 'error'}>{alerta.texto}</ModalAlert>}

      <div className={styles.layout}>
        <div className={styles.listPanel}>
          <div className={styles.sectionTitle}>{esAdmin ? 'Marcas/categorías' : 'Tus marcas/categorías'}</div>
          {loadingPares ? (
            <ModalLoading message="Cargando..." />
          ) : pares.length === 0 ? (
            <div className={styles.emptyState}>
              {esAdmin
                ? 'No hay marcas/categorías cargadas.'
                : 'No sos titular de ninguna marca/categoría.'}
            </div>
          ) : (
            <div className={styles.parList}>
              {pares.map((par) => (
                <button
                  key={par.id}
                  className={`${styles.parItem} ${selectedId === par.id ? styles.parItemActive : ''}`}
                  onClick={() => seleccionarPar(par)}
                >
                  <ShieldCheck size={14} />
                  <span className={styles.parLabel}>{par.marca} / {par.categoria}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className={styles.detailPanel}>
          {!selectedPar ? (
            <div className={styles.emptyDetail}>
              Seleccioná una marca/categoría para gestionar sus sub-PMs.
            </div>
          ) : (
            <>
              <h3 className={styles.detailTitle}>{selectedPar.marca} / {selectedPar.categoria}</h3>

              <div className={styles.sectionTitle}>Sub-PMs delegados</div>
              {loadingSubPMs ? (
                <ModalLoading message="Cargando sub-PMs..." />
              ) : subPMs.length === 0 ? (
                <div className={styles.emptyState}>
                  {esAdmin
                    ? 'Este par todavía no tiene sub-PMs delegados.'
                    : 'Todavía no delegaste sub-PMs en este par.'}
                </div>
              ) : (
                <div className={styles.grantList}>
                  {subPMs.map((g) => (
                    <div key={g.id} className={styles.grantRow}>
                      <span className={styles.grantName}>{g.usuario_nombre || `Usuario #${g.usuario_id}`}</span>
                      <button
                        className="btn-tesla outline-subtle-danger icon-only sm"
                        onClick={() => pedirConfirmacionRevocar(g)}
                        disabled={revocandoId === g.id}
                        aria-label={`Revocar sub-PM de ${g.usuario_nombre || g.usuario_id}`}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {confirmarRevocar && (
                <div className={styles.confirmBox}>
                  <span>
                    ¿Revocar el sub-PM de {confirmarRevocar.usuario_nombre || `usuario #${confirmarRevocar.usuario_id}`}{' '}
                    en {selectedPar.marca} / {selectedPar.categoria}?
                  </span>
                  <div className={styles.confirmActions}>
                    <button
                      className="btn-tesla outline-subtle-danger sm"
                      onClick={confirmarRevocarSubPM}
                      disabled={revocandoId === confirmarRevocar.id}
                      aria-label={`Confirmar revocación del sub-PM de ${confirmarRevocar.usuario_nombre || confirmarRevocar.usuario_id}`}
                    >
                      {revocandoId === confirmarRevocar.id ? 'Revocando...' : 'Sí, revocar'}
                    </button>
                    <button
                      className="btn-tesla ghost sm"
                      onClick={cancelarRevocar}
                      disabled={revocandoId === confirmarRevocar.id}
                      aria-label="Cancelar revocación"
                    >
                      Cancelar
                    </button>
                  </div>
                </div>
              )}

              <div className={styles.addRow}>
                <select
                  className={styles.select}
                  value={nuevoUsuarioId}
                  onChange={(e) => setNuevoUsuarioId(e.target.value)}
                  aria-label="Usuario a delegar como sub-PM"
                >
                  <option value="">Otorgar sub-PM a...</option>
                  {usuariosDisponibles.map((u) => (
                    <option key={u.id} value={u.id}>{u.nombre}</option>
                  ))}
                </select>
                <button
                  className="btn-tesla outline-subtle-primary sm"
                  onClick={otorgarSubPM}
                  disabled={otorgando || !nuevoUsuarioId}
                >
                  <Plus size={14} />
                  {otorgando ? 'Otorgando...' : 'Otorgar'}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
