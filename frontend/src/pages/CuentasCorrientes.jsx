import { useState, useEffect, useCallback } from 'react';
import api from '../services/api';
import styles from './CuentasCorrientes.module.css';

const TABS = {
  proveedores: {
    label: 'Proveedores',
    endpoint: '/cuentas-corrientes/proveedores',
    idField: 'id_proveedor',
    nameField: 'proveedor',
    idLabel: 'ID Prov.',
    nameLabel: 'Proveedor',
    searchPlaceholder: 'Buscar proveedor...',
    countLabel: 'Proveedores',
  },
  clientes: {
    label: 'Clientes',
    endpoint: '/cuentas-corrientes/clientes',
    idField: 'id_cliente',
    nameField: 'cliente',
    idLabel: 'ID Cliente',
    nameLabel: 'Cliente',
    searchPlaceholder: 'Buscar cliente...',
    countLabel: 'Clientes',
  },
};

export default function CuentasCorrientes() {
  const [tab, setTab] = useState('proveedores');
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [buscar, setBuscar] = useState('');
  const [buscarInput, setBuscarInput] = useState('');
  const [sucursales, setSucursales] = useState([]);
  const [sucursalSeleccionada, setSucursalSeleccionada] = useState('');
  const [exportando, setExportando] = useState(false);

  const config = TABS[tab];

  // Cargar sucursales al montar
  useEffect(() => {
    const cargarSucursales = async () => {
      try {
        const response = await api.get('/cuentas-corrientes/sucursales');
        setSucursales(response.data || []);
      } catch (err) {
        console.error('Error cargando sucursales:', err);
      }
    };
    cargarSucursales();
  }, []);

  const cargarDatos = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = {};
      if (buscar) params.buscar = buscar;
      if (sucursalSeleccionada) params.sucursal = sucursalSeleccionada;

      const response = await api.get(config.endpoint, { params });
      setData(response.data?.data || []);
    } catch (err) {
      console.error('Error cargando cuentas corrientes:', err);
      const msg =
        err.response?.data?.error?.message ||
        'Error al cargar las cuentas corrientes';
      setError(msg);
      setData([]);
    } finally {
      setLoading(false);
    }
  }, [buscar, sucursalSeleccionada, config.endpoint]);

  useEffect(() => {
    cargarDatos();
  }, [cargarDatos]);

  const handleCambiarTab = (nuevoTab) => {
    if (nuevoTab === tab) return;
    setTab(nuevoTab);
    setBuscar('');
    setBuscarInput('');
    setSucursalSeleccionada('');
    setData([]);
  };

  const handleBuscar = (e) => {
    e.preventDefault();
    setBuscar(buscarInput);
  };

  const handleLimpiar = () => {
    setBuscarInput('');
    setBuscar('');
    setSucursalSeleccionada('');
  };

  const exportarExcel = async () => {
    setExportando(true);
    try {
      const params = { tipo: tab };
      if (buscar) params.buscar = buscar;
      if (sucursalSeleccionada) params.sucursal = sucursalSeleccionada;

      const response = await api.get('/cuentas-corrientes/exportar', {
        params,
        responseType: 'blob',
      });

      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', `cuentas_corrientes_${tab}.xlsx`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Error exportando:', err);
      setError('Error al exportar el archivo');
    } finally {
      setExportando(false);
    }
  };

  const formatearMoneda = (monto) => {
    return new Intl.NumberFormat('es-AR', {
      style: 'currency',
      currency: 'ARS',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(monto);
  };

  const calcularTotales = () => {
    return data.reduce(
      (acc, item) => {
        acc.montoTotal += item.monto_total || 0;
        acc.montoAbonado += item.monto_abonado || 0;
        acc.pendiente += item.pendiente || 0;
        return acc;
      },
      { montoTotal: 0, montoAbonado: 0, pendiente: 0 }
    );
  };

  const totales = calcularTotales();
  const hayFiltrosActivos = buscar || sucursalSeleccionada;

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1 className={styles.title}>Cuentas Corrientes</h1>
        <div className={styles.acciones}>
          <form onSubmit={handleBuscar} className={styles.buscador}>
            <input
              type="text"
              value={buscarInput}
              onChange={(e) => setBuscarInput(e.target.value)}
              placeholder={config.searchPlaceholder}
              className={styles.searchInput}
            />
            <button type="submit" className="btn-tesla outline-subtle-primary sm">
              Buscar
            </button>
          </form>
          <select
            value={sucursalSeleccionada}
            onChange={(e) => setSucursalSeleccionada(e.target.value)}
            className={styles.selectSucursal}
          >
            <option value="">Todas las sucursales</option>
            {sucursales.map((s) => (
              <option key={s.bra_id} value={s.bra_id}>
                {s.bra_desc}
              </option>
            ))}
          </select>
          {hayFiltrosActivos && (
            <button
              type="button"
              onClick={handleLimpiar}
              className="btn-tesla outline-subtle-danger sm"
            >
              Limpiar
            </button>
          )}
          <button
            onClick={cargarDatos}
            className="btn-tesla outline-subtle-primary sm"
            disabled={loading}
          >
            {loading ? 'Cargando...' : 'Actualizar'}
          </button>
          <button
            onClick={exportarExcel}
            className="btn-tesla outline-subtle-success sm"
            disabled={exportando || loading || data.length === 0}
          >
            {exportando ? 'Exportando...' : 'Exportar Excel'}
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className={styles.tabs}>
        {Object.entries(TABS).map(([key, t]) => (
          <button
            key={key}
            className={`${styles.tab} ${tab === key ? styles.tabActive : ''}`}
            onClick={() => handleCambiarTab(key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {error && <div className={styles.errorBanner}>{error}</div>}

      {loading ? (
        <div className={styles.loading}>Consultando ERP, puede demorar unos segundos...</div>
      ) : (
        <>
          <div className={styles.statsCard}>
            <div className={styles.statItem}>
              <div className={styles.statLabel}>{config.countLabel}</div>
              <div className={styles.statValue}>{data.length}</div>
            </div>
            <div className={styles.statItem}>
              <div className={styles.statLabel}>Monto Total</div>
              <div className={styles.statValue}>
                {formatearMoneda(totales.montoTotal)}
              </div>
            </div>
            <div className={styles.statItem}>
              <div className={styles.statLabel}>Abonado</div>
              <div className={`${styles.statValue} ${styles.success}`}>
                {formatearMoneda(totales.montoAbonado)}
              </div>
            </div>
            <div className={styles.statItem}>
              <div className={styles.statLabel}>Pendiente</div>
              <div className={`${styles.statValue} ${styles.danger}`}>
                {formatearMoneda(totales.pendiente)}
              </div>
            </div>
          </div>

          <div className={styles.tableWrapper}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Sucursal</th>
                  <th>{config.idLabel}</th>
                  <th>{config.nameLabel}</th>
                  <th>Monto Total</th>
                  <th>Abonado</th>
                  <th>Pendiente</th>
                </tr>
              </thead>
              <tbody>
                {data.length === 0 ? (
                  <tr>
                    <td colSpan="6" className={styles.noData}>
                      No se encontraron cuentas corrientes
                    </td>
                  </tr>
                ) : (
                  data.map((item) => (
                    <tr key={`${item.bra_id}-${item[config.idField]}`}>
                      <td>{item.sucursal}</td>
                      <td className={styles.centrado}>{item[config.idField]}</td>
                      <td>{item[config.nameField]}</td>
                      <td className={styles.monto}>
                        {formatearMoneda(item.monto_total)}
                      </td>
                      <td className={`${styles.monto} ${styles.success}`}>
                        {formatearMoneda(item.monto_abonado)}
                      </td>
                      <td
                        className={`${styles.monto} ${
                          item.pendiente > 0 ? styles.danger : ''
                        }`}
                      >
                        {formatearMoneda(item.pendiente)}
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
