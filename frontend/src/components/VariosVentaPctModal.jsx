/**
 * VariosVentaPctModal — history + admin form for the "% de varios" used by
 * the ML sales breakdown (`DesgloseDrawer`) to reach "Total Gauss".
 *
 * `GET /varios-venta-pct` returns the full dated/versioned history
 * (newest-first, already sorted by the backend). Reading it only needs
 * `ml_ops.ver` — the same permission that already gates opening VentasML,
 * so anyone who can see the sales list can see this history.
 *
 * Creating a new version (`POST /varios-venta-pct`) needs a SEPARATE
 * permission, `ml_ops.varios_editar`. Hiding the form below when the
 * caller lacks `ml_ops.varios_editar` is a UI COURTESY, not the security
 * boundary — the backend's permission check on the POST endpoint is the
 * real gate. Removing this conditional does not grant write access; it
 * only shows a form whose submit would still 403. Do not treat this
 * component's own gating as enforcement.
 *
 * Props:
 *   isOpen  - boolean
 *   onClose - function
 */
import { useCallback, useEffect, useState } from 'react';
import { AlertCircle, Loader2, Percent } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import api from '../services/api';
import ModalTesla from './ModalTesla';
import styles from './VariosVentaPctModal.module.css';

const formatFecha = (fecha) => {
  if (!fecha) return '';
  const [year, month, day] = fecha.split('-');
  return `${day}/${month}/${year}`;
};

const detalleDeError = (err, fallback) => {
  const detail = err?.response?.data?.detail;
  return typeof detail === 'string' ? detail : fallback;
};

export default function VariosVentaPctModal({ isOpen, onClose }) {
  const { tienePermiso } = usePermisos();
  const puedeEditar = tienePermiso('ml_ops.varios_editar');

  const [historial, setHistorial] = useState([]);
  const [loading, setLoading] = useState(false);
  const [errorCarga, setErrorCarga] = useState(null);

  const [porcentaje, setPorcentaje] = useState('');
  const [fechaDesde, setFechaDesde] = useState('');
  const [guardando, setGuardando] = useState(false);
  const [errorGuardar, setErrorGuardar] = useState(null);

  const cargarHistorial = useCallback(async () => {
    setLoading(true);
    setErrorCarga(null);
    try {
      const response = await api.get('/varios-venta-pct');
      setHistorial(response.data);
    } catch (err) {
      setErrorCarga(detalleDeError(err, 'No se pudo cargar el historial del % de varios.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      cargarHistorial();
    }
  }, [isOpen, cargarHistorial]);

  const limpiarForm = () => {
    setPorcentaje('');
    setFechaDesde('');
    setErrorGuardar(null);
  };

  const handleGuardar = async () => {
    setErrorGuardar(null);

    const valor = parseFloat(porcentaje);
    if (Number.isNaN(valor) || valor < 0 || valor > 100) {
      setErrorGuardar('Ingresá un porcentaje válido entre 0 y 100.');
      return;
    }
    if (!fechaDesde) {
      setErrorGuardar('Ingresá la fecha desde la que rige esta versión.');
      return;
    }

    setGuardando(true);
    try {
      await api.post('/varios-venta-pct', { porcentaje: valor, fecha_desde: fechaDesde });
      limpiarForm();
      await cargarHistorial();
    } catch (err) {
      setErrorGuardar(detalleDeError(err, 'No se pudo guardar la nueva versión del % de varios.'));
    } finally {
      setGuardando(false);
    }
  };

  const handleClose = () => {
    limpiarForm();
    onClose();
  };

  return (
    <ModalTesla
      isOpen={isOpen}
      onClose={handleClose}
      title="% de varios"
      subtitle="Porcentaje dinámico que el desglose de ventas ML resta para llegar a Total Gauss"
      size="md"
    >
      <div className={styles.container}>
        {loading ? (
          <div className={styles.loading}>
            <Loader2 size={20} className={styles.spin} />
            <span>Cargando historial...</span>
          </div>
        ) : errorCarga ? (
          <div className={styles.error}>
            <AlertCircle size={16} />
            <span>{errorCarga}</span>
          </div>
        ) : historial.length === 0 ? (
          <p className={styles.empty}>No hay versiones del % de varios configuradas.</p>
        ) : (
          <table className={styles.tabla}>
            <thead>
              <tr>
                <th>%</th>
                <th>Desde</th>
                <th>Hasta</th>
              </tr>
            </thead>
            <tbody>
              {historial.map((v) => (
                <tr key={v.id}>
                  <td>{v.porcentaje}%</td>
                  <td>{formatFecha(v.fecha_desde)}</td>
                  <td>{v.fecha_hasta ? formatFecha(v.fecha_hasta) : 'Vigente'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {/*
          UI courtesy only: this conditional hides the write form from
          operators who cannot POST /varios-venta-pct, so they are not
          shown controls that would just 403. It does not enforce
          anything by itself — `ml_ops.varios_editar` on the backend is
          the actual authorization boundary. A user could still fire the
          request directly against the API; the backend rejects it there.
        */}
        {puedeEditar && (
          <div className={styles.form}>
            <h4>Cargar nueva versión</h4>
            <div className={styles.formRow}>
              <div>
                <label htmlFor="varios-pct-input">Porcentaje (%)</label>
                <input
                  id="varios-pct-input"
                  type="number"
                  min="0"
                  max="100"
                  step="0.01"
                  placeholder="Ej: 3.5"
                  value={porcentaje}
                  onChange={(e) => setPorcentaje(e.target.value)}
                />
              </div>
              <div>
                <label htmlFor="varios-pct-desde">Desde</label>
                <input
                  id="varios-pct-desde"
                  type="date"
                  value={fechaDesde}
                  onChange={(e) => setFechaDesde(e.target.value)}
                />
              </div>
            </div>

            {errorGuardar && (
              <div className={styles.error}>
                <AlertCircle size={16} />
                <span>{errorGuardar}</span>
              </div>
            )}

            <button
              type="button"
              className={`btn-tesla outline-subtle-primary sm ${guardando ? 'loading' : ''}`}
              onClick={handleGuardar}
              disabled={guardando}
            >
              <Percent size={14} />
              {guardando ? 'Guardando...' : 'Guardar nueva versión'}
            </button>
          </div>
        )}
      </div>
    </ModalTesla>
  );
}
