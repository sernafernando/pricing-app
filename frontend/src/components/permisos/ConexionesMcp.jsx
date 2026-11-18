import { useEffect, useState } from 'react';
import { mcpConexionesAPI } from '../../services/api';
import styles from './ConexionesMcp.module.css';

const formatearFecha = (iso) =>
  new Date(iso).toLocaleString('es-AR', { dateStyle: 'short', timeStyle: 'short' });

/**
 * "Conexiones de IA (MCP)" section of the user dialog: the user's active MCP
 * connections (e.g. ChatGPT) with a Revocar button each. Revoking cuts the
 * client's access on its next call. Admin endpoints (ADMIN / SUPERADMIN).
 */
export default function ConexionesMcp({ usuarioId }) {
  const [conexiones, setConexiones] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState(null);
  const [revocando, setRevocando] = useState(null);
  // The connection whose row asks "¿Revocar?" (inline confirmation: this section lives inside a modal).
  const [confirmando, setConfirmando] = useState(null);

  useEffect(() => {
    let vigente = true;
    setCargando(true);
    setError(null);
    mcpConexionesAPI
      .listarDeUsuario(usuarioId)
      .then(({ data }) => {
        if (vigente) setConexiones(Array.isArray(data) ? data : []);
      })
      .catch(() => {
        if (vigente) setError('No se pudieron cargar las conexiones.');
      })
      .finally(() => {
        if (vigente) setCargando(false);
      });
    return () => {
      vigente = false;
    };
  }, [usuarioId]);

  const revocar = async (conexion) => {
    setConfirmando(null);
    setRevocando(conexion.id);
    setError(null);
    try {
      await mcpConexionesAPI.revocar(conexion.id);
      setConexiones((prev) => prev.filter((c) => c.id !== conexion.id));
    } catch (err) {
      if (err?.response?.status === 404) {
        // Already revoked elsewhere: it is not active anymore either way.
        setConexiones((prev) => prev.filter((c) => c.id !== conexion.id));
      } else {
        setError('No se pudo revocar la conexión.');
      }
    } finally {
      setRevocando(null);
    }
  };

  return (
    <section className={styles.seccion} aria-labelledby="conexiones-mcp-titulo">
      <h3 id="conexiones-mcp-titulo" className={styles.titulo}>
        Conexiones de IA (MCP)
      </h3>

      {error && (
        <div className={styles.error} role="alert">
          {error}
        </div>
      )}

      {cargando && <p className={styles.muted}>Cargando...</p>}

      {!cargando && !error && conexiones.length === 0 && <p className={styles.muted}>Sin conexiones activas.</p>}

      {!cargando && conexiones.length > 0 && (
        <ul className={styles.lista}>
          {conexiones.map((conexion) => (
            <li key={conexion.id} className={styles.fila}>
              <div className={styles.info}>
                <span className={styles.nombre}>{conexion.client_name}</span>
                <span className={styles.muted}>
                  Conectada el {formatearFecha(conexion.created_at)} · Último uso:{' '}
                  {conexion.last_used_at ? formatearFecha(conexion.last_used_at) : 'nunca'}
                </span>
              </div>
              {confirmando === conexion.id ? (
                <div className={styles.confirmar} role="group" aria-label={`Confirmar revocación de ${conexion.client_name}`}>
                  <span className={styles.muted}>¿Revocar? Va a tener que volver a conectarse.</span>
                  <button type="button" className="btn-tesla danger sm" onClick={() => revocar(conexion)}>
                    Sí, revocar
                  </button>
                  <button type="button" className="btn-tesla ghost sm" onClick={() => setConfirmando(null)}>
                    Cancelar
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  className="btn-tesla outline-subtle-danger sm"
                  disabled={revocando === conexion.id}
                  onClick={() => setConfirmando(conexion.id)}
                >
                  Revocar
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
