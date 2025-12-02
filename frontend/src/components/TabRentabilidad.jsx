import { useState, useEffect } from 'react';
import api from '../api';
import styles from './TabRentabilidad.module.css';

export default function TabRentabilidad({ fechaDesde, fechaHasta }) {
  const [loading, setLoading] = useState(false);
  const [rentabilidad, setRentabilidad] = useState(null);
  const [filtrosDisponibles, setFiltrosDisponibles] = useState({
    marcas: [],
    categorias: [],
    subcategorias: []
  });

  // Filtros seleccionados (arrays para múltiple selección)
  const [marcasSeleccionadas, setMarcasSeleccionadas] = useState([]);
  const [categoriasSeleccionadas, setCategoriasSeleccionadas] = useState([]);
  const [subcategoriasSeleccionadas, setSubcategoriasSeleccionadas] = useState([]);

  // Modal de offsets
  const [mostrarModalOffset, setMostrarModalOffset] = useState(false);
  const [offsets, setOffsets] = useState([]);
  const [nuevoOffset, setNuevoOffset] = useState({
    tipo: 'marca',
    valor: '',
    monto: '',
    descripcion: '',
    fecha_desde: '',
    fecha_hasta: ''
  });

  useEffect(() => {
    if (fechaDesde && fechaHasta) {
      cargarFiltros();
      cargarRentabilidad();
    }
  }, [fechaDesde, fechaHasta]);

  useEffect(() => {
    if (fechaDesde && fechaHasta) {
      cargarRentabilidad();
    }
  }, [marcasSeleccionadas, categoriasSeleccionadas, subcategoriasSeleccionadas]);

  const cargarFiltros = async () => {
    try {
      const params = {
        fecha_desde: fechaDesde,
        fecha_hasta: fechaHasta
      };
      if (marcasSeleccionadas.length > 0) {
        params.marcas = marcasSeleccionadas.join(',');
      }
      if (categoriasSeleccionadas.length > 0) {
        params.categorias = categoriasSeleccionadas.join(',');
      }

      const response = await api.get('/api/rentabilidad/filtros', { params });
      setFiltrosDisponibles(response.data);
    } catch (error) {
      console.error('Error cargando filtros:', error);
    }
  };

  const cargarRentabilidad = async () => {
    setLoading(true);
    try {
      const params = {
        fecha_desde: fechaDesde,
        fecha_hasta: fechaHasta
      };
      if (marcasSeleccionadas.length > 0) {
        params.marcas = marcasSeleccionadas.join(',');
      }
      if (categoriasSeleccionadas.length > 0) {
        params.categorias = categoriasSeleccionadas.join(',');
      }
      if (subcategoriasSeleccionadas.length > 0) {
        params.subcategorias = subcategoriasSeleccionadas.join(',');
      }

      const response = await api.get('/api/rentabilidad', { params });
      setRentabilidad(response.data);
    } catch (error) {
      console.error('Error cargando rentabilidad:', error);
    } finally {
      setLoading(false);
    }
  };

  const cargarOffsets = async () => {
    try {
      const response = await api.get('/api/offsets-ganancia');
      setOffsets(response.data);
    } catch (error) {
      console.error('Error cargando offsets:', error);
    }
  };

  const toggleFiltro = (tipo, valor) => {
    if (tipo === 'marca') {
      setMarcasSeleccionadas(prev =>
        prev.includes(valor)
          ? prev.filter(m => m !== valor)
          : [...prev, valor]
      );
      // Limpiar filtros dependientes
      setCategoriasSeleccionadas([]);
      setSubcategoriasSeleccionadas([]);
    } else if (tipo === 'categoria') {
      setCategoriasSeleccionadas(prev =>
        prev.includes(valor)
          ? prev.filter(c => c !== valor)
          : [...prev, valor]
      );
      setSubcategoriasSeleccionadas([]);
    } else if (tipo === 'subcategoria') {
      setSubcategoriasSeleccionadas(prev =>
        prev.includes(valor)
          ? prev.filter(s => s !== valor)
          : [...prev, valor]
      );
    }
  };

  const limpiarFiltros = () => {
    setMarcasSeleccionadas([]);
    setCategoriasSeleccionadas([]);
    setSubcategoriasSeleccionadas([]);
  };

  const formatMoney = (valor) => {
    if (valor === null || valor === undefined) return '$0';
    return new Intl.NumberFormat('es-AR', {
      style: 'currency',
      currency: 'ARS',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0
    }).format(valor);
  };

  const formatPercent = (valor) => {
    if (valor === null || valor === undefined) return '0%';
    return `${valor.toFixed(2)}%`;
  };

  const getMarkupColor = (markup) => {
    if (markup < 0) return '#ef4444';
    if (markup < 3) return '#f59e0b';
    if (markup < 6) return '#eab308';
    return '#22c55e';
  };

  const guardarOffset = async () => {
    try {
      const payload = {
        monto: parseFloat(nuevoOffset.monto),
        descripcion: nuevoOffset.descripcion,
        fecha_desde: nuevoOffset.fecha_desde,
        fecha_hasta: nuevoOffset.fecha_hasta || null
      };

      if (nuevoOffset.tipo === 'marca') {
        payload.marca = nuevoOffset.valor;
      } else if (nuevoOffset.tipo === 'categoria') {
        payload.categoria = nuevoOffset.valor;
      } else if (nuevoOffset.tipo === 'subcategoria') {
        payload.subcategoria_id = parseInt(nuevoOffset.valor);
      } else if (nuevoOffset.tipo === 'producto') {
        payload.item_id = parseInt(nuevoOffset.valor);
      }

      await api.post('/api/offsets-ganancia', payload);
      setMostrarModalOffset(false);
      setNuevoOffset({
        tipo: 'marca',
        valor: '',
        monto: '',
        descripcion: '',
        fecha_desde: '',
        fecha_hasta: ''
      });
      cargarRentabilidad();
      cargarOffsets();
    } catch (error) {
      console.error('Error guardando offset:', error);
      alert('Error al guardar el offset');
    }
  };

  const eliminarOffset = async (id) => {
    if (!confirm('¿Eliminar este offset?')) return;
    try {
      await api.delete(`/api/offsets-ganancia/${id}`);
      cargarRentabilidad();
      cargarOffsets();
    } catch (error) {
      console.error('Error eliminando offset:', error);
    }
  };

  return (
    <div className={styles.container}>
      {/* Filtros múltiples */}
      <div className={styles.filtrosContainer}>
        <div className={styles.filtroGrupo}>
          <label>Marcas:</label>
          <div className={styles.chipContainer}>
            {filtrosDisponibles.marcas.map(marca => (
              <button
                key={marca}
                className={`${styles.chip} ${marcasSeleccionadas.includes(marca) ? styles.chipActivo : ''}`}
                onClick={() => toggleFiltro('marca', marca)}
              >
                {marca}
              </button>
            ))}
          </div>
        </div>

        {marcasSeleccionadas.length > 0 && filtrosDisponibles.categorias.length > 0 && (
          <div className={styles.filtroGrupo}>
            <label>Categorías:</label>
            <div className={styles.chipContainer}>
              {filtrosDisponibles.categorias.map(cat => (
                <button
                  key={cat}
                  className={`${styles.chip} ${categoriasSeleccionadas.includes(cat) ? styles.chipActivo : ''}`}
                  onClick={() => toggleFiltro('categoria', cat)}
                >
                  {cat}
                </button>
              ))}
            </div>
          </div>
        )}

        {categoriasSeleccionadas.length > 0 && filtrosDisponibles.subcategorias.length > 0 && (
          <div className={styles.filtroGrupo}>
            <label>Subcategorías:</label>
            <div className={styles.chipContainer}>
              {filtrosDisponibles.subcategorias.map(subcat => (
                <button
                  key={subcat}
                  className={`${styles.chip} ${subcategoriasSeleccionadas.includes(subcat) ? styles.chipActivo : ''}`}
                  onClick={() => toggleFiltro('subcategoria', subcat)}
                >
                  {subcat}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className={styles.filtroAcciones}>
          {(marcasSeleccionadas.length > 0 || categoriasSeleccionadas.length > 0) && (
            <button onClick={limpiarFiltros} className={styles.btnLimpiar}>
              ✕ Limpiar filtros
            </button>
          )}
          <button
            onClick={() => {
              cargarOffsets();
              setMostrarModalOffset(true);
            }}
            className={styles.btnOffset}
          >
            💰 Gestionar Offsets
          </button>
        </div>
      </div>

      {loading ? (
        <div className={styles.loading}>Cargando rentabilidad...</div>
      ) : rentabilidad ? (
        <>
          {/* Card de totales */}
          <div className={styles.totalCard}>
            <h3>Total del período</h3>
            <div className={styles.totalGrid}>
              <div className={styles.totalItem}>
                <span className={styles.totalLabel}>Ventas</span>
                <span className={styles.totalValor}>{rentabilidad.totales.total_ventas}</span>
              </div>
              <div className={styles.totalItem}>
                <span className={styles.totalLabel}>Monto Vendido</span>
                <span className={styles.totalValor}>{formatMoney(rentabilidad.totales.monto_venta)}</span>
              </div>
              <div className={styles.totalItem}>
                <span className={styles.totalLabel}>Limpio</span>
                <span className={styles.totalValor}>{formatMoney(rentabilidad.totales.monto_limpio)}</span>
              </div>
              <div className={styles.totalItem}>
                <span className={styles.totalLabel}>Costo</span>
                <span className={styles.totalValor}>{formatMoney(rentabilidad.totales.costo_total)}</span>
              </div>
              <div className={styles.totalItem}>
                <span className={styles.totalLabel}>Ganancia</span>
                <span className={styles.totalValor} style={{ color: rentabilidad.totales.ganancia >= 0 ? '#22c55e' : '#ef4444' }}>
                  {formatMoney(rentabilidad.totales.ganancia)}
                </span>
              </div>
              <div className={styles.totalItem}>
                <span className={styles.totalLabel}>Markup</span>
                <span className={styles.totalValor} style={{ color: getMarkupColor(rentabilidad.totales.markup_promedio) }}>
                  {formatPercent(rentabilidad.totales.markup_promedio)}
                </span>
              </div>
              {rentabilidad.totales.offset_total > 0 && (
                <>
                  <div className={styles.totalItem}>
                    <span className={styles.totalLabel}>+ Offsets</span>
                    <span className={styles.totalValor} style={{ color: '#3b82f6' }}>
                      {formatMoney(rentabilidad.totales.offset_total)}
                    </span>
                  </div>
                  <div className={styles.totalItem}>
                    <span className={styles.totalLabel}>Ganancia c/Offset</span>
                    <span className={styles.totalValor} style={{ color: rentabilidad.totales.ganancia_con_offset >= 0 ? '#22c55e' : '#ef4444' }}>
                      {formatMoney(rentabilidad.totales.ganancia_con_offset)}
                    </span>
                  </div>
                  <div className={styles.totalItem}>
                    <span className={styles.totalLabel}>Markup c/Offset</span>
                    <span className={styles.totalValor} style={{ color: getMarkupColor(rentabilidad.totales.markup_con_offset) }}>
                      {formatPercent(rentabilidad.totales.markup_con_offset)}
                    </span>
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Cards por grupo */}
          <div className={styles.cardsGrid}>
            {rentabilidad.cards.map((card, index) => (
              <div key={index} className={styles.card}>
                <div className={styles.cardHeader}>
                  <h4 className={styles.cardTitulo}>{card.nombre || 'Sin nombre'}</h4>
                  <span className={styles.cardTipo}>{card.tipo}</span>
                </div>
                <div className={styles.cardBody}>
                  <div className={styles.cardMetrica}>
                    <span>Ventas:</span>
                    <span>{card.total_ventas}</span>
                  </div>
                  <div className={styles.cardMetrica}>
                    <span>Monto:</span>
                    <span>{formatMoney(card.monto_venta)}</span>
                  </div>
                  <div className={styles.cardMetrica}>
                    <span>Limpio:</span>
                    <span>{formatMoney(card.monto_limpio)}</span>
                  </div>
                  <div className={styles.cardMetrica}>
                    <span>Costo:</span>
                    <span>{formatMoney(card.costo_total)}</span>
                  </div>
                  <div className={styles.cardMetrica}>
                    <span>Ganancia:</span>
                    <span style={{ color: card.ganancia >= 0 ? '#22c55e' : '#ef4444' }}>
                      {formatMoney(card.ganancia)}
                    </span>
                  </div>
                  <div className={styles.cardMetrica}>
                    <span>Markup:</span>
                    <span style={{ color: getMarkupColor(card.markup_promedio) }}>
                      {formatPercent(card.markup_promedio)}
                    </span>
                  </div>
                  {card.offset_total > 0 && (
                    <>
                      <div className={styles.cardMetricaOffset}>
                        <span>+ Offset:</span>
                        <span style={{ color: '#3b82f6' }}>{formatMoney(card.offset_total)}</span>
                      </div>
                      <div className={styles.cardMetricaOffset}>
                        <span>Markup c/Off:</span>
                        <span style={{ color: getMarkupColor(card.markup_con_offset) }}>
                          {formatPercent(card.markup_con_offset)}
                        </span>
                      </div>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        </>
      ) : (
        <div className={styles.empty}>No hay datos para el período seleccionado</div>
      )}

      {/* Modal de Offsets */}
      {mostrarModalOffset && (
        <div className={styles.modalOverlay} onClick={() => setMostrarModalOffset(false)}>
          <div className={styles.modal} onClick={e => e.stopPropagation()}>
            <h3>Gestionar Offsets de Ganancia</h3>

            <div className={styles.offsetForm}>
              <h4>Nuevo Offset</h4>
              <div className={styles.formRow}>
                <select
                  value={nuevoOffset.tipo}
                  onChange={e => setNuevoOffset({ ...nuevoOffset, tipo: e.target.value, valor: '' })}
                >
                  <option value="marca">Por Marca</option>
                  <option value="categoria">Por Categoría</option>
                  <option value="subcategoria">Por Subcategoría</option>
                  <option value="producto">Por Producto (item_id)</option>
                </select>
                <input
                  type="text"
                  placeholder={nuevoOffset.tipo === 'producto' ? 'Item ID' : `Nombre de ${nuevoOffset.tipo}`}
                  value={nuevoOffset.valor}
                  onChange={e => setNuevoOffset({ ...nuevoOffset, valor: e.target.value })}
                />
              </div>
              <div className={styles.formRow}>
                <input
                  type="number"
                  placeholder="Monto ($)"
                  value={nuevoOffset.monto}
                  onChange={e => setNuevoOffset({ ...nuevoOffset, monto: e.target.value })}
                />
                <input
                  type="text"
                  placeholder="Descripción (ej: Rebate Q4)"
                  value={nuevoOffset.descripcion}
                  onChange={e => setNuevoOffset({ ...nuevoOffset, descripcion: e.target.value })}
                />
              </div>
              <div className={styles.formRow}>
                <div>
                  <label>Desde:</label>
                  <input
                    type="date"
                    value={nuevoOffset.fecha_desde}
                    onChange={e => setNuevoOffset({ ...nuevoOffset, fecha_desde: e.target.value })}
                  />
                </div>
                <div>
                  <label>Hasta (opcional):</label>
                  <input
                    type="date"
                    value={nuevoOffset.fecha_hasta}
                    onChange={e => setNuevoOffset({ ...nuevoOffset, fecha_hasta: e.target.value })}
                  />
                </div>
              </div>
              <button onClick={guardarOffset} className={styles.btnGuardar}>
                Guardar Offset
              </button>
            </div>

            <div className={styles.offsetsLista}>
              <h4>Offsets existentes</h4>
              {offsets.length === 0 ? (
                <p>No hay offsets configurados</p>
              ) : (
                <table className={styles.offsetsTable}>
                  <thead>
                    <tr>
                      <th>Nivel</th>
                      <th>Valor</th>
                      <th>Monto</th>
                      <th>Descripción</th>
                      <th>Período</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {offsets.map(offset => (
                      <tr key={offset.id}>
                        <td>
                          {offset.item_id ? 'Producto' :
                           offset.subcategoria_id ? 'Subcategoría' :
                           offset.categoria ? 'Categoría' : 'Marca'}
                        </td>
                        <td>
                          {offset.item_id || offset.subcategoria_id || offset.categoria || offset.marca}
                        </td>
                        <td>{formatMoney(offset.monto)}</td>
                        <td>{offset.descripcion}</td>
                        <td>
                          {offset.fecha_desde}
                          {offset.fecha_hasta ? ` a ${offset.fecha_hasta}` : ' en adelante'}
                        </td>
                        <td>
                          <button
                            onClick={() => eliminarOffset(offset.id)}
                            className={styles.btnEliminar}
                          >
                            🗑️
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <button onClick={() => setMostrarModalOffset(false)} className={styles.btnCerrar}>
              Cerrar
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
