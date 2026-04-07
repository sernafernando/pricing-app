import { useState, useEffect } from 'react';
import { X, UserPlus, User } from 'lucide-react';
import { rrhhAPI } from '../services/api';
import styles from './FichajeModal.module.css';

const stripAccents = (str) =>
  str.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z]/g, '');

function buildUsernameOptions(nombre, apellido) {
  const nombreParts = nombre?.trim().split(/\s+/) || [];
  const apellidoParts = apellido?.trim().split(/\s+/) || [];
  const apellidoFull = stripAccents(apellido?.replace(/\s+/g, '') || '');
  const apellidoFirst = stripAccents(apellidoParts[0] || '');
  const tieneApellidoCompuesto = apellidoParts.length > 1;

  const options = [];
  const seen = new Set();

  const add = (label, username, params) => {
    if (seen.has(username)) return;
    seen.add(username);
    options.push({ label, username, ...params });
  };

  // Primer nombre + primer apellido
  const ini1 = stripAccents(nombreParts[0]?.[0] || '?');
  add(
    `${nombreParts[0]} ${apellidoParts[0]}`,
    `${ini1}${apellidoFirst}`,
    { usar_segundo_nombre: false, solo_primer_apellido: true },
  );

  // Primer nombre + apellido compuesto
  if (tieneApellidoCompuesto) {
    add(
      `${nombreParts[0]} ${apellido}`,
      `${ini1}${apellidoFull}`,
      { usar_segundo_nombre: false, solo_primer_apellido: false },
    );
  }

  // Segundo nombre + primer apellido
  if (nombreParts.length > 1) {
    const ini2 = stripAccents(nombreParts[1]?.[0] || '?');
    add(
      `${nombreParts[1]} ${apellidoParts[0]}`,
      `${ini2}${apellidoFirst}`,
      { usar_segundo_nombre: true, solo_primer_apellido: true },
    );

    // Segundo nombre + apellido compuesto
    if (tieneApellidoCompuesto) {
      add(
        `${nombreParts[1]} ${apellido}`,
        `${ini2}${apellidoFull}`,
        { usar_segundo_nombre: true, solo_primer_apellido: false },
      );
    }
  }

  return options;
}

export default function FichajeModal({ empleado, onClose, onUpdated }) {
  const [tab, setTab] = useState('crear');
  const usernameOptions = buildUsernameOptions(empleado.nombre, empleado.apellido);
  const [selectedOption, setSelectedOption] = useState(0);
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
      const opt = usernameOptions[selectedOption] || {};
      const { data } = await rrhhAPI.crearUsuarioFichaje(empleado.id, {
        usar_segundo_nombre: opt.usar_segundo_nombre || false,
        solo_primer_apellido: opt.solo_primer_apellido ?? false,
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
                <label>Username</label>
                <select
                  className={styles.select}
                  value={selectedOption}
                  onChange={(e) => setSelectedOption(parseInt(e.target.value, 10))}
                >
                  {usernameOptions.map((opt, i) => (
                    <option key={i} value={i}>
                      {opt.label} ({opt.username})
                    </option>
                  ))}
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
