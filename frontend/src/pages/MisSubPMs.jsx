import { useState, useEffect, useCallback } from 'react';
import { Plus, Trash2, ShieldCheck } from 'lucide-react';
import { marcasPmAPI } from '../services/api';
import { ModalAlert, ModalLoading } from '../components/ModalTesla';
import styles from './MisSubPMs.module.css';

/**
 * MisSubPMs — non-admin titular surface for sub-PM delegation
 * (sub-pm-scope-marcas PR3).
 *
 * A titular of one or more (marca, categoria) pairs (per
 * `GET /marcas-pm/mis-titularidades`, deliberately NOT the UNION'd
 * mis-marcas) can grant/revoke sub-PMs on THEIR OWN pairs here. Admins
 * manage everything via the existing GestionPM.jsx; this page carries no
 * admin permiso gate — visibility is purely data-scoped (you only see pairs
 * you are the titular of).
 */
export default function MisSubPMs() {
  const [pares, setPares] = useState([]);
  const [loadingPares, setLoadingPares] = useState(true);
  const [selectedId, setSelectedId] = useState(null);

  const [subPMs, setSubPMs] = useState([]);
  const [loadingSubPMs, setLoadingSubPMs] = useState(false);

  const [usuarios, setUsuarios] = useState([]);
  const [nuevoUsuarioId, setNuevoUsuarioId] = useState('');
  const [otorgando, setOtorgando] = useState(false);
  const [revocandoId, setRevocandoId] = useState(null);

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
      const { data } = await marcasPmAPI.misTitularidades();
      setPares(Array.isArray(data?.pares) ? data.pares : []);
    } catch (err) {
      setPares([]);
      showError(err, 'Error al cargar tus marcas/categorías');
    } finally {
      setLoadingPares(false);
    }
  }, [showError]);

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
    (async () => {
      try {
        const { data } = await marcasPmAPI.listarUsuariosPM();
        setUsuarios(Array.isArray(data) ? data : []);
      } catch {
        // Non-blocking: the grant form just has an empty picker if this fails.
        setUsuarios([]);
      }
    })();
  }, [cargarPares]);

  const selectedPar = pares.find((p) => p.id === selectedId) || null;

  const seleccionarPar = (par) => {
    setSelectedId(par.id);
    setNuevoUsuarioId('');
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

  const revocarSubPM = async (grant) => {
    setRevocandoId(grant.id);
    setAlerta(null);
    try {
      await marcasPmAPI.eliminarSubPM(grant.id);
      showSuccess(`Revocaste el sub-PM de ${grant.usuario_nombre || `usuario #${grant.usuario_id}`}`);
      await cargarSubPMs(selectedPar);
    } catch (err) {
      showError(err, 'Error al revocar el sub-PM');
    } finally {
      setRevocandoId(null);
    }
  };

  const usuariosDisponibles = usuarios.filter(
    (u) => !subPMs.some((g) => g.usuario_id === u.id) && u.id !== selectedPar?.usuario_id,
  );

  return (
    <div className={styles.container}>
      <h1 className={styles.title}>Mis Sub-PMs</h1>
      <p className={styles.subtitle}>
        Delegá la gestión de tus marcas/categorías a otros usuarios sin cederles la titularidad.
      </p>

      {alerta && <ModalAlert type={alerta.tipo === 'success' ? 'success' : 'error'}>{alerta.texto}</ModalAlert>}

      <div className={styles.layout}>
        <div className={styles.listPanel}>
          <div className={styles.sectionTitle}>Tus marcas/categorías</div>
          {loadingPares ? (
            <ModalLoading message="Cargando..." />
          ) : pares.length === 0 ? (
            <div className={styles.emptyState}>No sos titular de ninguna marca/categoría.</div>
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
                <div className={styles.emptyState}>Todavía no delegaste sub-PMs en este par.</div>
              ) : (
                <div className={styles.grantList}>
                  {subPMs.map((g) => (
                    <div key={g.id} className={styles.grantRow}>
                      <span className={styles.grantName}>{g.usuario_nombre || `Usuario #${g.usuario_id}`}</span>
                      <button
                        className="btn-tesla outline-subtle-danger icon-only sm"
                        onClick={() => revocarSubPM(g)}
                        disabled={revocandoId === g.id}
                        aria-label={`Revocar sub-PM de ${g.usuario_nombre || g.usuario_id}`}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  ))}
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
