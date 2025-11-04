import { useState, useEffect } from 'react';
import axios from 'axios';
import styles from './DashboardVentas.module.css';

export default function DashboardVentas() {
  const [ventas, setVentas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');

  useEffect(() => {
    // Configurar fechas por defecto: hoy y mañana
    const hoy = new Date();
    const manana = new Date(hoy);
    manana.setDate(manana.getDate() + 1);

    const formatearFecha = (fecha) => {
      return fecha.toISOString().split('T')[0];
    };

    setFromDate(formatearFecha(hoy));
    setToDate(formatearFecha(manana));
  }, []);

  useEffect(() => {
    if (fromDate && toDate) {
      cargarVentas();
    }
  }, [fromDate, toDate]);

  const cargarVentas = async () => {
    setLoading(true);
    try {
      const response = await axios.get(
        `https://parser-worker-js.gaussonline.workers.dev/consulta`,
        {
          params: {
            strScriptLabel: 'scriptDashboard',
            fromDate: fromDate,
            toDate: toDate
          }
        }
      );
      setVentas(Array.isArray(response.data) ? response.data : []);
    } catch (error) {
      console.error('Error cargando ventas:', error);
      alert('Error al cargar las ventas');
      setVentas([]);
    } finally {
      setLoading(false);
    }
  };

  const formatearFecha = (fecha) => {
    const date = new Date(fecha);
    return date.toLocaleString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: 'America/Argentina/Buenos_Aires'
    });
  };

  const formatearMoneda = (monto) => {
    return new Intl.NumberFormat('es-AR', {
      style: 'currency',
      currency: 'ARS',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0
    }).format(monto);
  };

  const formatearDolar = (monto) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(monto);
  };

  const getTipoLogistica = (tipo) => {
    const tipos = {
      'cross_docking': '📦 Full',
      'self_service': '🏢 Flex',
      'drop_off': '📮 Drop Off'
    };
    return tipos[tipo] || tipo;
  };

  const calcularTotales = () => {
    return ventas.reduce((acc, venta) => {
      acc.cantidad += venta.Cantidad || 0;
      acc.montoTotal += venta.Monto_Total || 0;
      acc.costoEnvio += venta.MLShippmentCost4Seller || 0;
      return acc;
    }, { cantidad: 0, montoTotal: 0, costoEnvio: 0 });
  };

  const totales = calcularTotales();

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1 className={styles.title}>📊 Dashboard de Ventas MercadoLibre</h1>
        <div className={styles.filtros}>
          <div className={styles.filtroFecha}>
            <label>Desde:</label>
            <input
              type="date"
              value={fromDate}
              onChange={(e) => setFromDate(e.target.value)}
              className={styles.dateInput}
            />
          </div>
          <div className={styles.filtroFecha}>
            <label>Hasta:</label>
            <input
              type="date"
              value={toDate}
              onChange={(e) => setToDate(e.target.value)}
              className={styles.dateInput}
            />
          </div>
          <button onClick={cargarVentas} className={styles.btnRecargar}>
            🔄 Recargar
          </button>
        </div>
      </div>

      {loading ? (
        <div className={styles.loading}>Cargando ventas...</div>
      ) : (
        <>
          <div className={styles.statsCard}>
            <div className={styles.statItem}>
              <div className={styles.statLabel}>Total Ventas</div>
              <div className={styles.statValue}>{ventas.length}</div>
            </div>
            <div className={styles.statItem}>
              <div className={styles.statLabel}>Unidades Vendidas</div>
              <div className={styles.statValue}>{totales.cantidad}</div>
            </div>
            <div className={styles.statItem}>
              <div className={styles.statLabel}>Monto Total</div>
              <div className={styles.statValue}>{formatearMoneda(totales.montoTotal)}</div>
            </div>
            <div className={styles.statItem}>
              <div className={styles.statLabel}>Costo Envíos</div>
              <div className={styles.statValue}>{formatearMoneda(totales.costoEnvio)}</div>
            </div>
          </div>

          <div className={styles.tableWrapper}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th>ID Op.</th>
                  <th>Marca</th>
                  <th>Categoría</th>
                  <th>Descripción</th>
                  <th>Cant.</th>
                  <th>Monto Unit.</th>
                  <th>Monto Total</th>
                  <th>Costo USD</th>
                  <th>IVA %</th>
                  <th>Tipo Log.</th>
                  <th>Costo Envío</th>
                  <th>ML ID</th>
                </tr>
              </thead>
              <tbody>
                {ventas.length === 0 ? (
                  <tr>
                    <td colSpan="13" className={styles.noData}>
                      No hay ventas en el período seleccionado
                    </td>
                  </tr>
                ) : (
                  ventas.map((venta) => (
                    <tr key={venta.ID_de_Operación}>
                      <td>{formatearFecha(venta.Fecha)}</td>
                      <td>{venta.ID_de_Operación}</td>
                      <td>{venta.Marca}</td>
                      <td>
                        <div className={styles.categoria}>
                          <div>{venta.Categoría}</div>
                          <div className={styles.subcategoria}>{venta.SubCategoría}</div>
                        </div>
                      </td>
                      <td className={styles.descripcion}>{venta.Descripción}</td>
                      <td className={styles.centrado}>{venta.Cantidad}</td>
                      <td className={styles.monto}>{formatearMoneda(venta.Monto_Unitario)}</td>
                      <td className={styles.monto}>{formatearMoneda(venta.Monto_Total)}</td>
                      <td className={styles.monto}>{formatearDolar(venta.Costo_sin_IVA)}</td>
                      <td className={styles.centrado}>{venta.IVA}%</td>
                      <td>{getTipoLogistica(venta.ML_logistic_type)}</td>
                      <td className={styles.monto}>{formatearMoneda(venta.MLShippmentCost4Seller || 0)}</td>
                      <td className={styles.centrado}>
                        <a
                          href={`https://www.mercadolibre.com.ar/ventas/${venta.ML_id}/detalle`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={styles.mlLink}
                        >
                          Ver
                        </a>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
