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
  const [marcasSeleccionadas, setMarcasSeleccionadas] = useState([]);
  const [busquedaMarca, setBusquedaMarca] = useState('');
  const [panelMarcasAbierto, setPanelMarcasAbierto] = useState(false);
  const [busqueda, setBusqueda] = useState('');
  const [listaPrecioFiltro, setListaPrecioFiltro] = useState('');
  const [listasPrecio, setListasPrecio] = useState([]);
  const [conStock, setConStock] = useState(null); // null = todos, true = con stock, false = sin stock

  // Estado para agregar motivo al banear
  const [itemSeleccionado, setItemSeleccionado] = useState(null);
  const [showMotivoModal, setShowMotivoModal] = useState(false);
  const [motivo, setMotivo] = useState('');

  // Estado para ordenamiento (multi-sort con shift)
  const [ordenColumnas, setOrdenColumnas] = useState([]); // [{columna: 'item_id', direccion: 'asc'}, ...]

  // Estado para multi-selección (tab sin MLA)
  const [itemsSeleccionados, setItemsSeleccionados] = useState(new Set());
  const [ultimoSeleccionado, setUltimoSeleccionado] = useState(null);

  // Estado para multi-selección (tab banlist)
  const [baneadosSeleccionados, setBaneadosSeleccionados] = useState(new Set());
  const [ultimoBaneadoSeleccionado, setUltimoBaneadoSeleccionado] = useState(null);

  // Filtros para banlist
  const [marcasBanlist, setMarcasBanlist] = useState([]);
  const [marcasSeleccionadasBanlist, setMarcasSeleccionadasBanlist] = useState([]);
  const [busquedaMarcaBanlist, setBusquedaMarcaBanlist] = useState('');
  const [panelMarcasAbiertoBanlist, setPanelMarcasAbiertoBanlist] = useState(false);
  const [busquedaBanlist, setBusquedaBanlist] = useState('');
  const [itemsBaneadosOriginales, setItemsBaneadosOriginales] = useState([]);

  const API_URL = 'https://pricing.gaussonline.com.ar/api';
  const token = localStorage.getItem('token');

  useEffect(() => {
    cargarListasPrecio();
    cargarItemsSinMLA();
  }, []);

  useEffect(() => {
    if (activeTab === 'banlist') {
      cargarItemsBaneados();
    }
  }, [activeTab]);

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
      // Primero cargar items sin filtro de marca para obtener marcas disponibles
      const paramsBase = {};
      if (busqueda) paramsBase.buscar = busqueda;
      if (listaPrecioFiltro) paramsBase.prli_id = listaPrecioFiltro;
      if (conStock !== null) paramsBase.con_stock = conStock;

      const responseBase = await axios.get(`${API_URL}/items-sin-mla/items-sin-mla`, {
        headers: { Authorization: `Bearer ${token}` },
        params: paramsBase
      });

      // Calcular marcas disponibles desde todos los items (sin filtro de marca)
      const marcasUnicas = [...new Set(responseBase.data.map(item => item.marca).filter(Boolean))].sort();
      setMarcas(marcasUnicas);

      // Si hay filtros de marca, filtrar los items
      if (marcasSeleccionadas.length > 0) {
        const itemsFiltrados = responseBase.data.filter(item => marcasSeleccionadas.includes(item.marca));
        setItemsSinMLA(itemsFiltrados);
      } else {
        setItemsSinMLA(responseBase.data);
      }
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

      const data = response.data;
      setItemsBaneadosOriginales(data);

      // Calcular marcas disponibles
      const marcasUnicas = [...new Set(data.map(item => item.marca).filter(Boolean))].sort();
      setMarcasBanlist(marcasUnicas);

      // Aplicar filtros
      aplicarFiltrosBanlist(data);
    } catch (error) {
      console.error('Error al cargar items baneados:', error);
      alert('Error al cargar items baneados');
    } finally {
      setLoadingBaneados(false);
    }
  };

  const aplicarFiltrosBanlist = (items = itemsBaneadosOriginales) => {
    let itemsFiltrados = [...items];

    // Filtro de búsqueda
    if (busquedaBanlist) {
      const busquedaLower = busquedaBanlist.toLowerCase();
      itemsFiltrados = itemsFiltrados.filter(item =>
        item.codigo?.toLowerCase().includes(busquedaLower) ||
        item.descripcion?.toLowerCase().includes(busquedaLower) ||
        item.item_id?.toString().includes(busquedaLower)
      );
    }

    // Filtro de marcas
    if (marcasSeleccionadasBanlist.length > 0) {
      itemsFiltrados = itemsFiltrados.filter(item =>
        marcasSeleccionadasBanlist.includes(item.marca)
      );
    }

    setItemsBaneados(itemsFiltrados);
  };

  const limpiarFiltrosBanlist = () => {
    setMarcasSeleccionadasBanlist([]);
    setBusquedaBanlist('');
    setPanelMarcasAbiertoBanlist(false);
    aplicarFiltrosBanlist(itemsBaneadosOriginales);
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
    setMarcasSeleccionadas([]);
    setBusqueda('');
    setListaPrecioFiltro('');
    setConStock(null);
    setPanelMarcasAbierto(false);
  };

  useEffect(() => {
    cargarItemsSinMLA();
  }, [marcasSeleccionadas, busqueda, listaPrecioFiltro, conStock]);

  const handleSort = (columna, event) => {
    const shiftPressed = event?.shiftKey;

    if (!shiftPressed) {
      // Sin Shift: ordenamiento simple
      const existente = ordenColumnas.find(o => o.columna === columna);

      if (existente) {
        if (existente.direccion === 'asc') {
          setOrdenColumnas([{ columna, direccion: 'desc' }]);
        } else {
          setOrdenColumnas([]);
        }
      } else {
        setOrdenColumnas([{ columna, direccion: 'asc' }]);
      }
    } else {
      // Con Shift: ordenamiento múltiple
      const existente = ordenColumnas.find(o => o.columna === columna);

      if (existente) {
        if (existente.direccion === 'asc') {
          // Cambiar a descendente
          setOrdenColumnas(
            ordenColumnas.map(o =>
              o.columna === columna ? { ...o, direccion: 'desc' } : o
            )
          );
        } else {
          // Quitar esta columna del ordenamiento
          setOrdenColumnas(ordenColumnas.filter(o => o.columna !== columna));
        }
      } else {
        // Agregar nueva columna al ordenamiento
        setOrdenColumnas([...ordenColumnas, { columna, direccion: 'asc' }]);
      }
    }
  };

  const sortedItems = (items) => {
    if (ordenColumnas.length === 0) return items;

    return [...items].sort((a, b) => {
      // Comparar por cada columna en orden
      for (const { columna, direccion } of ordenColumnas) {
        let aVal = a[columna];
        let bVal = b[columna];

        // Manejo especial para arrays (listas)
        if (Array.isArray(aVal) && Array.isArray(bVal)) {
          aVal = aVal.length;
          bVal = bVal.length;
        }

        // Manejo para valores null/undefined
        if (aVal === null || aVal === undefined) aVal = '';
        if (bVal === null || bVal === undefined) bVal = '';

        // Comparación
        if (typeof aVal === 'string' && typeof bVal === 'string') {
          aVal = aVal.toLowerCase();
          bVal = bVal.toLowerCase();
        }

        if (aVal < bVal) return direccion === 'asc' ? -1 : 1;
        if (aVal > bVal) return direccion === 'asc' ? 1 : -1;
        // Si son iguales, continuar con la siguiente columna
      }
      return 0;
    });
  };

  const getIconoOrden = (columna) => {
    const orden = ordenColumnas.find(o => o.columna === columna);
    if (!orden) return '↕';
    return orden.direccion === 'asc' ? '▲' : '▼';
  };

  const getNumeroOrden = (columna) => {
    const index = ordenColumnas.findIndex(o => o.columna === columna);
    return index >= 0 ? index + 1 : null;
  };

  const handleSeleccionarItem = (itemId, event) => {
    const shiftPressed = event?.shiftKey;
    const ctrlPressed = event?.ctrlKey || event?.metaKey;

    const nuevaSeleccion = new Set(itemsSeleccionados);

    if (shiftPressed && ultimoSeleccionado !== null) {
      // Selección por rango
      const itemsActuales = sortedItems(itemsSinMLA);
      const indices = [
        itemsActuales.findIndex(i => i.item_id === ultimoSeleccionado),
        itemsActuales.findIndex(i => i.item_id === itemId)
      ].sort((a, b) => a - b);

      for (let i = indices[0]; i <= indices[1]; i++) {
        if (itemsActuales[i]) {
          nuevaSeleccion.add(itemsActuales[i].item_id);
        }
      }
    } else {
      // Toggle individual (sin Ctrl también funciona)
      if (nuevaSeleccion.has(itemId)) {
        nuevaSeleccion.delete(itemId);
      } else {
        nuevaSeleccion.add(itemId);
      }
    }

    setItemsSeleccionados(nuevaSeleccion);
    setUltimoSeleccionado(itemId);
  };

  const handleSeleccionarTodos = () => {
    if (itemsSeleccionados.size === itemsSinMLA.length) {
      setItemsSeleccionados(new Set());
    } else {
      setItemsSeleccionados(new Set(itemsSinMLA.map(item => item.item_id)));
    }
  };

  const banearSeleccionados = async () => {
    if (itemsSeleccionados.size === 0) return;

    if (!window.confirm(`¿Banear ${itemsSeleccionados.size} items?`)) return;

    try {
      for (const itemId of itemsSeleccionados) {
        await axios.post(
          `${API_URL}/items-sin-mla/banear-item`,
          { item_id: itemId, motivo: 'Baneado masivamente' },
          { headers: { Authorization: `Bearer ${token}` } }
        );
      }

      alert(`${itemsSeleccionados.size} items baneados exitosamente`);
      setItemsSeleccionados(new Set());
      setUltimoSeleccionado(null);
      cargarItemsSinMLA();
      cargarItemsBaneados();
    } catch (error) {
      console.error('Error baneando items:', error);
      alert('Error al banear items masivamente');
    }
  };

  // Funciones para multi-selección en banlist
  const handleSeleccionarBaneado = (banlistId, event) => {
    const shiftPressed = event?.shiftKey;
    const ctrlPressed = event?.ctrlKey || event?.metaKey;

    const nuevaSeleccion = new Set(baneadosSeleccionados);

    if (shiftPressed && ultimoBaneadoSeleccionado !== null) {
      // Selección por rango
      const itemsActuales = sortedItems(itemsBaneados);
      const indices = [
        itemsActuales.findIndex(i => i.id === ultimoBaneadoSeleccionado),
        itemsActuales.findIndex(i => i.id === banlistId)
      ].sort((a, b) => a - b);

      for (let i = indices[0]; i <= indices[1]; i++) {
        if (itemsActuales[i]) {
          nuevaSeleccion.add(itemsActuales[i].id);
        }
      }
    } else {
      // Toggle individual (sin Ctrl también funciona)
      if (nuevaSeleccion.has(banlistId)) {
        nuevaSeleccion.delete(banlistId);
      } else {
        nuevaSeleccion.add(banlistId);
      }
    }

    setBaneadosSeleccionados(nuevaSeleccion);
    setUltimoBaneadoSeleccionado(banlistId);
  };

  const handleSeleccionarTodosBaneados = () => {
    if (baneadosSeleccionados.size === itemsBaneados.length) {
      setBaneadosSeleccionados(new Set());
    } else {
      setBaneadosSeleccionados(new Set(itemsBaneados.map(item => item.id)));
    }
  };

  const desbanearSeleccionados = async () => {
    if (baneadosSeleccionados.size === 0) return;

    if (!window.confirm(`¿Desbanear ${baneadosSeleccionados.size} items?`)) return;

    try {
      for (const banlistId of baneadosSeleccionados) {
        await axios.post(
          `${API_URL}/items-sin-mla/desbanear-item`,
          { banlist_id: banlistId },
          { headers: { Authorization: `Bearer ${token}` } }
        );
      }

      alert(`${baneadosSeleccionados.size} items desbaneados exitosamente`);
      setBaneadosSeleccionados(new Set());
      setUltimoBaneadoSeleccionado(null);
      cargarItemsBaneados();
      cargarItemsSinMLA();
    } catch (error) {
      console.error('Error desbaneando items:', error);
      alert('Error al desbanear items masivamente');
    }
  };

  useEffect(() => {
    cargarItemsSinMLA();
  }, [marcasSeleccionadas, busqueda, listaPrecioFiltro, conStock]);

  useEffect(() => {
    if (itemsBaneadosOriginales.length > 0) {
      aplicarFiltrosBanlist();
    }
  }, [marcasSeleccionadasBanlist, busquedaBanlist]);

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

            <div className="filter-group marcas-filter-container" style={{position: 'relative'}}>
              <label>🏷️ Marca:</label>
              <button
                onClick={() => setPanelMarcasAbierto(!panelMarcasAbierto)}
                className={`filter-button-dropdown ${marcasSeleccionadas.length > 0 ? 'active' : ''}`}
              >
                {marcasSeleccionadas.length > 0
                  ? `${marcasSeleccionadas.length} marcas`
                  : 'Todas las marcas'}
                {marcasSeleccionadas.length > 0 && (
                  <span className="filter-badge-inline">{marcasSeleccionadas.length}</span>
                )}
              </button>

              {panelMarcasAbierto && (
                <div className="dropdown-panel">
                  <div className="dropdown-header">
                    <input
                      type="text"
                      placeholder="Buscar marca..."
                      value={busquedaMarca}
                      onChange={(e) => setBusquedaMarca(e.target.value)}
                      className="dropdown-search"
                    />
                    {marcasSeleccionadas.length > 0 && (
                      <button
                        onClick={() => setMarcasSeleccionadas([])}
                        className="btn-clear-dropdown"
                      >
                        Limpiar ({marcasSeleccionadas.length})
                      </button>
                    )}
                  </div>
                  <div className="dropdown-list">
                    {marcas
                      .filter(marca => !busquedaMarca || marca.toLowerCase().includes(busquedaMarca.toLowerCase()))
                      .map(marca => (
                        <label
                          key={marca}
                          className={`dropdown-item ${marcasSeleccionadas.includes(marca) ? 'selected' : ''}`}
                        >
                          <input
                            type="checkbox"
                            checked={marcasSeleccionadas.includes(marca)}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setMarcasSeleccionadas([...marcasSeleccionadas, marca]);
                              } else {
                                setMarcasSeleccionadas(marcasSeleccionadas.filter(m => m !== marca));
                              }
                            }}
                          />
                          <span>{marca}</span>
                        </label>
                      ))}
                  </div>
                </div>
              )}
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

          {/* Barra de acciones para multi-selección */}
          {itemsSeleccionados.size > 0 && (
            <div className="seleccion-bar">
              <span>{itemsSeleccionados.size} item(s) seleccionado(s)</span>
              <button onClick={banearSeleccionados} className="btn-banear-seleccionados">
                🚫 Banear seleccionados
              </button>
            </div>
          )}

          {/* Tabla de items sin MLA */}
          {loadingItems ? (
            <div className="loading">Cargando items sin MLA...</div>
          ) : (
            <div className="table-container">
              <table className="items-table">
                <thead>
                  <tr>
                    <th className="checkbox-col">
                      <input
                        type="checkbox"
                        checked={itemsSeleccionados.size === itemsSinMLA.length && itemsSinMLA.length > 0}
                        onChange={handleSeleccionarTodos}
                      />
                    </th>
                    <th className="sortable" onClick={(e) => handleSort('item_id', e)}>
                      Item ID {getIconoOrden('item_id')} {getNumeroOrden('item_id') && <span className="orden-numero">{getNumeroOrden('item_id')}</span>}
                    </th>
                    <th className="sortable" onClick={(e) => handleSort('codigo', e)}>
                      Código {getIconoOrden('codigo')} {getNumeroOrden('codigo') && <span className="orden-numero">{getNumeroOrden('codigo')}</span>}
                    </th>
                    <th className="sortable" onClick={(e) => handleSort('descripcion', e)}>
                      Descripción {getIconoOrden('descripcion')} {getNumeroOrden('descripcion') && <span className="orden-numero">{getNumeroOrden('descripcion')}</span>}
                    </th>
                    <th className="sortable" onClick={(e) => handleSort('marca', e)}>
                      Marca {getIconoOrden('marca')} {getNumeroOrden('marca') && <span className="orden-numero">{getNumeroOrden('marca')}</span>}
                    </th>
                    <th className="sortable" onClick={(e) => handleSort('stock', e)}>
                      Stock {getIconoOrden('stock')} {getNumeroOrden('stock') && <span className="orden-numero">{getNumeroOrden('stock')}</span>}
                    </th>
                    <th className="sortable" onClick={(e) => handleSort('listas_sin_mla', e)}>
                      Le falta en {getIconoOrden('listas_sin_mla')} {getNumeroOrden('listas_sin_mla') && <span className="orden-numero">{getNumeroOrden('listas_sin_mla')}</span>}
                    </th>
                    <th className="sortable" onClick={(e) => handleSort('listas_con_mla', e)}>
                      Tiene en {getIconoOrden('listas_con_mla')} {getNumeroOrden('listas_con_mla') && <span className="orden-numero">{getNumeroOrden('listas_con_mla')}</span>}
                    </th>
                    <th>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {itemsSinMLA.length === 0 ? (
                    <tr>
                      <td colSpan="9" className="no-data">
                        No hay items sin MLA con los filtros aplicados
                      </td>
                    </tr>
                  ) : (
                    sortedItems(itemsSinMLA).map((item) => (
                      <tr
                        key={item.item_id}
                        className={itemsSeleccionados.has(item.item_id) ? 'fila-seleccionada' : ''}
                        onClick={(e) => {
                          if (e.target.type !== 'checkbox' && e.target.tagName !== 'BUTTON') {
                            handleSeleccionarItem(item.item_id, e);
                          }
                        }}
                      >
                        <td className="checkbox-col" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={itemsSeleccionados.has(item.item_id)}
                            onChange={(e) => handleSeleccionarItem(item.item_id, e)}
                          />
                        </td>
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

          {/* Filtros */}
          <div className="filters-section">
            <div className="filter-group">
              <label>🔎 Buscar:</label>
              <input
                type="text"
                placeholder="Código o descripción"
                value={busquedaBanlist}
                onChange={(e) => setBusquedaBanlist(e.target.value)}
                className="filter-input"
              />
            </div>

            <div className="filter-group marcas-filter-container" style={{position: 'relative'}}>
              <label>🏷️ Marca:</label>
              <button
                onClick={() => setPanelMarcasAbiertoBanlist(!panelMarcasAbiertoBanlist)}
                className={`filter-button-dropdown ${marcasSeleccionadasBanlist.length > 0 ? 'active' : ''}`}
              >
                {marcasSeleccionadasBanlist.length > 0
                  ? `${marcasSeleccionadasBanlist.length} marcas`
                  : 'Todas las marcas'}
                {marcasSeleccionadasBanlist.length > 0 && (
                  <span className="filter-badge-inline">{marcasSeleccionadasBanlist.length}</span>
                )}
              </button>

              {panelMarcasAbiertoBanlist && (
                <div className="dropdown-panel">
                  <div className="dropdown-header">
                    <input
                      type="text"
                      placeholder="Buscar marca..."
                      value={busquedaMarcaBanlist}
                      onChange={(e) => setBusquedaMarcaBanlist(e.target.value)}
                      className="dropdown-search"
                    />
                    {marcasSeleccionadasBanlist.length > 0 && (
                      <button
                        onClick={() => setMarcasSeleccionadasBanlist([])}
                        className="btn-clear-dropdown"
                      >
                        Limpiar ({marcasSeleccionadasBanlist.length})
                      </button>
                    )}
                  </div>
                  <div className="dropdown-list">
                    {marcasBanlist
                      .filter(marca => !busquedaMarcaBanlist || marca.toLowerCase().includes(busquedaMarcaBanlist.toLowerCase()))
                      .map(marca => (
                        <label
                          key={marca}
                          className={`dropdown-item ${marcasSeleccionadasBanlist.includes(marca) ? 'selected' : ''}`}
                        >
                          <input
                            type="checkbox"
                            checked={marcasSeleccionadasBanlist.includes(marca)}
                            onChange={(e) => {
                              if (e.target.checked) {
                                setMarcasSeleccionadasBanlist([...marcasSeleccionadasBanlist, marca]);
                              } else {
                                setMarcasSeleccionadasBanlist(marcasSeleccionadasBanlist.filter(m => m !== marca));
                              }
                            }}
                          />
                          <span>{marca}</span>
                        </label>
                      ))}
                  </div>
                </div>
              )}
            </div>

            <button onClick={limpiarFiltrosBanlist} className="btn-limpiar">
              🗑️ Limpiar
            </button>
          </div>

          {/* Barra de acciones para multi-selección */}
          {baneadosSeleccionados.size > 0 && (
            <div className="seleccion-bar">
              <span>{baneadosSeleccionados.size} item(s) seleccionado(s)</span>
              <button onClick={desbanearSeleccionados} className="btn-desbanear-seleccionados">
                ✅ Desbanear seleccionados
              </button>
            </div>
          )}

          {loadingBaneados ? (
            <div className="loading">Cargando banlist...</div>
          ) : (
            <div className="table-container">
              <table className="items-table">
                <thead>
                  <tr>
                    <th className="checkbox-col">
                      <input
                        type="checkbox"
                        checked={baneadosSeleccionados.size === itemsBaneados.length && itemsBaneados.length > 0}
                        onChange={handleSeleccionarTodosBaneados}
                      />
                    </th>
                    <th className="sortable" onClick={(e) => handleSort('item_id', e)}>
                      Item ID {getIconoOrden('item_id')} {getNumeroOrden('item_id') && <span className="orden-numero">{getNumeroOrden('item_id')}</span>}
                    </th>
                    <th className="sortable" onClick={(e) => handleSort('codigo', e)}>
                      Código {getIconoOrden('codigo')} {getNumeroOrden('codigo') && <span className="orden-numero">{getNumeroOrden('codigo')}</span>}
                    </th>
                    <th className="sortable" onClick={(e) => handleSort('descripcion', e)}>
                      Descripción {getIconoOrden('descripcion')} {getNumeroOrden('descripcion') && <span className="orden-numero">{getNumeroOrden('descripcion')}</span>}
                    </th>
                    <th className="sortable" onClick={(e) => handleSort('marca', e)}>
                      Marca {getIconoOrden('marca')} {getNumeroOrden('marca') && <span className="orden-numero">{getNumeroOrden('marca')}</span>}
                    </th>
                    <th className="sortable" onClick={(e) => handleSort('motivo', e)}>
                      Motivo {getIconoOrden('motivo')} {getNumeroOrden('motivo') && <span className="orden-numero">{getNumeroOrden('motivo')}</span>}
                    </th>
                    <th className="sortable" onClick={(e) => handleSort('usuario_nombre', e)}>
                      Usuario {getIconoOrden('usuario_nombre')} {getNumeroOrden('usuario_nombre') && <span className="orden-numero">{getNumeroOrden('usuario_nombre')}</span>}
                    </th>
                    <th className="sortable" onClick={(e) => handleSort('fecha_creacion', e)}>
                      Fecha {getIconoOrden('fecha_creacion')} {getNumeroOrden('fecha_creacion') && <span className="orden-numero">{getNumeroOrden('fecha_creacion')}</span>}
                    </th>
                    <th>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {itemsBaneados.length === 0 ? (
                    <tr>
                      <td colSpan="9" className="no-data">
                        No hay items en la banlist
                      </td>
                    </tr>
                  ) : (
                    sortedItems(itemsBaneados).map((item) => (
                      <tr
                        key={item.id}
                        className={baneadosSeleccionados.has(item.id) ? 'fila-seleccionada' : ''}
                        onClick={(e) => {
                          if (e.target.type !== 'checkbox' && e.target.tagName !== 'BUTTON') {
                            handleSeleccionarBaneado(item.id, e);
                          }
                        }}
                      >
                        <td className="checkbox-col" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={baneadosSeleccionados.has(item.id)}
                            onChange={(e) => handleSeleccionarBaneado(item.id, e)}
                          />
                        </td>
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
