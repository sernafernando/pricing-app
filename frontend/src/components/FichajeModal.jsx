import { useState, useEffect } from 'react';
import { X, UserPlus, User } from 'lucide-react';
import { rrhhAPI } from '../services/api';
import styles from './FichajeModal.module.css';

export default function FichajeModal({ empleado, onClose, onUpdated }) {
  const [tab, setTab] = useState('crear');
  const [usarSegundo, setUsarSegundo] = useState(false);
  const [creando, setCreando] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [usuariosSistema, setUsuariosSistema] = useState([]);
  const [loadingUsuarios, setLoadingUsuarios] = useState(false);
  const [vincularUsuarioId, setVincularUsuarioId] = useState('');

  useEffect(() => {
    const fetchUsuarios = async () => {
      setLoadingUsuarios(true);
      try {
        const { data } = await rrhhAPI.listarUsuariosSistema();
        setUsuariosSistema(Array.isArray(data) ? data : []);
      } catch {
        setUsuariosSistema([]);
      } finally {
        setLoadingUsuarios(false);
      }
    };
    fetchUsuarios();
  }, []);

  const handleCrear = async () => {
    setCreando(true);
    setError(null);
    try {
      const { data } = await rrhhAPI.crearUsuarioFichaje(empleado.id, {
        usar_segundo_nombre: usarSegundo,
      });
      setResult(data);
      onUpdated();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al crear usuario');
    } finally {
      setCreando(false);
    }
  };

  const handleDesvincular = async () => {
    setCreando(true);
    setError(null);
    try {
      await rrhhAPI.actualizarEmpleado(empleado.id, { usuario_id: null });
      setResult({ message: 'Usuario desvinculado del empleado.' });
      onUpdated();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al desvincular usuario');
    } finally {
      setCreando(false);
    }
  };

  const handleVincular = async () => {
    if (!vincularUsuarioId) return;
    setCreando(true);
    setError(null);
    try {
      await rrhhAPI.actualizarEmpleado(empleado.id, {
        usuario_id: parseInt(vincularUsuarioId, 10),
      });
      const usuario = usuariosSistema.find((u) => u.id === parseInt(vincularUsuarioId, 10));
      setResult({
        usuario_id: parseInt(vincularUsuarioId, 10),
        username: usuario?.username || '',
        message: `Usuario "${usuario?.username || vincularUsuarioId}" vinculado al empleado.`,
      });
      onUpdated();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al vincular usuario');
    } finally {
      setCreando(false);
    }
  };

  return (
    <div className="modal-overlay-tesla">
      <div className="modal-tesla lg">
        <div className="modal-header-tesla">
          <h2 className="modal-title-tesla">Usuario de fichaje</h2>
          <button className="btn-close-tesla" onClick={onClose} aria-label="Cerrar">
            <X size={14} />
          </button>
        </div>
        <div className="modal-body-tesla">
          <p className={styles.subtext}>
            Empleado: <strong>{empleado.nombre} {empleado.apellido}</strong> ({empleado.legajo})
          </p>

          {empleado.usuario_id && !result && (
            <div className={styles.linkedBox}>
              <p className={styles.linkedTitle}>Usuario vinculado</p>
              <p className={styles.linkedDetail}>
                {usuariosSistema.find((u) => u.id === empleado.usuario_id)?.username || `ID #${empleado.usuario_id}`}
                {' — '}
                {usuariosSistema.find((u) => u.id === empleado.usuario_id)?.nombre || ''}
              </p>
            </div>
          )}

          {!empleado.usuario_id && !result && (
            <div className={styles.tabRow}>
              <button
                className={tab === 'crear' ? styles.btnActive : styles.btnInactive}
                onClick={() => { setTab('crear'); setError(null); }}
              >
                <UserPlus size={14} /> Crear nuevo
              </button>
              <button
                className={tab === 'vincular' ? styles.btnActive : styles.btnInactive}
                onClick={() => { setTab('vincular'); setError(null); }}
              >
                <User size={14} /> Vincular existente
              </button>
            </div>
          )}

          {!empleado.usuario_id && tab === 'crear' && !result && (
            <>
              <p className={styles.hint}>
                Se crea un usuario con rol FICHAJE (solo acceso a fichaje mobile). Password: DNI del empleado.
              </p>
              <div className={styles.formGroup}>
                <label>Inicial del nombre para el username</label>
                <select
                  className={styles.select}
                  value={usarSegundo ? 'segundo' : 'primero'}
                  onChange={(e) => setUsarSegundo(e.target.value === 'segundo')}
                >
                  <option value="primero">
                    Primer nombre ({empleado.nombre?.split(' ')[0]?.[0]?.toLowerCase() || '?'}{empleado.apellido?.toLowerCase()})
                  </option>
                  {empleado.nombre?.split(' ').length > 1 && (
                    <option value="segundo">
                      Segundo nombre ({empleado.nombre?.split(' ')[1]?.[0]?.toLowerCase() || '?'}{empleado.apellido?.toLowerCase()})
                    </option>
                  )}
                </select>
              </div>
            </>
          )}

          {!empleado.usuario_id && tab === 'vincular' && !result && (
            <>
              <p className={styles.hint}>
                Vincular un usuario que ya existe en el sistema a este empleado.
              </p>
              <div className={styles.formGroup}>
                <label>Usuario existente</label>
                {loadingUsuarios ? (
                  <p className={styles.hint}>Cargando usuarios...</p>
                ) : (
                  <select
                    className={styles.select}
                    value={vincularUsuarioId}
                    onChange={(e) => setVincularUsuarioId(e.target.value)}
                  >
                    <option value="">Seleccionar usuario...</option>
                    {usuariosSistema
                      .filter((u) => u.activo)
                      .map((u) => (
                        <option key={u.id} value={u.id}>
                          {u.username} — {u.nombre}
                        </option>
                      ))}
                  </select>
                )}
              </div>
            </>
          )}

          {error && <div className={styles.error}>{error}</div>}

          {result && (
            <div className={styles.successBox}>
              <p className={styles.successTitle}>{result.message}</p>
              {result.username && (
                <p className={styles.successDetail}>
                  Usuario: <strong>{result.username}</strong>
                </p>
              )}
            </div>
          )}
        </div>
        <div className="modal-footer-tesla">
          <button className={styles.btnInactive} onClick={onClose}>
            {result ? 'Cerrar' : 'Cancelar'}
          </button>
          {!result && !empleado.usuario_id && tab === 'crear' && (
            <button className={styles.btnActive} onClick={handleCrear} disabled={creando}>
              {creando ? 'Creando...' : 'Crear usuario'}
            </button>
          )}
          {!result && !empleado.usuario_id && tab === 'vincular' && (
            <button className={styles.btnActive} onClick={handleVincular} disabled={creando || !vincularUsuarioId}>
              {creando ? 'Vinculando...' : 'Vincular'}
            </button>
          )}
          {!result && empleado.usuario_id && (
            <button className={styles.btnDanger} onClick={handleDesvincular} disabled={creando}>
              {creando ? 'Desvinculando...' : 'Desvincular usuario'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
