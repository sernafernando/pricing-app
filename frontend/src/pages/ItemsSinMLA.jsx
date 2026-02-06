import React, { useState, useEffect, useMemo } from 'react';
import axios from 'axios';
import { useQueryFilters } from '../hooks/useQueryFilters';
import { usePermisos } from '../hooks/usePermisos';
import './ItemsSinMLA.css';

const ItemsSinMLA = () => {
  const { tienePermiso } = usePermisos();
  
  // Usar query params para tab activo
  const { getFilter, updateFilters } = useQueryFilters({
    tab: 'sin-mla'
  });

  const activeTab = getFilter('tab');
  const setActiveTab = (tab) => updateFilters({ tab });

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
  const [soloNuevos, setSoloNuevos] = useState(false); // Filtro para mostrar solo items nuevos

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
  const [soloNuevosBanlist, setSoloNuevosBanlist] = useState(false);

  // Estado para comparación de listas
  const [itemsComparacion, setItemsComparacion] = useState([]);
  const [loadingComparacion, setLoadingComparacion] = useState(false);
  const [busquedaComparacion, setBusquedaComparacion] = useState('');
  const [marcaComparacion, setMarcaComparacion] = useState('');

  // Estado para multi-selección en comparación
  const [comparacionSeleccionados, setComparacionSeleccionados] = useState(new Set());
  const [ultimoComparacionSeleccionado, setUltimoComparacionSeleccionado] = useState(null);

  // Modal para banear comparación
  const [comparacionItemSeleccionado, setComparacionItemSeleccionado] = useState(null);
  const [showComparacionMotivoModal, setShowComparacionMotivoModal] = useState(false);
  const [comparacionMotivo, setComparacionMotivo] = useState('');

  // Estado para banlist de comparación
  const [comparacionBaneados, setComparacionBaneados] = useState([]);
  const [loadingComparacionBaneados, setLoadingComparacionBaneados] = useState(false);
  const [busquedaComparacionBanlist, setBusquedaComparacionBanlist] = useState('');

  // Selector de banlist activa en tab banlist
  const [banlistActiva, setBanlistActiva] = useState('items-sin-mla');

  // Estado para multi-selección en banlist de comparación
  const [comparacionBaneadosSeleccionados, setComparacionBaneadosSeleccionados] = useState(new Set());
  const [ultimoComparacionBaneadoSeleccionado, setUltimoComparacionBaneadoSeleccionado] = useState(null);

  const API_URL = import.meta.env.VITE_API_URL;
  const token = localStorage.getItem('token');

  useEffect(() => {
    cargarListasPrecio();
    cargarItemsSinMLA();
  }, []);

  useEffect(() => {
    if (activeTab === 'banlist') {
      if (banlistActiva === 'items-sin-mla') {
        cargarItemsBaneados();
      } else {
        cargarComparacionBaneados();
      }
    } else if (activeTab === 'comparacion') {
      cargarComparacionListas();
    }
  }, [activeTab, banlistActiva]);

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

      // Aplicar filtros
      let itemsFiltrados = responseBase.data;

      // Filtro de marca
      if (marcasSeleccionadas.length > 0) {
        itemsFiltrados = itemsFiltrados.filter(item => marcasSeleccionadas.includes(item.marca));
      }

      // Filtro de solo nuevos
      if (soloNuevos) {
        const maxId = Math.max(...itemsFiltrados.map(i => i.item_id));
        const umbral = maxId * 0.95;
        itemsFiltrados = itemsFiltrados.filter(item => item.item_id >= umbral);
      }

      setItemsSinMLA(itemsFiltrados);
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

    // Filtro de solo nuevos
    if (soloNuevosBanlist) {
      const maxId = Math.max(...itemsFiltrados.map(i => i.item_id));
      const umbral = maxId * 0.95;
      itemsFiltrados = itemsFiltrados.filter(item => item.item_id >= umbral);
    }

    setItemsBaneados(itemsFiltrados);
  };

  const limpiarFiltrosBanlist = () => {
    setMarcasSeleccionadasBanlist([]);
    setBusquedaBanlist('');
    setSoloNuevosBanlist(false);
    setPanelMarcasAbiertoBanlist(false);
    aplicarFiltrosBanlist(itemsBaneadosOriginales);
  };

  const cargarComparacionListas = async () => {
    setLoadingComparacion(true);
    try {
      const params = {};
      if (busquedaComparacion) params.buscar = busquedaComparacion;
      if (marcaComparacion) params.marca = marcaComparacion;

      const response = await axios.get(`${API_URL}/items-sin-mla/comparacion-listas`, {
        headers: { Authorization: `Bearer ${token}` },
        params
      });

      setItemsComparacion(response.data);
    } catch (error) {
      console.error('Error al cargar comparación de listas:', error);
      alert('Error al cargar la comparación de listas');
    } finally {
      setLoadingComparacion(false);
    }
  };

  // === Funciones para banlist de comparación ===
  const cargarComparacionBaneados = async () => {
    setLoadingComparacionBaneados(true);
    try {
      const response = await axios.get(`${API_URL}/items-sin-mla/comparacion-baneados`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setComparacionBaneados(response.data);
    } catch (error) {
      console.error('Error al cargar banlist de comparación:', error);
      alert('Error al cargar banlist de comparación');
    } finally {
      setLoadingComparacionBaneados(false);
    }
  };

  const handleBanearComparacion = (item) => {
    setComparacionItemSeleccionado(item);
    setComparacionMotivo('');
    setShowComparacionMotivoModal(true);
  };

  const confirmarBanearComparacion = async () => {
    if (!comparacionItemSeleccionado) return;

    try {
      await axios.post(
        `${API_URL}/items-sin-mla/banear-comparacion`,
        { mla_id: comparacionItemSeleccionado.mla_id, motivo: comparacionMotivo || null },
        { headers: { Authorization: `Bearer ${token}` } }
      );

      alert(`Publicación ${comparacionItemSeleccionado.mla_id} agregada a la banlist`);
      setShowComparacionMotivoModal(false);
      setComparacionItemSeleccionado(null);
      setComparacionMotivo('');

      cargarComparacionListas();
      if (banlistActiva === 'comparacion') {
        cargarComparacionBaneados();
      }
    } catch (error) {
      console.error('Error al banear comparación:', error);
      alert(error.response?.data?.detail || 'Error al banear publicación');
    }
  };

  const handleDesbanearComparacion = async (banlistId, mlaId) => {
    if (!confirm(`¿Seguro que deseas quitar ${mlaId} de la banlist?`)) return;

    try {
      await axios.post(
        `${API_URL}/items-sin-mla/desbanear-comparacion`,
        { banlist_id: banlistId },
        { headers: { Authorization: `Bearer ${token}` } }
      );

      alert(`Publicación ${mlaId} removida de la banlist`);
      cargarComparacionBaneados();
      cargarComparacionListas();
    } catch (error) {
      console.error('Error al desbanear comparación:', error);
      alert('Error al desbanear publicación');
    }
  };

  const banearComparacionSeleccionados = async () => {
    if (comparacionSeleccionados.size === 0) return;
    if (!window.confirm(`¿Banear ${comparacionSeleccionados.size} publicaciones?`)) return;

    try {
      for (const mlaId of comparacionSeleccionados) {
        await axios.post(
          `${API_URL}/items-sin-mla/banear-comparacion`,
          { mla_id: mlaId, motivo: 'Baneado masivamente' },
          { headers: { Authorization: `Bearer ${token}` } }
        );
      }

      alert(`${comparacionSeleccionados.size} publicaciones baneadas exitosamente`);
      setComparacionSeleccionados(new Set());
      setUltimoComparacionSeleccionado(null);
      cargarComparacionListas();
      cargarComparacionBaneados();
    } catch (error) {
      console.error('Error baneando comparaciones:', error);
      alert('Error al banear publicaciones masivamente');
    }
  };

  const handleSeleccionarComparacion = (mlaId, event) => {
    const shiftPressed = event?.shiftKey;
    const nuevaSeleccion = new Set(comparacionSeleccionados);

    if (shiftPressed && ultimoComparacionSeleccionado !== null) {
      const itemsActuales = sortedItems(itemsComparacion);
      const indices = [
        itemsActuales.findIndex(i => i.mla_id === ultimoComparacionSeleccionado),
        itemsActuales.findIndex(i => i.mla_id === mlaId)
      ].sort((a, b) => a - b);

      for (let i = indices[0]; i <= indices[1]; i++) {
        if (itemsActuales[i]) {
          nuevaSeleccion.add(itemsActuales[i].mla_id);
        }
      }
    } else {
      if (nuevaSeleccion.has(mlaId)) {
        nuevaSeleccion.delete(mlaId);
      } else {
        nuevaSeleccion.add(mlaId);
      }
    }

    setComparacionSeleccionados(nuevaSeleccion);
    setUltimoComparacionSeleccionado(mlaId);
  };

  const handleSeleccionarTodosComparacion = () => {
    if (comparacionSeleccionados.size === itemsComparacion.length) {
      setComparacionSeleccionados(new Set());
    } else {
      setComparacionSeleccionados(new Set(itemsComparacion.map(item => item.mla_id)));
    }
  };

  // Multi-selección en banlist de comparación
  const handleSeleccionarComparacionBaneado = (banlistId, event) => {
    const shiftPressed = event?.shiftKey;
    const nuevaSeleccion = new Set(comparacionBaneadosSeleccionados);

    if (shiftPressed && ultimoComparacionBaneadoSeleccionado !== null) {
      const itemsActuales = sortedItems(comparacionBaneados);
      const indices = [
        itemsActuales.findIndex(i => i.id === ultimoComparacionBaneadoSeleccionado),
        itemsActuales.findIndex(i => i.id === banlistId)
      ].sort((a, b) => a - b);

      for (let i = indices[0]; i <= indices[1]; i++) {
        if (itemsActuales[i]) {
          nuevaSeleccion.add(itemsActuales[i].id);
        }
      }
    } else {
      if (nuevaSeleccion.has(banlistId)) {
        nuevaSeleccion.delete(banlistId);
      } else {
        nuevaSeleccion.add(banlistId);
      }
    }

    setComparacionBaneadosSeleccionados(nuevaSeleccion);
    setUltimoComparacionBaneadoSeleccionado(banlistId);
  };

  const handleSeleccionarTodosComparacionBaneados = () => {
    if (comparacionBaneadosSeleccionados.size === comparacionBaneados.length) {
      setComparacionBaneadosSeleccionados(new Set());
    } else {
      setComparacionBaneadosSeleccionados(new Set(comparacionBaneados.map(item => item.id)));
    }
  };

  const desbanearComparacionSeleccionados = async () => {
    if (comparacionBaneadosSeleccionados.size === 0) return;
    if (!window.confirm(`¿Desbanear ${comparacionBaneadosSeleccionados.size} publicaciones?`)) return;

    try {
      for (const banlistId of comparacionBaneadosSeleccionados) {
        await axios.post(
          `${API_URL}/items-sin-mla/desbanear-comparacion`,
          { banlist_id: banlistId },
          { headers: { Authorization: `Bearer ${token}` } }
        );
      }

      alert(`${comparacionBaneadosSeleccionados.size} publicaciones desbaneadas exitosamente`);
      setComparacionBaneadosSeleccionados(new Set());
      setUltimoComparacionBaneadoSeleccionado(null);
      cargarComparacionBaneados();
      cargarComparacionListas();
    } catch (error) {
      console.error('Error desbaneando comparaciones:', error);
      alert('Error al desbanear publicaciones masivamente');
    }
  };

  // Filtrar banlist de comparación por búsqueda
  const comparacionBaneadosFiltrados = comparacionBaneados.filter(item => {
    if (!busquedaComparacionBanlist) return true;
    const busq = busquedaComparacionBanlist.toLowerCase();
    return (
      item.mla_id?.toLowerCase().includes(busq) ||
      item.codigo?.toLowerCase().includes(busq) ||
      item.descripcion?.toLowerCase().includes(busq)
    );
  });

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
    setSoloNuevos(false);
    setPanelMarcasAbierto(false);
  };

  useEffect(() => {
    cargarItemsSinMLA();
  }, [marcasSeleccionadas, busqueda, listaPrecioFiltro, conStock, soloNuevos]);

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

  // Función para determinar si un item es nuevo
  // Un item se considera "nuevo" si su item_id está en el top 5% de todos los item_ids
  const esItemNuevo = (itemId) => {
    const todosLosIds = [...itemsSinMLA.map(i => i.item_id), ...itemsBaneados.map(i => i.item_id)];
    if (todosLosIds.length === 0) return false;

    const maxId = Math.max(...todosLosIds);
    const umbral = maxId * 0.95; // Top 5% de IDs más altos

    return itemId >= umbral;
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
    if (itemsBaneadosOriginales.length > 0) {
      aplicarFiltrosBanlist();
    }
  }, [marcasSeleccionadasBanlist, busquedaBanlist, soloNuevosBanlist]);

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
        {tienePermiso('admin.ver_items_sin_mla') && (
          <button
            className={`tab-button ${activeTab === 'sin-mla' ? 'active' : ''}`}
            onClick={() => setActiveTab('sin-mla')}
          >
            🔍 Sin MLA ({itemsSinMLA.length})
          </button>
        )}
        {(tienePermiso('admin.gestionar_items_sin_mla_banlist') || tienePermiso('admin.gestionar_comparacion_banlist')) && (
          <button
            className={`tab-button ${activeTab === 'banlist' ? 'active' : ''}`}
            onClick={() => setActiveTab('banlist')}
          >
            🚫 Banlist
          </button>
        )}
        {tienePermiso('admin.ver_comparacion_listas_ml') && (
          <button
            className={`tab-button ${activeTab === 'comparacion' ? 'active' : ''}`}
            onClick={() => setActiveTab('comparacion')}
          >
            📊 Comparación Listas ({itemsComparacion.length})
          </button>
        )}
      </div>

      {/* Contenido del Tab 1: Items sin MLA */}
      {activeTab === 'sin-mla' && tienePermiso('admin.ver_items_sin_mla') && (
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

            <div className="filter-group">
              <label style={{display: 'flex', alignItems: 'center', cursor: 'pointer'}}>
                <input
                  type="checkbox"
                  checked={soloNuevos}
                  onChange={(e) => setSoloNuevos(e.target.checked)}
                  style={{marginRight: '6px', cursor: 'pointer'}}
                />
                ✨ Solo nuevos
              </label>
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
                      >
                        <td className="checkbox-col">
                          <input
                            type="checkbox"
                            checked={itemsSeleccionados.has(item.item_id)}
                            onChange={(e) => handleSeleccionarItem(item.item_id, e)}
                          />
                        </td>
                        <td>{item.item_id}</td>
                        <td>{item.codigo}</td>
                        <td className="descripcion-cell">
                          {esItemNuevo(item.item_id) && <span className="badge-nuevo">NUEVO</span>}
                          {item.descripcion}
                        </td>
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

      {/* Contenido del Tab 2: Banlist (con selector) */}
      {activeTab === 'banlist' && (tienePermiso('admin.gestionar_items_sin_mla_banlist') || tienePermiso('admin.gestionar_comparacion_banlist')) && (
        <div className="tab-content">
          {/* Selector de banlist */}
          <div className="banlist-selector">
            {tienePermiso('admin.gestionar_items_sin_mla_banlist') && (
              <button
                className={`banlist-selector-btn ${banlistActiva === 'items-sin-mla' ? 'active' : ''}`}
                onClick={() => { setBanlistActiva('items-sin-mla'); setOrdenColumnas([]); }}
              >
                🔍 Items sin MLA ({itemsBaneados.length})
              </button>
            )}
            {tienePermiso('admin.gestionar_comparacion_banlist') && (
              <button
                className={`banlist-selector-btn ${banlistActiva === 'comparacion' ? 'active' : ''}`}
                onClick={() => { setBanlistActiva('comparacion'); setOrdenColumnas([]); }}
              >
                📊 Comparación ({comparacionBaneados.length})
              </button>
            )}
          </div>

          {/* Banlist de Items sin MLA */}
          {banlistActiva === 'items-sin-mla' && tienePermiso('admin.gestionar_items_sin_mla_banlist') && (
            <>
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

                <div className="filter-group">
                  <label style={{display: 'flex', alignItems: 'center', cursor: 'pointer'}}>
                    <input
                      type="checkbox"
                      checked={soloNuevosBanlist}
                      onChange={(e) => setSoloNuevosBanlist(e.target.checked)}
                      style={{marginRight: '6px', cursor: 'pointer'}}
                    />
                    ✨ Solo nuevos
                  </label>
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
                          >
                            <td className="checkbox-col">
                              <input
                                type="checkbox"
                                checked={baneadosSeleccionados.has(item.id)}
                                onChange={(e) => handleSeleccionarBaneado(item.id, e)}
                              />
                            </td>
                            <td>{item.item_id}</td>
                            <td>{item.codigo}</td>
                            <td className="descripcion-cell">
                              {esItemNuevo(item.item_id) && <span className="badge-nuevo">NUEVO</span>}
                              {item.descripcion}
                            </td>
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
            </>
          )}

          {/* Banlist de Comparación */}
          {banlistActiva === 'comparacion' && tienePermiso('admin.gestionar_comparacion_banlist') && (
            <>
              <p className="tab-description">
                Publicaciones excluidas de la comparación de listas (errores ya revisados)
              </p>

              {/* Filtros */}
              <div className="filters-section">
                <div className="filter-group">
                  <label>🔎 Buscar:</label>
                  <input
                    type="text"
                    placeholder="MLA ID, código o descripción"
                    value={busquedaComparacionBanlist}
                    onChange={(e) => setBusquedaComparacionBanlist(e.target.value)}
                    className="filter-input"
                  />
                </div>
              </div>

              {/* Barra de acciones para multi-selección */}
              {comparacionBaneadosSeleccionados.size > 0 && (
                <div className="seleccion-bar">
                  <span>{comparacionBaneadosSeleccionados.size} publicación(es) seleccionada(s)</span>
                  <button onClick={desbanearComparacionSeleccionados} className="btn-desbanear-seleccionados">
                    ✅ Desbanear seleccionados
                  </button>
                </div>
              )}

              {loadingComparacionBaneados ? (
                <div className="loading">Cargando banlist de comparación...</div>
              ) : (
                <div className="table-container">
                  <table className="items-table">
                    <thead>
                      <tr>
                        <th className="checkbox-col">
                          <input
                            type="checkbox"
                            checked={comparacionBaneadosSeleccionados.size === comparacionBaneadosFiltrados.length && comparacionBaneadosFiltrados.length > 0}
                            onChange={handleSeleccionarTodosComparacionBaneados}
                          />
                        </th>
                        <th className="sortable" onClick={(e) => handleSort('mla_id', e)}>
                          MLA ID {getIconoOrden('mla_id')} {getNumeroOrden('mla_id') && <span className="orden-numero">{getNumeroOrden('mla_id')}</span>}
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
                        <th className="sortable" onClick={(e) => handleSort('lista_sistema', e)}>
                          Lista {getIconoOrden('lista_sistema')} {getNumeroOrden('lista_sistema') && <span className="orden-numero">{getNumeroOrden('lista_sistema')}</span>}
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
                      {comparacionBaneadosFiltrados.length === 0 ? (
                        <tr>
                          <td colSpan="10" className="no-data">
                            No hay publicaciones en la banlist de comparación
                          </td>
                        </tr>
                      ) : (
                        sortedItems(comparacionBaneadosFiltrados).map((item) => (
                          <tr
                            key={item.id}
                            className={comparacionBaneadosSeleccionados.has(item.id) ? 'fila-seleccionada' : ''}
                          >
                            <td className="checkbox-col">
                              <input
                                type="checkbox"
                                checked={comparacionBaneadosSeleccionados.has(item.id)}
                                onChange={(e) => handleSeleccionarComparacionBaneado(item.id, e)}
                              />
                            </td>
                            <td>{item.mla_id}</td>
                            <td>{item.item_id || '-'}</td>
                            <td>{item.codigo || '-'}</td>
                            <td className="descripcion-cell">{item.descripcion}</td>
                            <td>
                              {item.lista_sistema && <span className="badge-lista">{item.lista_sistema}</span>}
                            </td>
                            <td className="motivo-cell">{item.motivo || '-'}</td>
                            <td>{item.usuario_nombre}</td>
                            <td>{new Date(item.fecha_creacion).toLocaleDateString()}</td>
                            <td>
                              <button
                                onClick={() => handleDesbanearComparacion(item.id, item.mla_id)}
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
            </>
          )}
        </div>
      )}

      {/* Contenido del Tab 3: Comparación de Listas */}
      {activeTab === 'comparacion' && tienePermiso('admin.ver_comparacion_listas_ml') && (
        <div className="tab-content">
          {/* Barra de acciones para multi-selección */}
          {comparacionSeleccionados.size > 0 && tienePermiso('admin.gestionar_comparacion_banlist') && (
            <div className="seleccion-bar">
              <span>{comparacionSeleccionados.size} publicación(es) seleccionada(s)</span>
              <button onClick={banearComparacionSeleccionados} className="btn-banear-seleccionados">
                🚫 Banear seleccionados
              </button>
            </div>
          )}

          {/* Tabla de comparación */}
          {loadingComparacion ? (
            <div className="loading">Cargando comparación...</div>
          ) : (
            <div className="table-container">
              <table className="items-table">
                <thead>
                  <tr>
                    {tienePermiso('admin.gestionar_comparacion_banlist') && (
                      <th className="checkbox-col">
                        <input
                          type="checkbox"
                          checked={comparacionSeleccionados.size === itemsComparacion.length && itemsComparacion.length > 0}
                          onChange={handleSeleccionarTodosComparacion}
                        />
                      </th>
                    )}
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
                    <th className="sortable" onClick={(e) => handleSort('mla_id', e)}>
                      MLA ID {getIconoOrden('mla_id')} {getNumeroOrden('mla_id') && <span className="orden-numero">{getNumeroOrden('mla_id')}</span>}
                    </th>
                    <th className="sortable" onClick={(e) => handleSort('lista_sistema', e)}>
                      Lista Sistema {getIconoOrden('lista_sistema')} {getNumeroOrden('lista_sistema') && <span className="orden-numero">{getNumeroOrden('lista_sistema')}</span>}
                    </th>
                    <th className="sortable" onClick={(e) => handleSort('campana_ml', e)}>
                      Campaña ML {getIconoOrden('campana_ml')} {getNumeroOrden('campana_ml') && <span className="orden-numero">{getNumeroOrden('campana_ml')}</span>}
                    </th>
                    <th className="sortable" onClick={(e) => handleSort('precio_sistema', e)}>
                      Precio Sistema {getIconoOrden('precio_sistema')} {getNumeroOrden('precio_sistema') && <span className="orden-numero">{getNumeroOrden('precio_sistema')}</span>}
                    </th>
                    <th className="sortable" onClick={(e) => handleSort('precio_ml', e)}>
                      Precio ML {getIconoOrden('precio_ml')} {getNumeroOrden('precio_ml') && <span className="orden-numero">{getNumeroOrden('precio_ml')}</span>}
                    </th>
                    {tienePermiso('admin.gestionar_comparacion_banlist') && (
                      <th>Acciones</th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {itemsComparacion.length === 0 ? (
                    <tr>
                      <td colSpan={tienePermiso('admin.gestionar_comparacion_banlist') ? 11 : 9} className="no-data">
                        No hay diferencias encontradas entre listas del sistema y campañas de ML
                      </td>
                    </tr>
                  ) : (
                    sortedItems(itemsComparacion).map((item) => (
                      <tr
                        key={`${item.mla_id}-${item.item_id}`}
                        className={comparacionSeleccionados.has(item.mla_id) ? 'fila-seleccionada' : ''}
                      >
                        {tienePermiso('admin.gestionar_comparacion_banlist') && (
                          <td className="checkbox-col">
                            <input
                              type="checkbox"
                              checked={comparacionSeleccionados.has(item.mla_id)}
                              onChange={(e) => handleSeleccionarComparacion(item.mla_id, e)}
                            />
                          </td>
                        )}
                        <td>{item.item_id}</td>
                        <td>{item.codigo}</td>
                        <td className="descripcion-cell">{item.descripcion}</td>
                        <td>{item.marca}</td>
                        <td>
                          <a
                            href={item.permalink}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="mla-link"
                          >
                            {item.mla_id}
                          </a>
                        </td>
                        <td>
                          <span className="badge-lista">{item.lista_sistema}</span>
                        </td>
                        <td>
                          <span className="badge-campana">{item.campana_ml}</span>
                        </td>
                        <td>${item.precio_sistema?.toFixed(2)}</td>
                        <td>${item.precio_ml?.toFixed(2)}</td>
                        {tienePermiso('admin.gestionar_comparacion_banlist') && (
                          <td>
                            <button
                              onClick={() => handleBanearComparacion(item)}
                              className="btn-banear"
                              title="Agregar a banlist"
                            >
                              🚫 Banear
                            </button>
                          </td>
                        )}
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Modal para agregar motivo al banear (items sin MLA) */}
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

      {/* Modal para agregar motivo al banear (comparación) */}
      {showComparacionMotivoModal && (
        <div className="modal-overlay" onClick={() => setShowComparacionMotivoModal(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h3>🚫 Banear de Comparación</h3>
            <p>
              <strong>MLA:</strong> {comparacionItemSeleccionado?.mla_id}
            </p>
            <p>
              <strong>Item:</strong> {comparacionItemSeleccionado?.item_id} - {comparacionItemSeleccionado?.descripcion}
            </p>
            <p>
              <strong>Lista:</strong> {comparacionItemSeleccionado?.lista_sistema} → <strong>Campaña ML:</strong> {comparacionItemSeleccionado?.campana_ml}
            </p>
            <div className="form-group">
              <label>Motivo (opcional):</label>
              <textarea
                value={comparacionMotivo}
                onChange={(e) => setComparacionMotivo(e.target.value)}
                placeholder="Ej: Campaña correcta, error de sincronización ya resuelto, etc."
                rows="4"
                className="motivo-textarea"
              />
            </div>
            <div className="modal-actions">
              <button onClick={confirmarBanearComparacion} className="btn-confirmar">
                Confirmar
              </button>
              <button onClick={() => setShowComparacionMotivoModal(false)} className="btn-cancelar">
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
