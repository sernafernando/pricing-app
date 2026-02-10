import { useState, useEffect } from 'react';
import axios from 'axios';
import { useQueryFilters } from '../hooks/useQueryFilters';
import { usePermisos } from '../hooks/usePermisos';
import { useAuthStore } from '../store/authStore';
import ModalInfoProducto from '../components/ModalInfoProducto';
import './ItemsSinMLA.css';

// Inline SVG icons — stroke-based, consistent 16x16 default
const s = (d, size = 16) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{verticalAlign: 'middle', marginRight: 4, flexShrink: 0}}>
    {d}
  </svg>
);

const Icon = {
  clipboard:   (sz) => s(<><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/></>, sz),
  search:      (sz) => s(<><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></>, sz),
  ban:         (sz) => s(<><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></>, sz),
  barChart:    (sz) => s(<><line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/></>, sz),
  tag:         (sz) => s(<><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/><line x1="7" y1="7" x2="7.01" y2="7"/></>, sz),
  dollar:      (sz) => s(<><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></>, sz),
  box:         (sz) => s(<><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></>, sz),
  sparkle:     (sz) => s(<><path d="M12 2l2.09 6.26L20 10l-5.91 1.74L12 18l-2.09-6.26L4 10l5.91-1.74L12 2z"/></>, sz),
  alertCircle: (sz) => s(<><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></>, sz),
  trash:       (sz) => s(<><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></>, sz),
  pin:         (sz) => s(<><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7z"/><circle cx="12" cy="9" r="2.5"/></>, sz),
  user:        (sz) => s(<><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></>, sz),
  edit:        (sz) => s(<><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></>, sz),
  check:       (sz) => s(<><polyline points="20 6 9 17 4 12"/></>, sz),
  x:           (sz) => s(<><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></>, sz),
  checkCircle: (sz) => s(<><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></>, sz),
  info:        (sz) => s(<><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></>, sz),
};

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
  const [sinPublicaciones, setSinPublicaciones] = useState(false); // Filtro: sin ninguna publicación

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

  // ========== SISTEMA DE ASIGNACIONES ==========
  const [asignaciones, setAsignaciones] = useState([]); // Todas las asignaciones pendientes
  const [usuariosAsignables, setUsuariosAsignables] = useState([]);
  const [showAsignarModal, setShowAsignarModal] = useState(false);
  const [itemParaAsignar, setItemParaAsignar] = useState(null); // Item actual para asignar
  const [listasParaAsignar, setListasParaAsignar] = useState([]); // Listas seleccionadas en el modal
  const [usuarioDestinoId, setUsuarioDestinoId] = useState(''); // '' = auto-asignarse
  const [notasAsignacion, setNotasAsignacion] = useState('');
  const [loadingAsignacion, setLoadingAsignacion] = useState(false);

  // Filtros de asignaciones en tab sin-mla
  const [filtroAsignadoA, setFiltroAsignadoA] = useState(''); // usuario_id del asignado
  const [filtroAsignadoPor, setFiltroAsignadoPor] = useState(''); // asignado_por_id
  const [filtroEstadoAsignacion, setFiltroEstadoAsignacion] = useState(''); // '' = sin filtro, 'pendiente', 'asignado', 'sin-asignar'

  // Modal de asignación masiva
  const [showAsignarMasivoModal, setShowAsignarMasivoModal] = useState(false);

  // Modal de info producto
  const [mostrarModalInfo, setMostrarModalInfo] = useState(false);
  const [productoInfoId, setProductoInfoId] = useState(null);

  const API_URL = import.meta.env.VITE_API_URL;
  const token = localStorage.getItem('token');

  useEffect(() => {
    cargarListasPrecio();
    cargarItemsSinMLA();
    cargarAsignaciones();
    cargarUsuariosAsignables();
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

  // ========== FUNCIONES DE ASIGNACIONES ==========

  const cargarAsignaciones = async () => {
    try {
      const response = await axios.get(`${API_URL}/asignaciones/items-sin-mla`, {
        headers: { Authorization: `Bearer ${token}` },
        params: { estado: 'pendiente' }
      });
      setAsignaciones(response.data);
    } catch (error) {
      console.error('Error al cargar asignaciones:', error);
    }
  };

  const cargarUsuariosAsignables = async () => {
    try {
      const response = await axios.get(`${API_URL}/asignaciones/usuarios-asignables`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setUsuariosAsignables(response.data);
    } catch (error) {
      // Si no tiene permiso, no pasa nada — no muestra el dropdown
      console.error('Error al cargar usuarios asignables:', error);
    }
  };

  const getAsignacionesItem = (itemId) => {
    return asignaciones.filter(a => a.referencia_id === itemId);
  };

  const handleAsignar = (item) => {
    setItemParaAsignar(item);
    setListasParaAsignar([...item.listas_sin_mla]); // Pre-seleccionar todas las listas faltantes
    setUsuarioDestinoId('');
    setNotasAsignacion('');
    setShowAsignarModal(true);
  };

  const confirmarAsignar = async () => {
    if (!itemParaAsignar || listasParaAsignar.length === 0) return;

    setLoadingAsignacion(true);
    try {
      await axios.post(
        `${API_URL}/asignaciones/asignar`,
        {
          item_id: itemParaAsignar.item_id,
          listas: listasParaAsignar,
          usuario_id: usuarioDestinoId ? parseInt(usuarioDestinoId) : null,
          notas: notasAsignacion || null,
          listas_sin_mla: itemParaAsignar.listas_sin_mla,
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );

      setShowAsignarModal(false);
      setItemParaAsignar(null);
      cargarAsignaciones();
    } catch (error) {
      console.error('Error al asignar:', error);
      alert(error.response?.data?.detail || 'Error al asignar item');
    } finally {
      setLoadingAsignacion(false);
    }
  };

  const handleDesasignar = async (asignacionIds) => {
    if (!window.confirm(`¿Desasignar ${asignacionIds.length} asignación(es)?`)) return;

    try {
      await axios.post(
        `${API_URL}/asignaciones/desasignar`,
        { asignacion_ids: asignacionIds },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      cargarAsignaciones();
    } catch (error) {
      console.error('Error al desasignar:', error);
      alert(error.response?.data?.detail || 'Error al desasignar');
    }
  };

  const handleAsignarMasivo = () => {
    if (itemsSeleccionados.size === 0) return;
    setUsuarioDestinoId('');
    setNotasAsignacion('');
    setShowAsignarMasivoModal(true);
  };

  const confirmarAsignarMasivo = async () => {
    if (itemsSeleccionados.size === 0) return;

    setLoadingAsignacion(true);
    try {
      const items = [];
      for (const itemId of itemsSeleccionados) {
        const item = itemsSinMLA.find(i => i.item_id === itemId);
        if (item) {
          items.push({
            item_id: item.item_id,
            listas: item.listas_sin_mla, // Asignar TODAS las listas faltantes
            listas_sin_mla: item.listas_sin_mla,
          });
        }
      }

      await axios.post(
        `${API_URL}/asignaciones/asignar-masivo`,
        {
          items,
          usuario_id: usuarioDestinoId ? parseInt(usuarioDestinoId) : null,
          notas: notasAsignacion || null,
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );

      setShowAsignarMasivoModal(false);
      setItemsSeleccionados(new Set());
      setUltimoSeleccionado(null);
      cargarAsignaciones();
    } catch (error) {
      console.error('Error al asignar masivo:', error);
      alert(error.response?.data?.detail || 'Error al asignar masivamente');
    } finally {
      setLoadingAsignacion(false);
    }
  };

  const formatFechaHora = (isoString) => {
    if (!isoString) return '-';
    const fecha = new Date(isoString);
    return fecha.toLocaleDateString('es-AR', {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit'
    });
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

      // Filtro sin ninguna publicación (no tiene en NINGUNA lista)
      if (sinPublicaciones) {
        itemsFiltrados = itemsFiltrados.filter(item =>
          !item.listas_con_mla || item.listas_con_mla.length === 0
        );
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
    setSinPublicaciones(false);
    setPanelMarcasAbierto(false);
  };

  useEffect(() => {
    cargarItemsSinMLA();
  }, [marcasSeleccionadas, busqueda, listaPrecioFiltro, conStock, soloNuevos, sinPublicaciones]);

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
        <h1>{Icon.clipboard(22)} Items sin MLA</h1>
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
            {Icon.search(14)} Sin MLA ({itemsSinMLA.length})
          </button>
        )}
        {(tienePermiso('admin.gestionar_items_sin_mla_banlist') || tienePermiso('admin.gestionar_comparacion_banlist')) && (
          <button
            className={`tab-button ${activeTab === 'banlist' ? 'active' : ''}`}
            onClick={() => setActiveTab('banlist')}
          >
            {Icon.ban(14)} Banlist
          </button>
        )}
        {tienePermiso('admin.ver_comparacion_listas_ml') && (
          <button
            className={`tab-button ${activeTab === 'comparacion' ? 'active' : ''}`}
            onClick={() => setActiveTab('comparacion')}
          >
            {Icon.barChart(14)} Comparación Listas ({itemsComparacion.length})
          </button>
        )}
      </div>

      {/* Contenido del Tab 1: Items sin MLA */}
      {activeTab === 'sin-mla' && tienePermiso('admin.ver_items_sin_mla') && (
        <div className="tab-content">
          {/* Filtros */}
          <div className="filters-section">
            <div className="filter-group">
              <label>{Icon.search(13)} Buscar:</label>
              <input
                type="text"
                placeholder="Código o descripción"
                value={busqueda}
                onChange={(e) => setBusqueda(e.target.value)}
                className="filter-input"
              />
            </div>

            <div className="filter-group marcas-filter-container" style={{position: 'relative'}}>
              <label>{Icon.tag(13)} Marca:</label>
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
              <label>{Icon.dollar(13)} Lista faltante:</label>
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
              <label>{Icon.box(13)} Stock:</label>
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

            <div className="filter-group-toggles">
              <button
                onClick={() => setSoloNuevos(!soloNuevos)}
                className={`btn-toggle-filter ${soloNuevos ? 'active-warning' : ''}`}
              >
                {soloNuevos ? Icon.check(12) : Icon.sparkle(13)} Solo nuevos
              </button>

              <button
                onClick={() => setSinPublicaciones(!sinPublicaciones)}
                className={`btn-toggle-filter ${sinPublicaciones ? 'active-info' : ''}`}
              >
                {sinPublicaciones ? Icon.check(12) : Icon.alertCircle(13)} Sin publicaciones
              </button>
            </div>

            {(tienePermiso('admin.asignar_items_sin_mla') || tienePermiso('admin.gestionar_asignaciones')) && (
              <div className="filter-group">
                <label>{Icon.pin(13)} Asignación:</label>
                <select
                  value={filtroEstadoAsignacion}
                  onChange={(e) => setFiltroEstadoAsignacion(e.target.value)}
                  className="filter-select"
                >
                  <option value="">Todos</option>
                  <option value="asignado">Asignados</option>
                  <option value="sin-asignar">Sin asignar</option>
                </select>
              </div>
            )}

            {(tienePermiso('admin.asignar_items_sin_mla') || tienePermiso('admin.gestionar_asignaciones')) && filtroEstadoAsignacion === 'asignado' && (
              <>
                <div className="filter-group">
                  <label>{Icon.user(13)} Asignado a:</label>
                  <select
                    value={filtroAsignadoA}
                    onChange={(e) => setFiltroAsignadoA(e.target.value)}
                    className="filter-select"
                  >
                    <option value="">Todos</option>
                    {usuariosAsignables.map(u => (
                      <option key={u.id} value={u.id}>{u.nombre}</option>
                    ))}
                  </select>
                </div>

                <div className="filter-group">
                  <label>{Icon.edit(13)} Asignado por:</label>
                  <select
                    value={filtroAsignadoPor}
                    onChange={(e) => setFiltroAsignadoPor(e.target.value)}
                    className="filter-select"
                  >
                    <option value="">Todos</option>
                    {usuariosAsignables.map(u => (
                      <option key={u.id} value={u.id}>{u.nombre}</option>
                    ))}
                  </select>
                </div>
              </>
            )}

            <button onClick={limpiarFiltros} className="btn-tesla outline-subtle-danger sm" title="Limpiar todos los filtros">
              {Icon.trash(13)} Limpiar
            </button>
          </div>

          {/* Barra de acciones para multi-selección */}
          {itemsSeleccionados.size > 0 && (
            <div className="seleccion-bar">
              <span>{itemsSeleccionados.size} item(s) seleccionado(s)</span>
              <div className="seleccion-bar-actions">
                {(tienePermiso('admin.asignar_items_sin_mla') || tienePermiso('admin.gestionar_asignaciones')) && (
                  <button onClick={handleAsignarMasivo} className="btn-tesla outline-subtle-purple sm">
                    {Icon.pin(14)} Asignar seleccionados
                  </button>
                )}
                <button onClick={banearSeleccionados} className="btn-tesla outline-subtle-danger sm">
                  {Icon.ban(14)} Banear seleccionados
                </button>
              </div>
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
                    <th>Asignación</th>
                    <th>Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {(() => {
                    // Aplicar filtros de asignación sobre los items
                    let itemsFiltrados = sortedItems(itemsSinMLA);

                    if (filtroEstadoAsignacion === 'asignado') {
                      itemsFiltrados = itemsFiltrados.filter(item => {
                        const asigs = getAsignacionesItem(item.item_id);
                        if (asigs.length === 0) return false;
                        if (filtroAsignadoA && !asigs.some(a => a.usuario_id === parseInt(filtroAsignadoA))) return false;
                        if (filtroAsignadoPor && !asigs.some(a => a.asignado_por_id === parseInt(filtroAsignadoPor))) return false;
                        return true;
                      });
                    } else if (filtroEstadoAsignacion === 'sin-asignar') {
                      itemsFiltrados = itemsFiltrados.filter(item => getAsignacionesItem(item.item_id).length === 0);
                    }

                    if (itemsFiltrados.length === 0) {
                      return (
                        <tr>
                          <td colSpan="11" className="no-data">
                            No hay items sin MLA con los filtros aplicados
                          </td>
                        </tr>
                      );
                    }

                    return itemsFiltrados.map((item) => {
                      const asignacionesItem = getAsignacionesItem(item.item_id);
                      const tieneAsignacion = asignacionesItem.length > 0;

                      return (
                        <tr
                          key={item.item_id}
                          className={`${itemsSeleccionados.has(item.item_id) ? 'fila-seleccionada' : ''} ${tieneAsignacion ? 'fila-asignada' : ''}`}
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
                                {item.listas_sin_mla.map((lista, idx) => {
                                  const asigLista = asignacionesItem.find(a => a.subtipo === lista);
                                  return (
                                    <span
                                      key={idx}
                                      className={`badge ${asigLista ? 'badge-asignada' : 'badge-error'}`}
                                      title={asigLista ? `Asignado a ${asigLista.usuario_nombre} por ${asigLista.asignado_por_nombre} - ${formatFechaHora(asigLista.fecha_asignacion)}` : ''}
                                    >
                                      {asigLista && Icon.pin(11)}{lista}
                                    </span>
                                  );
                                })}
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
                          <td className="asignacion-cell">
                            {tieneAsignacion ? (
                              <div className="asignacion-info">
                                {asignacionesItem.map(a => (
                                  <div key={a.id} className="asignacion-detalle">
                                    <span className="asignacion-usuario" title={`Asignado por ${a.asignado_por_nombre}`}>
                                      {Icon.user(12)} {a.usuario_nombre}
                                    </span>
                                    <span className="asignacion-fecha">
                                      {formatFechaHora(a.fecha_asignacion)}
                                    </span>
                                    <span className="asignacion-por" title="Asignado por">
                                      {Icon.edit(11)} {a.asignado_por_nombre}
                                    </span>
                                    <button
                                      onClick={() => handleDesasignar([a.id])}
                                      className="btn-desasignar-mini"
                                      title="Desasignar"
                                    >
                                      {Icon.x(12)}
                                    </button>
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <span className="sin-asignar">—</span>
                            )}
                          </td>
                          <td className="acciones-cell">
                            <button
                              onClick={() => { setProductoInfoId(item.item_id); setMostrarModalInfo(true); }}
                              className="btn-tesla outline-subtle-primary icon-only sm"
                              title="Ver información del producto"
                              aria-label="Ver información del producto"
                            >
                              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>
                            </button>
                            {(tienePermiso('admin.asignar_items_sin_mla') || tienePermiso('admin.gestionar_asignaciones')) && (
                              <button
                                onClick={() => handleAsignar(item)}
                                className="btn-tesla outline-subtle-primary icon-only sm"
                                title="Asignar listas"
                                aria-label="Asignar listas"
                              >
                                <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/></svg>
                              </button>
                            )}
                            <button
                              onClick={() => handleBanear(item)}
                              className="btn-tesla outline-subtle-danger icon-only sm"
                              title="Agregar a banlist"
                              aria-label="Agregar a banlist"
                            >
                              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg>
                            </button>
                          </td>
                        </tr>
                      );
                    });
                  })()}
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
                {Icon.search(14)} Items sin MLA ({itemsBaneados.length})
              </button>
            )}
            {tienePermiso('admin.gestionar_comparacion_banlist') && (
              <button
                className={`banlist-selector-btn ${banlistActiva === 'comparacion' ? 'active' : ''}`}
                onClick={() => { setBanlistActiva('comparacion'); setOrdenColumnas([]); }}
              >
                {Icon.barChart(14)} Comparación ({comparacionBaneados.length})
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
                  <label>{Icon.search(13)} Buscar:</label>
                  <input
                    type="text"
                    placeholder="Código o descripción"
                    value={busquedaBanlist}
                    onChange={(e) => setBusquedaBanlist(e.target.value)}
                    className="filter-input"
                  />
                </div>

                <div className="filter-group marcas-filter-container" style={{position: 'relative'}}>
                  <label>{Icon.tag(13)} Marca:</label>
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

                <button
                  onClick={() => setSoloNuevosBanlist(!soloNuevosBanlist)}
                  className={`btn-toggle-filter ${soloNuevosBanlist ? 'active-warning' : ''}`}
                >
                  {soloNuevosBanlist ? Icon.check(12) : Icon.sparkle(13)} Solo nuevos
                </button>

                <button onClick={limpiarFiltrosBanlist} className="btn-tesla outline-subtle-danger sm" title="Limpiar todos los filtros">
                  {Icon.trash(13)} Limpiar
                </button>
              </div>

              {/* Barra de acciones para multi-selección */}
              {baneadosSeleccionados.size > 0 && (
                <div className="seleccion-bar">
                  <span>{baneadosSeleccionados.size} item(s) seleccionado(s)</span>
                  <button onClick={desbanearSeleccionados} className="btn-tesla outline-subtle-success sm">
                    {Icon.checkCircle(14)} Desbanear seleccionados
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
                                className="btn-tesla outline-subtle-success xs"
                                title="Quitar de banlist"
                              >
                                {Icon.checkCircle(12)} Desbanear
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
                  <label>{Icon.search(13)} Buscar:</label>
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
                  <button onClick={desbanearComparacionSeleccionados} className="btn-tesla outline-subtle-success sm">
                    {Icon.checkCircle(14)} Desbanear seleccionados
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
                                className="btn-tesla outline-subtle-success xs"
                                title="Quitar de banlist"
                              >
                                {Icon.checkCircle(12)} Desbanear
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
              <button onClick={banearComparacionSeleccionados} className="btn-tesla outline-subtle-danger sm">
                {Icon.ban(14)} Banear seleccionados
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
                              className="btn-tesla outline-subtle-danger xs"
                              title="Agregar a banlist"
                            >
                              {Icon.ban(12)} Banear
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
            <h3>{Icon.ban(18)} Agregar a Banlist</h3>
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
              <button onClick={confirmarBanear} className="btn-tesla outline-subtle-primary">
                Confirmar
              </button>
              <button onClick={() => setShowMotivoModal(false)} className="btn-tesla outline-subtle-danger">
                Cancelar
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal de asignación individual */}
      {showAsignarModal && itemParaAsignar && (
        <div className="modal-overlay" onClick={() => setShowAsignarModal(false)}>
          <div className="modal-content modal-asignacion" onClick={(e) => e.stopPropagation()}>
            <h3>{Icon.pin(18)} Asignar Item</h3>
            <p>
              <strong>Item:</strong> {itemParaAsignar.item_id} - {itemParaAsignar.descripcion}
            </p>
            <p>
              <strong>Marca:</strong> {itemParaAsignar.marca}
            </p>

            <div className="form-group">
              <label>Seleccionar listas a asignar:</label>
              <div className="listas-checkboxes">
                {itemParaAsignar.listas_sin_mla.map((lista) => {
                  const yaAsignada = asignaciones.some(
                    a => a.referencia_id === itemParaAsignar.item_id && a.subtipo === lista
                  );
                  return (
                    <label key={lista} className={`lista-checkbox ${yaAsignada ? 'lista-ya-asignada' : ''}`}>
                      <input
                        type="checkbox"
                        checked={listasParaAsignar.includes(lista)}
                        disabled={yaAsignada}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setListasParaAsignar([...listasParaAsignar, lista]);
                          } else {
                            setListasParaAsignar(listasParaAsignar.filter(l => l !== lista));
                          }
                        }}
                      />
                      <span className={`badge ${yaAsignada ? 'badge-asignada' : 'badge-error'}`}>
                        {lista}
                      </span>
                      {yaAsignada && (
                        <span className="ya-asignada-label">
                          (asignado a {asignaciones.find(a => a.referencia_id === itemParaAsignar.item_id && a.subtipo === lista)?.usuario_nombre})
                        </span>
                      )}
                    </label>
                  );
                })}
              </div>
            </div>

            {tienePermiso('admin.gestionar_asignaciones') && (
              <div className="form-group">
                <label>Asignar a:</label>
                <select
                  value={usuarioDestinoId}
                  onChange={(e) => setUsuarioDestinoId(e.target.value)}
                  className="filter-select"
                >
                  <option value="">A mí mismo</option>
                  {usuariosAsignables.map(u => (
                    <option key={u.id} value={u.id}>{u.nombre}</option>
                  ))}
                </select>
              </div>
            )}

            <div className="form-group">
              <label>Notas (opcional):</label>
              <textarea
                value={notasAsignacion}
                onChange={(e) => setNotasAsignacion(e.target.value)}
                placeholder="Ej: Prioridad alta, producto nuevo, etc."
                rows="3"
                className="motivo-textarea"
              />
            </div>

            <div className="modal-actions">
              <button
                onClick={confirmarAsignar}
                className="btn-tesla outline-subtle-primary"
                disabled={listasParaAsignar.length === 0 || loadingAsignacion}
              >
                {loadingAsignacion ? 'Asignando...' : `Asignar ${listasParaAsignar.length} lista(s)`}
              </button>
              <button onClick={() => setShowAsignarModal(false)} className="btn-tesla outline-subtle-danger">
                Cancelar
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal de asignación masiva */}
      {showAsignarMasivoModal && (
        <div className="modal-overlay" onClick={() => setShowAsignarMasivoModal(false)}>
          <div className="modal-content modal-asignacion" onClick={(e) => e.stopPropagation()}>
            <h3>{Icon.pin(18)} Asignar {itemsSeleccionados.size} Items</h3>
            <p className="tab-description">
              Se asignarán TODAS las listas faltantes de cada item seleccionado.
            </p>

            {tienePermiso('admin.gestionar_asignaciones') && (
              <div className="form-group">
                <label>Asignar a:</label>
                <select
                  value={usuarioDestinoId}
                  onChange={(e) => setUsuarioDestinoId(e.target.value)}
                  className="filter-select"
                >
                  <option value="">A mí mismo</option>
                  {usuariosAsignables.map(u => (
                    <option key={u.id} value={u.id}>{u.nombre}</option>
                  ))}
                </select>
              </div>
            )}

            <div className="form-group">
              <label>Notas (opcional):</label>
              <textarea
                value={notasAsignacion}
                onChange={(e) => setNotasAsignacion(e.target.value)}
                placeholder="Ej: Lote para publicar esta semana"
                rows="3"
                className="motivo-textarea"
              />
            </div>

            <div className="modal-actions">
              <button
                onClick={confirmarAsignarMasivo}
                className="btn-tesla outline-subtle-primary"
                disabled={loadingAsignacion}
              >
                {loadingAsignacion ? 'Asignando...' : `Asignar ${itemsSeleccionados.size} item(s)`}
              </button>
              <button onClick={() => setShowAsignarMasivoModal(false)} className="btn-tesla outline-subtle-danger">
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
            <h3>{Icon.ban(18)} Banear de Comparación</h3>
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
              <button onClick={confirmarBanearComparacion} className="btn-tesla outline-subtle-primary">
                Confirmar
              </button>
              <button onClick={() => setShowComparacionMotivoModal(false)} className="btn-tesla outline-subtle-danger">
                Cancelar
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal de información de producto */}
      <ModalInfoProducto
        isOpen={mostrarModalInfo}
        onClose={() => setMostrarModalInfo(false)}
        itemId={productoInfoId}
      />
    </div>
  );
};

export default ItemsSinMLA;
