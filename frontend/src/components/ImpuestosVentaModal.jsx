/**
 * ImpuestosVentaModal — which ML taxes the sales breakdown deducts and which
 * are only informational (like SIRTAC), by period.
 *
 * `GET /impuestos-venta` lists every withholding ML charged (one row per exact
 * name, so per province) with the treatment in force today and its versions.
 * A tick in "Descontar" means the tax is subtracted from the neto; without it
 * the tax is shown but added back. Saving posts one version per changed tax
 * from the chosen date (`POST /impuestos-venta`), and the backend recalculates
 * the sales of that period.
 *
 * Reading needs `ml_ops.ver`; writing needs `ml_ops.varios_editar`, the same as
 * "% de varios". Disabling the ticks without it is a UI courtesy; the backend
 * permission check is the real gate.
 *
 * Props:
 *   isOpen  - boolean
 *   onClose - function
 */
import { useCallback, useEffect, useState } from 'react';
import { AlertCircle, Loader2, Save } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import api from '../services/api';
import ModalTesla from './ModalTesla';
import styles from './ImpuestosVentaModal.module.css';

const formatFecha = (fecha) => {
  if (!fecha) return '';
  const [year, month, day] = fecha.split('-');
  return `${day}/${month}/${year}`;
};

const detalleDeError = (err, fallback) => {
  const detail = err?.response?.data?.detail;
  return typeof detail === 'string' ? detail : fallback;
};

const primeroDelMes = () => {
  const hoy = new Date();
  return `${hoy.getFullYear()}-${String(hoy.getMonth() + 1).padStart(2, '0')}-01`;
};

const tratamiento = (informativo) => (informativo ? 'Informativo' : 'Se descuenta');

// Why the row is in its current state: the version in force today, or the built-in rule.
const origenDeHoy = (impuesto) => {
  const hoy = new Date().toISOString().slice(0, 10);
  const vigente = impuesto.versiones.find(
    (v) => v.fecha_desde <= hoy && (!v.fecha_hasta || v.fecha_hasta >= hoy),
  );
  if (vigente) return `${tratamiento(vigente.informativo)} desde ${formatFecha(vigente.fecha_desde)}`;
  return `${tratamiento(impuesto.informativo_hoy)} (por defecto)`;
};

export default function ImpuestosVentaModal({ isOpen, onClose }) {
  const { tienePermiso } = usePermisos();
  const puedeEditar = tienePermiso('ml_ops.varios_editar');

  const [impuestos, setImpuestos] = useState([]);
  const [loading, setLoading] = useState(false);
  const [errorCarga, setErrorCarga] = useState(null);

  // charge_name -> informativo wanted, only for the rows the user changed.
  const [cambios, setCambios] = useState({});
  const [fechaDesde, setFechaDesde] = useState(primeroDelMes);
  const [guardando, setGuardando] = useState(false);
  const [errorGuardar, setErrorGuardar] = useState(null);
  const [aviso, setAviso] = useState(null);

  const cargar = useCallback(async () => {
    setLoading(true);
    setErrorCarga(null);
    try {
      const response = await api.get('/impuestos-venta');
      setImpuestos(response.data);
    } catch (err) {
      setErrorCarga(detalleDeError(err, 'No se pudieron cargar los impuestos.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      cargar();
    }
  }, [isOpen, cargar]);

  const informativoDe = (impuesto) =>
    impuesto.charge_name in cambios ? cambios[impuesto.charge_name] : impuesto.informativo_hoy;

  const alternar = (impuesto) => {
    const informativo = !informativoDe(impuesto);
    setAviso(null);
    setCambios((previos) => {
      const siguientes = { ...previos };
      if (informativo === impuesto.informativo_hoy) {
        delete siguientes[impuesto.charge_name];
      } else {
        siguientes[impuesto.charge_name] = informativo;
      }
      return siguientes;
    });
  };

  const handleGuardar = async () => {
    setErrorGuardar(null);
    setAviso(null);
    if (!fechaDesde) {
      setErrorGuardar('Ingresá la fecha desde la que rigen los cambios.');
      return;
    }
    setGuardando(true);
    let recalculando = 0;
    try {
      for (const [chargeName, informativo] of Object.entries(cambios)) {
        const response = await api.post('/impuestos-venta', {
          charge_name: chargeName,
          informativo,
          fecha_desde: fechaDesde,
        });
        recalculando += response.data.recalculando;
        setCambios((previos) => {
          const siguientes = { ...previos };
          delete siguientes[chargeName];
          return siguientes;
        });
      }
      setAviso(`Guardado. Se recalculan ${recalculando} ventas.`);
    } catch (err) {
      setErrorGuardar(detalleDeError(err, 'No se pudo guardar el cambio.'));
    } finally {
      setGuardando(false);
      await cargar();
    }
  };

  const handleClose = () => {
    setCambios({});
    setErrorGuardar(null);
    setAviso(null);
    onClose();
  };

  const hayCambios = Object.keys(cambios).length > 0;

  return (
    <ModalTesla
      isOpen={isOpen}
      onClose={handleClose}
      title="Impuestos de ML"
      subtitle="Qué impuestos se descuentan del neto y cuáles son solo informativos, por período"
      size="lg"
    >
      <div className={styles.container}>
        {loading ? (
          <div className={styles.loading}>
            <Loader2 size={20} className={styles.spin} />
            <span>Cargando impuestos...</span>
          </div>
        ) : errorCarga ? (
          <div className={styles.error}>
            <AlertCircle size={16} />
            <span>{errorCarga}</span>
          </div>
        ) : impuestos.length === 0 ? (
          <p className={styles.empty}>Todavía no hay impuestos de ML en las ventas.</p>
        ) : (
          <table className={styles.tabla}>
            <thead>
              <tr>
                <th>Impuesto</th>
                <th>Descontar</th>
                <th>Hoy</th>
                <th>Historial</th>
              </tr>
            </thead>
            <tbody>
              {impuestos.map((impuesto) => (
                <tr key={impuesto.charge_name}>
                  <td>{impuesto.etiqueta}</td>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`Descontar ${impuesto.etiqueta}`}
                      checked={!informativoDe(impuesto)}
                      disabled={!puedeEditar || guardando}
                      onChange={() => alternar(impuesto)}
                    />
                  </td>
                  <td>{origenDeHoy(impuesto)}</td>
                  <td className={styles.historial}>
                    {impuesto.versiones.length === 0
                      ? '—'
                      : impuesto.versiones.map((v) => (
                          <div key={v.id}>
                            {tratamiento(v.informativo)}: {formatFecha(v.fecha_desde)} →{' '}
                            {v.fecha_hasta ? formatFecha(v.fecha_hasta) : 'vigente'}
                          </div>
                        ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {aviso && <p className={styles.aviso}>{aviso}</p>}

        {/* UI courtesy only: `ml_ops.varios_editar` on the backend is the actual gate. */}
        {puedeEditar && (
          <div className={styles.form}>
            <div>
              <label htmlFor="impuestos-venta-desde">Desde</label>
              <input
                id="impuestos-venta-desde"
                type="date"
                value={fechaDesde}
                onChange={(e) => setFechaDesde(e.target.value)}
              />
            </div>
            <p className={styles.ayuda}>
              Los cambios rigen desde esa fecha y se recalculan las ventas de ese período.
            </p>

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
              disabled={!hayCambios || guardando}
            >
              <Save size={14} />
              {guardando ? 'Guardando...' : 'Guardar cambios'}
            </button>
          </div>
        )}
      </div>
    </ModalTesla>
  );
}
