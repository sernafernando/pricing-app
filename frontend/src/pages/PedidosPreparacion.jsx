import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import styles from './PedidosPreparacion.module.css';

const API_URL = 'https://pricing.gaussonline.com.ar/api';

export default function PedidosPreparacion() {
  const [vista, setVista] = useState('detalle'); // 'detalle' o 'resumen'
  const [pedidos, setPedidos] = useState([]);
  const [resumen, setResumen] = useState([]);
  const [estadisticas, setEstadisticas] = useState(null);
  const [filtros, setFiltros] = useState(null);
  const [loading, setLoading] = useState(true);

  // Filtros
  const [marcaId, setMarcaId] = useState('');
  const [categoriaId, setCategoriaId] = useState('');
  const [tipoEnvio, setTipoEnvio] = useState('');
  const [search, setSearch] = useState('');
  const [soloPendientes, setSoloPendientes] = useState(false);

  const getToken = () => localStorage.getItem('token');

  const cargarFiltros = useCallback(async () => {
    try {
      const response = await axios.get(`${API_URL}/pedidos-preparacion/filtros`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      setFiltros(response.data);
    } catch (error) {
      console.error('Error cargando filtros:', error);
    }
  }, []);

  const cargarEstadisticas = useCallback(async () => {
    try {
      const response = await axios.get(`${API_URL}/pedidos-preparacion/estadisticas`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      });
      setEstadisticas(response.data);
    } catch (error) {
      console.error('Error cargando estadísticas:', error);
    }
  }, []);

  const cargarDatos = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (marcaId) params.append('marca_id', marcaId);
      if (categoriaId) params.append('categoria_id', categoriaId);
      if (tipoEnvio) params.append('logistic_type', tipoEnvio);
      if (search) params.append('search', search);
      if (soloPendientes) params.append('solo_pendientes', 'true');

      if (vista === 'detalle') {
        const response = await axios.get(`${API_URL}/pedidos-preparacion/detalle?${params}`, {
          headers: { Authorization: `Bearer ${getToken()}` }
        });
        setPedidos(response.data);
      } else {
        const response = await axios.get(`${API_URL}/pedidos-preparacion/resumen?${params}`, {
          headers: { Authorization: `Bearer ${getToken()}` }
        });
        setResumen(response.data);
      }
    } catch (error) {
      console.error('Error cargando datos:', error);
    } finally {
      setLoading(false);
    }
  }, [vista, marcaId, categoriaId, tipoEnvio, search, soloPendientes]);

  useEffect(() => {
    cargarFiltros();
    cargarEstadisticas();
  }, [cargarFiltros, cargarEstadisticas]);

  useEffect(() => {
    cargarDatos();
  }, [cargarDatos]);

  const formatearFecha = (fecha) => {
    if (!fecha) return '-';
    const date = new Date(fecha);
    const hoy = new Date();
    const esHoy = date.toDateString() === hoy.toDateString();

    const hora = date.toLocaleTimeString('es-AR', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    });

    if (esHoy) return `Hoy ${hora}`;

    return date.toLocaleDateString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    });
  };

  const getBadgeClass = (tipo) => {
    switch (tipo?.toLowerCase()) {
      case 'turbo': return styles.badgeTurbo;
      case 'self_service': return styles.badgeSelfService;
      case 'cross_docking': return styles.badgeCrossDocking;
      case 'drop_off': return styles.badgeDropOff;
      case 'xd_drop_off': return styles.badgeXdDropOff;
      default: return styles.badgeDefault;
    }
  };

  const getEstadoBadge = (estado) => {
    if (estado === 20) return { text: 'Pendiente', class: styles.estadoPendiente };
    return { text: 'Ready to Ship', class: styles.estadoReady };
  };

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1 className={styles.title}>📦 Pedidos en Preparación</h1>
        <button onClick={cargarDatos} className={styles.refreshBtn}>
          🔄 Actualizar
        </button>
      </div>

      {/* Estadísticas */}
      {estadisticas && (
        <div className={styles.statsGrid}>
          <div className={styles.statCard}>
            <div className={styles.statValue}>{estadisticas.total_pedidos}</div>
            <div className={styles.statLabel}>Pedidos</div>
          </div>
          <div className={styles.statCard}>
            <div className={styles.statValue}>{Math.round(estadisticas.total_unidades)}</div>
            <div className={styles.statLabel}>Unidades</div>
          </div>
          {estadisticas.por_tipo_envio?.map((tipo) => (
            <div key={tipo.tipo} className={styles.statCard}>
              <div className={styles.statValue}>{tipo.pedidos}</div>
              <div className={styles.statLabel}>{tipo.tipo}</div>
              <div className={styles.statSub}>{Math.round(tipo.unidades)} uds</div>
            </div>
          ))}
        </div>
      )}

      {/* Filtros */}
      <div className={styles.filtrosContainer}>
        <div className={styles.filtrosRow}>
          <select
            value={marcaId}
            onChange={(e) => setMarcaId(e.target.value)}
            className={styles.select}
          >
            <option value="">Todas las marcas</option>
            {filtros?.marcas?.map((m) => (
              <option key={m.id} value={m.id}>{m.nombre}</option>
            ))}
          </select>

          <select
            value={categoriaId}
            onChange={(e) => setCategoriaId(e.target.value)}
            className={styles.select}
          >
            <option value="">Todas las categorías</option>
            {filtros?.categorias?.map((c) => (
              <option key={c.id} value={c.id}>{c.nombre}</option>
            ))}
          </select>

          <select
            value={tipoEnvio}
            onChange={(e) => setTipoEnvio(e.target.value)}
            className={styles.select}
          >
            <option value="">Todos los envíos</option>
            <option value="Turbo">Turbo</option>
            {filtros?.tipos_envio?.filter(t => t !== 'Turbo').map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>

          <input
            type="text"
            placeholder="Buscar código, descripción, cliente..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={styles.searchInput}
          />

          <label className={styles.checkboxLabel}>
            <input
              type="checkbox"
              checked={soloPendientes}
              onChange={(e) => setSoloPendientes(e.target.checked)}
            />
            Solo pendientes (20)
          </label>
        </div>

        <div className={styles.vistaToggle}>
          <button
            className={`${styles.vistaBtn} ${vista === 'detalle' ? styles.vistaActiva : ''}`}
            onClick={() => setVista('detalle')}
          >
            📋 Detalle
          </button>
          <button
            className={`${styles.vistaBtn} ${vista === 'resumen' ? styles.vistaActiva : ''}`}
            onClick={() => setVista('resumen')}
          >
            📊 Resumen
          </button>
        </div>
      </div>

      {/* Contenido */}
      {loading ? (
        <div className={styles.loading}>Cargando pedidos...</div>
      ) : vista === 'detalle' ? (
        <div className={styles.tableContainer}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Estado</th>
                <th>Producto</th>
                <th>Cant</th>
                <th>Tipo Envío</th>
                <th>Cliente</th>
                <th>Dirección</th>
                <th>Fecha Límite</th>
                <th>Tracking</th>
              </tr>
            </thead>
            <tbody>
              {pedidos.length === 0 ? (
                <tr>
                  <td colSpan={8} className={styles.empty}>No hay pedidos en preparación</td>
                </tr>
              ) : (
                pedidos.map((p, idx) => {
                  const estadoInfo = getEstadoBadge(p.estado_orden);
                  return (
                    <tr key={`${p.mlo_id}-${p.item_id}-${idx}`}>
                      <td>
                        <span className={`${styles.badge} ${estadoInfo.class}`}>
                          {estadoInfo.text}
                        </span>
                      </td>
                      <td>
                        <div className={styles.producto}>
                          <strong>{p.item_code || '-'}</strong>
                          <span className={styles.descripcion}>
                            {p.item_desc || p.mlo_title || '-'}
                          </span>
                          {p.marca && <small className={styles.marca}>{p.marca}</small>}
                        </div>
                      </td>
                      <td className={styles.cantidad}>{p.cantidad}</td>
                      <td>
                        <span className={`${styles.badge} ${getBadgeClass(p.logistic_type)}`}>
                          {p.logistic_type}
                        </span>
                      </td>
                      <td>
                        <div className={styles.cliente}>
                          <strong>{p.cliente_nombre || '-'}</strong>
                          <small>{p.cliente_telefono || p.cliente_email || ''}</small>
                        </div>
                      </td>
                      <td>
                        <div className={styles.direccion}>
                          <span>{p.direccion || '-'}</span>
                          <small>{p.ciudad}, {p.provincia} {p.codigo_postal}</small>
                        </div>
                      </td>
                      <td className={styles.fecha}>
                        {formatearFecha(p.fecha_limite_despacho)}
                      </td>
                      <td className={styles.tracking}>
                        {p.tracking_number || '-'}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      ) : (
        <div className={styles.tableContainer}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Producto</th>
                <th>Cantidad Total</th>
                <th>Paquetes</th>
                <th>Tipo Envío</th>
                <th>Marca</th>
                <th>Categoría</th>
              </tr>
            </thead>
            <tbody>
              {resumen.length === 0 ? (
                <tr>
                  <td colSpan={6} className={styles.empty}>No hay datos para mostrar</td>
                </tr>
              ) : (
                resumen.map((r, idx) => (
                  <tr key={`${r.item_id}-${r.logistic_type}-${idx}`}>
                    <td>
                      <div className={styles.producto}>
                        <strong>{r.item_code || '-'}</strong>
                        <span className={styles.descripcion}>{r.item_desc || '-'}</span>
                      </div>
                    </td>
                    <td className={styles.cantidadGrande}>{r.cantidad_total}</td>
                    <td className={styles.cantidad}>{r.cantidad_paquetes}</td>
                    <td>
                      <span className={`${styles.badge} ${getBadgeClass(r.logistic_type)}`}>
                        {r.logistic_type}
                      </span>
                    </td>
                    <td>{r.marca || '-'}</td>
                    <td>{r.categoria || '-'}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Contador de resultados */}
      <div className={styles.footer}>
        {vista === 'detalle' ? (
          <span>Mostrando {pedidos.length} pedidos</span>
        ) : (
          <span>Mostrando {resumen.length} productos</span>
        )}
      </div>
    </div>
  );
}
