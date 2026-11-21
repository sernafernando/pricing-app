import { useEffect, useState } from 'react';
import { accionesIaAPI } from '../../services/api';
import styles from './InterruptorEscritura.module.css';

const BLOQUEADO = 'La escritura de la IA está bloqueada desde el servidor. No se puede encender desde acá.';

const mensajeError = (err) =>
  err?.response?.status === 403
    ? 'No tenés permiso para cambiar la escritura de la IA (mcp.escribir).'
    : 'No se pudo cambiar la escritura de la IA. Probá de nuevo.';

/**
 * DB switch that allows AI writes through MCP (default off). When the server's
 * env kill switch is on (`fuente == "kill_switch"`) it wins: the toggle is locked.
 */
export default function InterruptorEscritura() {
  const [estado, setEstado] = useState(null);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let vigente = true;
    accionesIaAPI
      .getEscritura()
      .then(({ data }) => {
        if (vigente) setEstado(data);
      })
      .catch((err) => {
        if (!vigente) return;
        setError(
          err?.response?.status === 403
            ? 'No tenés permiso para ver la escritura de la IA (mcp.escribir).'
            : 'No se pudo leer si la escritura de la IA está encendida.'
        );
      });
    return () => {
      vigente = false;
    };
  }, []);

  const cambiar = async () => {
    setGuardando(true);
    setError(null);
    try {
      const { data } = await accionesIaAPI.setEscritura(!estado.habilitado);
      setEstado(data);
    } catch (err) {
      setError(mensajeError(err));
    } finally {
      setGuardando(false);
    }
  };

  const bloqueado = estado?.fuente === 'kill_switch';
  const habilitado = Boolean(estado?.habilitado) && !bloqueado;

  return (
    <section className={styles.panel} aria-labelledby="escritura-ia-titulo">
      <div className={styles.texto}>
        <h2 id="escritura-ia-titulo" className={styles.titulo}>
          Escritura de la IA
        </h2>
        <p className={styles.ayuda}>
          Con la escritura apagada, ninguna IA conectada puede modificar Pricing (solo consultar).
        </p>
      </div>
      {estado && (
        <div className={styles.control}>
          <span className={habilitado ? styles.encendida : styles.apagada}>{habilitado ? 'Encendida' : 'Apagada'}</span>
          <button
            type="button"
            role="switch"
            aria-checked={habilitado}
            aria-label="Permitir que la IA modifique Pricing"
            className={`${styles.interruptor} ${habilitado ? styles.interruptorOn : ''}`}
            disabled={bloqueado || guardando}
            onClick={cambiar}
          >
            <span className={styles.perilla} />
          </button>
        </div>
      )}
      {bloqueado && <p className={styles.bloqueado}>{BLOQUEADO}</p>}
      {error && (
        <div className={styles.error} role="alert">
          {error}
        </div>
      )}
    </section>
  );
}
