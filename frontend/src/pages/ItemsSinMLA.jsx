import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './ItemsSinMLA.css';

const ItemsSinMLA = () => {
  const [activeTab, setActiveTab] = useState('sin-mla'); // 'sin-mla' | 'banlist'

  // Estado para items sin MLA
  const [itemsSinMLA, setItemsSinMLA] = useState([]);
  const [loadingItems, setLoadingItems] = useState(false);

  // Estado para items baneados
  const [itemsBaneados, setItemsBaneados] = useState([]);
  const [loadingBaneados, setLoadingBaneados] = useState(false);

  // Filtros
  const [marcas, setMarcas] = useState([]);
  const [marcaFiltro, setMarcaFiltro] = useState('');
  const [busqueda, setBusqueda] = useState('');
  const [listaPrecioFiltro, setListaPrecioFiltro] = useState('');
  const [listasPrecio, setListasPrecio] = useState([]);
  const [conStock, setConStock] = useState(null); // null = todos, true = con stock, false = sin stock

  // Estado para agregar motivo al banear
  const [itemSeleccionado, setItemSeleccionado] = useState(null);
  const [showMotivoModal, setShowMotivoModal] = useState(false);
  const [motivo, setMotivo] = useState('');

  // Estado para ordenamiento
  const [sortColumn, setSortColumn] = useState(null);
  const [sortDirection, setSortDirection] = useState('asc'); // 'asc' | 'desc'

  const API_URL = 'https://pricing.gaussonline.com.ar/api';
  const token = localStorage.getItem('token');

  useEffect(() => {
    cargarMarcas();
    cargarListasPrecio();
    cargarItemsSinMLA();
  }, []);

  useEffect(() => {
    if (activeTab === 'banlist') {
      cargarItemsBaneados();
    }
  }, [activeTab]);

  const cargarMarcas = async () => {
    try {
      const response = await axios.get(`${API_URL}/items-sin-mla/marcas`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setMarcas(response.data);
    } catch (error) {
      console.error('Error al cargar marcas:', error);
    }
  };

  const cargarListasPrecio = async () => {
    try {
      const response = await axios.get(`${API_URL}/items-sin-mla/listas-precios`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setListasPrecio(response.data);
    } catch (error) {
      console.error('Error al cargar listas de precios:', error);
    }
  };

  const cargarItemsSinMLA = async () => {
    setLoadingItems(true);
    try {
      const params = {};
      if (marcaFiltro) params.marca = marcaFiltro;
      if (busqueda) params.buscar = busqueda;
      if (listaPrecioFiltro) params.prli_id = listaPrecioFiltro;
      if (conStock !== null) params.con_stock = conStock;

      const response = await axios.get(`${API_URL}/items-sin-mla/items-sin-mla`, {
        headers: { Authorization: `Bearer ${token}` },
        params
      });
      setItemsSinMLA(response.data);
    } catch (error) {
      console.error('Error al cargar items sin MLA:', error);
      alert('Error al cargar items sin MLA');
    } finally {
      setLoadingItems(false);
    }
  };

  const cargarItemsBaneados = async () => {
    setLoadingBaneados(true);
    try {
      const response = await axios.get(`${API_URL}/items-sin-mla/items-baneados`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setItemsBaneados(response.data);
    } catch (error) {
      console.error('Error al cargar items baneados:', error);
      alert('Error al cargar items baneados');
    } finally {
      setLoadingBaneados(false);
    }
  };

  const handleBanear = (item) => {
    setItemSeleccionado(item);
    setMotivo('');
    setShowMotivoModal(true);
  };

  const confirmarBanear = async () => {
    if (!itemSeleccionado) return;

    try {
      await axios.post(
        `${API_URL}/items-sin-mla/banear-item`,
        { item_id: itemSeleccionado.item_id, motivo: motivo || null },
        { headers: { Authorization: `Bearer ${token}` } }
      );

      alert(`Item ${itemSeleccionado.item_id} agregado a la banlist`);
      setShowMotivoModal(false);
      setItemSeleccionado(null);
      setMotivo('');

      // Recargar listas
      cargarItemsSinMLA();
      if (activeTab === 'banlist') {
        cargarItemsBaneados();
      }
    } catch (error) {
      console.error('Error al banear item:', error);
      alert(error.response?.data?.detail || 'Error al banear item');
    }
  };

  const handleDesbanear = async (banlistId, itemId) => {
    if (!confirm(`¿Seguro que deseas quitar el item ${itemId} de la banlist?`)) {
      return;
    }

    try {
      await axios.post(
        `${API_URL}/items-sin-mla/desbanear-item`,
        { banlist_id: banlistId },
        { headers: { Authorization: `Bearer ${token}` } }
      );

      alert(`Item ${itemId} removido de la banlist`);

      // Recargar listas
      cargarItemsBaneados();
      cargarItemsSinMLA();
    } catch (error) {
      console.error('Error al desbanear item:', error);
      alert('Error al desbanear item');
    }
  };

  const aplicarFiltros = () => {
    cargarItemsSinMLA();
  };

  const limpiarFiltros = () => {
    setMarcaFiltro('');
    setBusqueda('');
    setListaPrecioFiltro('');
    setConStock(null);
  };

  useEffect(() => {
    cargarItemsSinMLA();
  }, [marcaFiltro, busqueda, listaPrecioFiltro, conStock]);

  const handleSort = (column) => {
    if (sortColumn === column) {
      // Cambiar dirección si es la misma columna
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      // Nueva columna, ordenar ascendente
      setSortColumn(column);
      setSortDirection('asc');
    }
  };

  const sortedItems = (items) => {
    if (!sortColumn) return items;

    return [...items].sort((a, b) => {
      let aVal = a[sortColumn];
      let bVal = b[sortColumn];

      // Manejo especial para arrays (listas)
      if (Array.isArray(aVal) && Array.isArray(bVal)) {
        aVal = aVal.length;
        bVal = bVal.length;
      }

      // Manejo para valores null/undefined
      if (aVal === null || aVal === undefined) aVal = '';
      if (bVal === null || bVal === undefined) bVal = '';

      // Comparación
      if (typeof aVal === 'string') {
        aVal = aVal.toLowerCase();
        bVal = bVal.toLowerCase();
      }

      if (aVal < bVal) return sortDirection === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortDirection === 'asc' ? 1 : -1;
      return 0;
    });
  };

  const renderSortIcon = (column) => {
    if (sortColumn !== column) return ' ⇅';
    return sortDirection === 'asc' ? ' ↑' : ' ↓';
  };

  useEffect(() => {
    cargarItemsSinMLA();
  }, [marcaFiltro, busqueda, listaPrecioFiltro, conStock]);

  return (
    <div className="items-sin-mla-container">
      <div className="page-header">
        <h1>📋 Items sin MLA</h1>
        <p className="page-description">
          Gestión de productos sin publicación en MercadoLibre
        </p>
      </div>

      {/* Tabs */}
      <div className="tabs-container">
        <button
          className={`tab-button ${activeTab === 'sin-mla' ? 'active' : ''}`}
          onClick={() => setActiveTab('sin-mla')}
        >
          🔍 Sin MLA ({itemsSinMLA.length})
        </button>
        <button
          className={`tab-button ${activeTab === 'banlist' ? 'active' : ''}`}
          onClick={() => setActiveTab('banlist')}
        >
          🚫 Banlist ({itemsBaneados.length})
        </button>
      </div>

      {/* Contenido del Tab 1: Items sin MLA */}
      {activeTab === 'sin-mla' && (
        <div className="tab-content">
          {/* Filtros */}
          <div className="filters-section">
            <div className="filter-group">
              <label>🔎 Buscar:</label>
              <input
                type="text"
                placeholder="Código o descripción"
                value={busqueda}
                onChange={(e) => setBusqueda(e.target.value)}
                className="filter-input"
              />
            </div>

            <div className="filter-group">
              <label>🏷️ Marca:</label>
              <select
                value={marcaFiltro}
                onChange={(e) => setMarcaFiltro(e.target.value)}
                className="filter-select"
              >
                <option value="">Todas las marcas</option>
                {marcas.map((m) => (
                  <option key={m.marca} value={m.marca}>
                    {m.marca}
                  </option>
                ))}
              </select>
            </div>

            <div className="filter-group">
              <label>💰 Lista faltante:</label>
              <select
                value={listaPrecioFiltro}
                onChange={(e) => setListaPrecioFiltro(e.target.value)}
                className="filter-select"
              >
                <option value="">Todas las listas</option>
                {listasPrecio.map((l) => (
                  <option key={l.prli_id} value={l.prli_id}>
                    {l.nombre}
                  </option>
                ))}
              </select>
            </div>

            <div className="filter-group">
              <label>📦 Stock:</label>
              <select
                value={conStock === null ? '' : conStock.toString()}
                onChange={(e) => {
                  const val = e.target.value;
                  setConStock(val === '' ? null : val === 'true');
                }}
                className="filter-select"
              >
                <option value="">Todos</option>
                <option value="true">Con stock</option>
                <option value="false">Sin stock</option>
              </select>
            </div>

            <button onClick={limpiarFiltros} className="btn-limpiar">
              🗑️ Limpiar
            </button>
          </div>

          {/* Tabla de items sin MLA */}
          {loadingItems ? (
            <div className="loading">Cargando items sin MLA...</div>
          ) : (
            <div className="table-container">
              <table className="items-table">
                <thead>
                  <tr>
                    <th className="sortable" onClick={() => handleSort('item_id')}>
                      Item ID{renderSortIcon('item_id')}
                    </th>
                    <th className="sortable" onClick={() => handleSort('codigo')}>
                      Código{renderSortIcon('codigo')}
                    </th>
                    <th className="sortable" onClick={() => handleSort('descripcion')}>
                      Descripción{renderSortIcon('descripcion')}
                    </th>
                    <th className="sortable" onClick={() => handleSort('marca')}>
                      Marca{renderSortIcon('marca')}
                    </th>
                    <th className="sortable" onClick={() => handleSort('stock')}>
                      Stock{renderSortIcon('stock')}
                    </th>
                    <th className="sortable" onClick={() => handleSort('listas_sin_mla')}>
                      Le falta en{renderSortIcon('listas_sin_mla')}
                    </th>
                    <th className="sortable" onClick={() => handleSort('listas_con_mla')}>
                      Tiene en{renderSortIcon('listas_con_mla')}
                    </th>
                    <th>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {itemsSinMLA.length === 0 ? (
                    <tr>
                      <td colSpan="8" className="no-data">
                        No hay items sin MLA con los filtros aplicados
                      </td>
                    </tr>
                  ) : (
                    sortedItems(itemsSinMLA).map((item) => (
                      <tr key={item.item_id}>
                        <td>{item.item_id}</td>
                        <td>{item.codigo}</td>
                        <td className="descripcion-cell">{item.descripcion}</td>
                        <td>{item.marca}</td>
                        <td className={item.stock > 0 ? 'stock-positive' : 'stock-zero'}>
                          {item.stock}
                        </td>
                        <td className="listas-cell">
                          {item.listas_sin_mla && item.listas_sin_mla.length > 0 ? (
                            <div className="listas-badges">
                              {item.listas_sin_mla.map((lista, idx) => (
                                <span key={idx} className="badge badge-error">{lista}</span>
                              ))}
                            </div>
                          ) : '-'}
                        </td>
                        <td className="listas-cell">
                          {item.listas_con_mla && item.listas_con_mla.length > 0 ? (
                            <div className="listas-badges">
                              {item.listas_con_mla.map((lista, idx) => (
                                <span key={idx} className="badge badge-success">{lista}</span>
                              ))}
                            </div>
                          ) : '-'}
                        </td>
                        <td>
                          <button
                            onClick={() => handleBanear(item)}
                            className="btn-banear"
                            title="Agregar a banlist"
                          >
                            🚫 Banear
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Contenido del Tab 2: Banlist */}
      {activeTab === 'banlist' && (
        <div className="tab-content">
          <p className="tab-description">
            Items que no deben aparecer en el reporte de sin MLA
          </p>

          {loadingBaneados ? (
            <div className="loading">Cargando banlist...</div>
          ) : (
            <div className="table-container">
              <table className="items-table">
                <thead>
                  <tr>
                    <th className="sortable" onClick={() => handleSort('item_id')}>
                      Item ID{renderSortIcon('item_id')}
                    </th>
                    <th className="sortable" onClick={() => handleSort('codigo')}>
                      Código{renderSortIcon('codigo')}
                    </th>
                    <th className="sortable" onClick={() => handleSort('descripcion')}>
                      Descripción{renderSortIcon('descripcion')}
                    </th>
                    <th className="sortable" onClick={() => handleSort('marca')}>
                      Marca{renderSortIcon('marca')}
                    </th>
                    <th className="sortable" onClick={() => handleSort('motivo')}>
                      Motivo{renderSortIcon('motivo')}
                    </th>
                    <th className="sortable" onClick={() => handleSort('usuario_nombre')}>
                      Usuario{renderSortIcon('usuario_nombre')}
                    </th>
                    <th className="sortable" onClick={() => handleSort('fecha_creacion')}>
                      Fecha{renderSortIcon('fecha_creacion')}
                    </th>
                    <th>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {itemsBaneados.length === 0 ? (
                    <tr>
                      <td colSpan="8" className="no-data">
                        No hay items en la banlist
                      </td>
                    </tr>
                  ) : (
                    sortedItems(itemsBaneados).map((item) => (
                      <tr key={item.id}>
                        <td>{item.item_id}</td>
                        <td>{item.codigo}</td>
                        <td className="descripcion-cell">{item.descripcion}</td>
                        <td>{item.marca}</td>
                        <td className="motivo-cell">{item.motivo || '-'}</td>
                        <td>{item.usuario_nombre}</td>
                        <td>{new Date(item.fecha_creacion).toLocaleDateString()}</td>
                        <td>
                          <button
                            onClick={() => handleDesbanear(item.id, item.item_id)}
                            className="btn-desbanear"
                            title="Quitar de banlist"
                          >
                            ✅ Desbanear
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Modal para agregar motivo al banear */}
      {showMotivoModal && (
        <div className="modal-overlay" onClick={() => setShowMotivoModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h3>🚫 Agregar a Banlist</h3>
            <p>
              <strong>Item:</strong> {itemSeleccionado?.item_id} - {itemSeleccionado?.descripcion}
            </p>
            <div className="form-group">
              <label>Motivo (opcional):</label>
              <textarea
                value={motivo}
                onChange={(e) => setMotivo(e.target.value)}
                placeholder="Ej: Producto descontinuado, no se vende por MLA, etc."
                rows="4"
                className="motivo-textarea"
              />
            </div>
            <div className="modal-actions">
              <button onClick={confirmarBanear} className="btn-confirmar">
                Confirmar
              </button>
              <button onClick={() => setShowMotivoModal(false)} className="btn-cancelar">
                Cancelar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default ItemsSinMLA;
