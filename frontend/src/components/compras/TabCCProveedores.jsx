import { useCallback, useEffect, useState } from 'react';
import { Search, Loader2, Layers, List, DollarSign } from 'lucide-react';
import api from '../../services/api';
import useCCProveedor from '../../hooks/useCCProveedor';
import styles from './TabCCProveedores.module.css';

const formatMoneda = (value, moneda = 'ARS') => {
  const num = Number(value) || 0;
  const prefix = moneda === 'USD' ? 'US$' : '$';
  return `${prefix}${num.toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

const formatDate = (isoStr) => {
  if (!isoStr) return '';
  try {
    const d = new Date(isoStr);
    return d.toLocaleDateString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    });
  } catch {
    return isoStr;
  }
};

export default function TabCCProveedores() {
  // Desestructurar funciones memoizadas para evitar loop en useEffect/useCallback.
  // El objeto `ccApi` se recrea en cada render; las funciones internas son estables.
  const {
    obtenerDetalle,
    obtenerPorPedido,
    loading: ccLoading,
    error: ccError,
  } = useCCProveedor();

  const [proveedorIdInput, setProveedorIdInput] = useState('');
  const [proveedorIdActivo, setProveedorIdActivo] = useState(null);

  const [filtroEmpresa, setFiltroEmpresa] = useState('');
  const [filtroHasta, setFiltroHasta] = useState('');
  const [view, setView] = useState('cronologico'); // 'cronologico' | 'por-pedido'

  const [empresas, setEmpresas] = useState([]);

  const [detalle, setDetalle] = useState(null);
  const [porPedido, setPorPedido] = useState([]);
  const [tcEstimado, setTcEstimado] = useState(null);

  const fetchEmpresas = useCallback(async () => {
    try {
      const { data } = await api.get('/empresas');
      setEmpresas(data || []);
    } catch {
      setEmpresas([]);
    }
  }, []);

  useEffect(() => {
    fetchEmpresas();
  }, [fetchEmpresas]);

  const fetchTcDelDia = useCallback(async () => {
    // No es bloqueante — si no existe el endpoint, dejamos null.
    try {
      const { data } = await api.get('/tipo-cambio/actual');
      if (data?.tipo_cambio) setTcEstimado(Number(data.tipo_cambio));
    } catch {
      setTcEstimado(null);
    }
  }, []);

  useEffect(() => {
    fetchTcDelDia();
  }, [fetchTcDelDia]);

  const fetchDetalle = useCallback(async () => {
    if (!proveedorIdActivo) return;
    const params = {};
    if (filtroEmpresa) params.empresa_id = filtroEmpresa;
    if (filtroHasta) params.hasta_fecha = filtroHasta;
    try {
      const data = await obtenerDetalle(proveedorIdActivo, params);
      setDetalle(data);
    } catch {
      setDetalle(null);
    }
  }, [obtenerDetalle, proveedorIdActivo, filtroEmpresa, filtroHasta]);

  const fetchPorPedido = useCallback(async () => {
    if (!proveedorIdActivo) return;
    try {
      const data = await obtenerPorPedido(proveedorIdActivo);
      setPorPedido(data || []);
    } catch {
      setPorPedido([]);
    }
  }, [obtenerPorPedido, proveedorIdActivo]);

  useEffect(() => {
    if (proveedorIdActivo) {
      fetchDetalle();
      fetchPorPedido();
    }
  }, [proveedorIdActivo, fetchDetalle, fetchPorPedido]);

  useEffect(() => {
    if (proveedorIdActivo) fetchDetalle();
  }, [filtroEmpresa, filtroHasta, fetchDetalle, proveedorIdActivo]);

  const handleBuscar = (e) => {
    e.preventDefault();
    const id = Number(proveedorIdInput);
    if (Number.isFinite(id) && id > 0) {
      setProveedorIdActivo(id);
    }
  };

  const saldos = detalle?.saldos || [];
  const saldoUsd = saldos.find((s) => s.moneda === 'USD')?.saldo || 0;
  const saldoArs = saldos.find((s) => s.moneda === 'ARS')?.saldo || 0;
  const consolidadoArs =
    tcEstimado && Number(saldoUsd) !== 0
      ? Number(saldoArs) + Number(saldoUsd) * tcEstimado
      : null;

  return (
    <div className={styles.container}>
      {/* Buscador */}
      <form className={styles.searchBar} onSubmit={handleBuscar}>
        <div className={styles.searchWrapper}>
          <Search size={14} className={styles.searchIcon} />
          <input
            type="number"
            className={styles.searchInput}
            placeholder="ID de proveedor..."
            value={proveedorIdInput}
            onChange={(e) => setProveedorIdInput(e.target.value)}
          />
        </div>
        <select
          className={styles.select}
          value={filtroEmpresa}
          onChange={(e) => setFiltroEmpresa(e.target.value)}
        >
          <option value="">Todas las empresas</option>
          {empresas.map((emp) => (
            <option key={emp.id} value={emp.id}>
              {emp.nombre}
            </option>
          ))}
        </select>
        <input
          type="date"
          className={styles.input}
          value={filtroHasta}
          onChange={(e) => setFiltroHasta(e.target.value)}
          title="Hasta fecha"
        />
        <button type="submit" className={styles.btnPrimary}>
          Buscar
        </button>
      </form>

      {ccError && <div className={styles.errorBanner}>{ccError}</div>}

      {!proveedorIdActivo ? (
        <div className={styles.emptyState}>
          Ingresá el ID del proveedor para ver su cuenta corriente.
        </div>
      ) : ccLoading && !detalle ? (
        <div className={styles.centered}>
          <Loader2 size={20} className={styles.spin} /> Cargando CC...
        </div>
      ) : !detalle ? (
        <div className={styles.emptyState}>Sin datos para este proveedor.</div>
      ) : (
        <>
          {/* Header con nombre */}
          <div className={styles.proveedorHeader}>
            <h2 className={styles.proveedorNombre}>{detalle.nombre_proveedor}</h2>
            <span className={styles.proveedorId}>ID #{detalle.proveedor_id}</span>
          </div>

          {/* Cards saldos por moneda (FUENTE DE VERDAD) */}
          <div className={styles.saldosGrid}>
            <div className={styles.saldoCard}>
              <div className={styles.saldoLabel}>
                <DollarSign size={14} /> Saldo ARS
              </div>
              <div className={styles.saldoValue}>{formatMoneda(saldoArs, 'ARS')}</div>
              <div className={styles.saldoMeta}>
                {saldos.find((s) => s.moneda === 'ARS')?.movimientos_count || 0} movs
              </div>
            </div>
            <div className={styles.saldoCard}>
              <div className={styles.saldoLabel}>
                <DollarSign size={14} /> Saldo USD
              </div>
              <div className={styles.saldoValue}>{formatMoneda(saldoUsd, 'USD')}</div>
              <div className={styles.saldoMeta}>
                {saldos.find((s) => s.moneda === 'USD')?.movimientos_count || 0} movs
              </div>
            </div>
            <div className={styles.saldoCardSecondary}>
              <div className={styles.saldoLabel}>Estimado consolidado (ARS)</div>
              <div className={styles.saldoValueSecondary}>
                {consolidadoArs !== null
                  ? formatMoneda(consolidadoArs, 'ARS')
                  : 'TC no disponible'}
              </div>
              <div className={styles.saldoMetaWarning}>
                Estimado. Fuente de verdad: saldos por moneda.
              </div>
            </div>
          </div>

          {/* View switcher */}
          <div className={styles.viewSwitcher}>
            <button
              className={view === 'cronologico' ? styles.viewBtnActive : styles.viewBtn}
              onClick={() => setView('cronologico')}
            >
              <List size={14} /> Cronológico
            </button>
            <button
              className={view === 'por-pedido' ? styles.viewBtnActive : styles.viewBtn}
              onClick={() => setView('por-pedido')}
            >
              <Layers size={14} /> Agrupado por pedido
            </button>
          </div>

          {/* Vistas */}
          {view === 'cronologico' ? (
            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Fecha</th>
                    <th>Tipo</th>
                    <th>Origen</th>
                    <th>Descripción</th>
                    <th className={styles.thRight}>Monto</th>
                    <th>Moneda</th>
                  </tr>
                </thead>
                <tbody>
                  {(detalle.movimientos || []).length === 0 ? (
                    <tr>
                      <td colSpan={6} className={styles.emptyState}>
                        Sin movimientos en este periodo.
                      </td>
                    </tr>
                  ) : (
                    detalle.movimientos.map((m) => (
                      <tr key={m.id}>
                        <td className={styles.tdSecondary}>{formatDate(m.fecha_movimiento)}</td>
                        <td>
                          <span
                            className={
                              m.tipo === 'debe'
                                ? styles.badgeDebe
                                : m.tipo === 'haber'
                                ? styles.badgeHaber
                                : styles.badgeAjuste
                            }
                          >
                            {m.tipo}
                          </span>
                        </td>
                        <td className={styles.tdSecondary}>
                          {m.origen_tipo}
                          {m.origen_id ? ` #${m.origen_id}` : ''}
                        </td>
                        <td>{m.descripcion || '—'}</td>
                        <td className={styles.tdRight}>{formatMoneda(m.monto, m.moneda)}</td>
                        <td>{m.moneda}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          ) : (
            <div className={styles.grupoList}>
              {porPedido.length === 0 ? (
                <div className={styles.emptyState}>Sin pedidos con movimientos CC.</div>
              ) : (
                porPedido.map((g) => (
                  <div key={g.pedido_compra_id} className={styles.grupoCard}>
                    <div className={styles.grupoHeader}>
                      <div>
                        <strong>{g.pedido_numero}</strong>
                        <span className={styles.grupoEstado}>{g.pedido_estado}</span>
                      </div>
                      <div className={styles.grupoMonto}>
                        {formatMoneda(g.pedido_monto, g.pedido_moneda)}
                      </div>
                    </div>
                    <div className={styles.grupoMovs}>
                      {g.movimientos.map((m) => (
                        <div key={m.id} className={styles.grupoMovRow}>
                          <span>{formatDate(m.fecha_movimiento)}</span>
                          <span className={styles.tdSecondary}>{m.tipo}</span>
                          <span>{formatMoneda(m.monto, m.moneda)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
