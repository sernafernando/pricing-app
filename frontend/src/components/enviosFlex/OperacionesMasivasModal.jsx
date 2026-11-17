import { useState, useEffect } from 'react';
import { Layers, Undo2, Check, CircleHelp, Loader2 } from 'lucide-react';
import ModalTesla from '../ModalTesla';
import api from '../../services/api';
import ResultadoDeshacerMasivo, { LogisticaChip } from './ResultadoDeshacerMasivo';
import { plural } from './plural';
import styles from './DeshacerMasivo.module.css';

const pad = (n) => String(n).padStart(2, '0');

// dd/mm HH:MM in the browser's local time.
const formatFecha = (isoString) => {
  const d = new Date(isoString);
  if (Number.isNaN(d.getTime())) return '—';
  return `${pad(d.getDate())}/${pad(d.getMonth() + 1)} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

// The latest bulk logistics assignments; one of them can be reverted whole.
export default function OperacionesMasivasModal({ operadorId = null, onClose, onListo }) {
  const [operaciones, setOperaciones] = useState(null);
  const [errorCarga, setErrorCarga] = useState(false);
  const [recarga, setRecarga] = useState(0);
  const [elegida, setElegida] = useState(null);
  const [deshaciendo, setDeshaciendo] = useState(false);
  const [resultado, setResultado] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let vigente = true;
    api
      .get('/etiquetas-envio/operaciones-masivas-logistica')
      .then(({ data }) => {
        if (!vigente) return;
        setOperaciones(data);
        setErrorCarga(false);
      })
      .catch(() => {
        if (vigente) setErrorCarga(true);
      });
    return () => {
      vigente = false;
    };
  }, [recarga]);

  const deshacer = async () => {
    setDeshaciendo(true);
    setError(null);
    try {
      const { data } = await api.post(
        `/etiquetas-envio/operaciones-masivas-logistica/${elegida.id}/deshacer`,
        { operador_id: operadorId },
      );
      setResultado(data);
      onListo?.(data);
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'No se pudo deshacer la operación.');
    } finally {
      setElegida(null);
      setDeshaciendo(false);
      setRecarga((n) => n + 1);
    }
  };

  const title = (
    <span className={styles.titulo}>
      <span className={styles.tituloIcono} aria-hidden="true">
        <Layers size={18} />
      </span>
      <span>Asignaciones masivas de logística</span>
    </span>
  );

  const footer = (
    <>
      {elegida && (
        <div className={styles.confirmar} role="group" aria-label="Confirmar deshacer operación">
          <CircleHelp size={18} aria-hidden="true" />
          <span className={styles.confirmarTexto}>
            ¿Deshacer la asignación a <LogisticaChip logistica={elegida.logistica} /> del{' '}
            {formatFecha(elegida.cambiado_en)}? Cada etiqueta vuelve a la logística que tenía antes; las que
            cambiaron después se saltean.
          </span>
          <div className={styles.acciones}>
            <button
              type="button"
              className={styles.btnSecundario}
              onClick={() => setElegida(null)}
              disabled={deshaciendo}
            >
              Cancelar
            </button>
            <button type="button" className={styles.btnAviso} onClick={deshacer} disabled={deshaciendo}>
              {deshaciendo ? <Loader2 size={14} className={styles.spin} /> : <Check size={14} />}
              Confirmar
            </button>
          </div>
        </div>
      )}
      <div className={styles.acciones}>
        <button type="button" className={styles.btnSecundario} onClick={onClose}>
          Cerrar
        </button>
      </div>
    </>
  );

  return (
    <ModalTesla
      isOpen
      onClose={onClose}
      title={title}
      footer={footer}
      size="lg"
      className={styles.modal}
      bodyClassName={styles.cuerpo}
    >
      {error && (
        <div className={styles.error} role="alert">
          {error}
        </div>
      )}
      {resultado && <ResultadoDeshacerMasivo resultado={resultado} />}

      {!operaciones && !errorCarga && (
        <div className={styles.estado}>
          <Loader2 size={16} className={styles.spin} /> Cargando asignaciones…
        </div>
      )}
      {errorCarga && !operaciones && (
        <div className={styles.error} role="alert">
          No se pudieron cargar las asignaciones masivas.
        </div>
      )}
      {operaciones && operaciones.length === 0 && (
        <div className={styles.estado}>No hay asignaciones masivas registradas.</div>
      )}

      {operaciones && operaciones.length > 0 && (
        <>
          <div className={styles.encabezado}>
            <span>Fecha</span>
            <span>Quién y a qué logística</span>
            <span>Etiquetas</span>
            <span />
          </div>
          <ul className={styles.lista}>
            {operaciones.map((op) => (
              <li key={op.id} className={elegida?.id === op.id ? styles.filaElegida : styles.fila}>
                <span className={styles.fecha}>{formatFecha(op.cambiado_en)}</span>
                <span className={styles.quien}>
                  <span>{op.usuario_nombre || '—'}</span>
                  <LogisticaChip logistica={op.logistica} />
                </span>
                <span className={styles.cantidad}>{plural(op.etiquetas, 'etiqueta', 'etiquetas')}</span>
                <button
                  type="button"
                  className={styles.btnSecundario}
                  onClick={() => {
                    setError(null);
                    setResultado(null);
                    setElegida(op);
                  }}
                  disabled={deshaciendo}
                  aria-label={`Deshacer la asignación del ${formatFecha(op.cambiado_en)}`}
                >
                  <Undo2 size={14} />
                  Deshacer
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </ModalTesla>
  );
}
