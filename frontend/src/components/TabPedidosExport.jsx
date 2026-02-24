import { useState, useEffect, useCallback } from 'react';
import { Package, Tag, ShoppingCart, Phone, Pencil, AlertTriangle, Printer, RefreshCw, X, Loader2, Save, Trash2, ClipboardList, Lightbulb, FileText, Truck, Search } from 'lucide-react';
import api from '../services/api';
import { useToast } from '../hooks/useToast';
import Toast from './Toast';
import styles from './TabPedidosExport.module.css';

// Constantes de user_id del ERP
const USER_ID_TIENDANUBE = 50021;
const USER_ID_VENDEDOR_ML = 50006;
const USER_ID_MERCADOLIBRE = 50001;

export default function TabPedidosExport() {
  const [pedidos, setPedidos] = useState([]);
  const [estadisticas, setEstadisticas] = useState(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [pedidoSeleccionado, setPedidoSeleccionado] = useState(null);
  const [editandoDireccion, setEditandoDireccion] = useState(false);
  const [direccionForm, setDireccionForm] = useState({
    direccion: '',
    ciudad: '',
    provincia: '',
    codigo_postal: '',
    telefono: '',
    destinatario: '',
    notas: ''
  });
  
  // Etiquetas
  const [mostrarModalEtiqueta, setMostrarModalEtiqueta] = useState(false);
  const [numBultos, setNumBultos] = useState(1);
  const [tipoDomicilio, setTipoDomicilio] = useState('Particular');
  const [tipoEnvio, setTipoEnvio] = useState('');
  const [generandoEtiqueta, setGenerandoEtiqueta] = useState(false);
  
  // Modal Enviar a Flex (completo)
  const [showFlexModal, setShowFlexModal] = useState(false);
  const [flexForm, setFlexForm] = useState({
    fecha_envio: new Date().toISOString().split('T')[0],
    receiver_name: '',
    street_name: '',
    street_number: '',
    zip_code: '',
    city_name: '',
    logistica_id: '',
    comment: '',
  });
  const [flexLoading, setFlexLoading] = useState(false);
  const [flexCordon, setFlexCordon] = useState(null);
  const [logisticas, setLogisticas] = useState([]);
  const [sucursales, setSucursales] = useState([]);
  
  // Bulk print
  const [pedidosSeleccionados, setPedidosSeleccionados] = useState([]);
  
  // Filtros
  const [soloActivos, setSoloActivos] = useState(true);
  const [soloTN, setSoloTN] = useState(false);
  const [soloML, setSoloML] = useState(false);
  const [soloOtros, setSoloOtros] = useState(false);
  const [soloSinDireccion, setSoloSinDireccion] = useState(false);
  const [excluirML, setExcluirML] = useState(true);
  const [userIdFiltro, setUserIdFiltro] = useState('');
  const [provinciaFiltro, setProvinciaFiltro] = useState('');
  const [search, setSearch] = useState('');
  
  // Listas para dropdowns
  const [usuariosDisponibles, setUsuariosDisponibles] = useState([]);
  const [provinciasDisponibles, setProvinciasDisponibles] = useState([]);

  // Toast notifications (reemplaza alert())
  const { toast, showToast, hideToast } = useToast(5000);

  // Confirm dialog (reemplaza confirm())
  const [confirmDialog, setConfirmDialog] = useState(null);

  const pedirConfirmacion = (title, message) =>
    new Promise((resolve) => {
      setConfirmDialog({
        title,
        message,
        onConfirm: () => {
          setConfirmDialog(null);
          resolve(true);
        },
        onCancel: () => {
          setConfirmDialog(null);
          resolve(false);
        },
      });
    });
  
  const cargarEstadisticas = useCallback(async () => {
    try {
      // Usar estadísticas del endpoint local con ssos_id=20 (En Preparación)
      // dias_atras=60 por defecto (últimos 60 días)
      const response = await api.get(
        '/pedidos-local/estadisticas', { params: { ssos_id: 20, dias_atras: 60 } }
      );
      setEstadisticas(response.data);
    } catch (error) {
      console.error('Error cargando estadísticas:', error);
    }
  }, []);

  const cargarUsuariosDisponibles = useCallback(async () => {
    try {
      const response = await api.get('/pedidos-simple/usuarios-disponibles');
      setUsuariosDisponibles(response.data);
    } catch (error) {
      console.error('Error cargando usuarios:', error);
    }
  }, []);

  const cargarProvinciasDisponibles = useCallback(async () => {
    try {
      const response = await api.get('/pedidos-simple/provincias-disponibles');
      setProvinciasDisponibles(response.data);
    } catch (error) {
      console.error('Error cargando provincias:', error);
    }
  }, []);

  const cargarPedidos = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      // Usar ssos_id=20 (En Preparación) cuando solo_activos está activo
      if (soloActivos) {
        params.append('ssos_id', '20');
      }
      // Filtrar por últimos 60 días por defecto
      params.append('dias_atras', '60');
      if (soloTN) params.append('solo_tn', 'true');
      if (soloML) params.append('solo_ml', 'true');
      if (soloSinDireccion) params.append('solo_sin_direccion', 'true');
      if (userIdFiltro) params.append('user_id', userIdFiltro);
      if (provinciaFiltro) params.append('provincia', provinciaFiltro);
      if (search) params.append('buscar', search);
      params.append('limit', '500');

      const response = await api.get(
        `/pedidos-local?${params.toString()}`
      );
      
      // Filtros client-side
      let pedidosFiltrados = response.data;
      if (soloOtros) {
        pedidosFiltrados = pedidosFiltrados.filter(p => 
          p.user_id !== USER_ID_TIENDANUBE && p.user_id !== USER_ID_VENDEDOR_ML
        );
      }
      if (excluirML && !soloML) {
        pedidosFiltrados = pedidosFiltrados.filter(p => p.user_id !== USER_ID_VENDEDOR_ML);
      }
      
      setPedidos(pedidosFiltrados);
    } catch (error) {
      console.error('Error cargando pedidos:', error);
      showToast('Error cargando pedidos', 'error');
    } finally {
      setLoading(false);
    }
  }, [soloActivos, soloTN, soloML, soloOtros, excluirML, soloSinDireccion, userIdFiltro, provinciaFiltro, search]);

  const sincronizarPedidos = async () => {
    const confirmed = await pedirConfirmacion(
      'Sincronizar pedidos',
      'Sincronizar pedidos desde el ERP y limpiar archivados. Puede tardar 1-2 minutos.',
    );
    if (!confirmed) return;

    setSyncing(true);
    try {
      const response = await api.post(
        '/pedidos-local/sincronizar',
        {},
        { timeout: 120000 } // 2 minutos timeout
      );
      
      const headers = response.data.headers_archivados_limpiados || 0;
      const details = response.data.details_archivados_limpiados || 0;
      
      showToast(`Sincronización OK: ${headers} archivados limpiados, ${details} detalles limpiados`);
      
      await cargarPedidos();
      await cargarEstadisticas();
    } catch (error) {
      console.error('Error en sincronización:', error);
      showToast('Error en sincronización: ' + (error.response?.data?.detail || error.message), 'error');
    } finally {
      setSyncing(false);
    }
  };

  // Obtener dirección con prioridad: override > TN > ERP > facturación (cliente)
  const getDireccionDisplay = (pedido) => {
    const direccion = pedido.override_shipping_address || pedido.tiendanube_shipping_address || pedido.soh_deliveryaddress || pedido.cust_address;
    const fromCustomer = !pedido.override_shipping_address && !pedido.tiendanube_shipping_address && !pedido.soh_deliveryaddress && !!pedido.cust_address;
    return {
      direccion,
      ciudad: pedido.override_shipping_city || pedido.tiendanube_shipping_city || (fromCustomer ? pedido.cust_city : null),
      provincia: pedido.override_shipping_province || pedido.tiendanube_shipping_province,
      codigo_postal: pedido.override_shipping_zipcode || pedido.tiendanube_shipping_zipcode || (fromCustomer ? pedido.cust_zip : null),
      telefono: pedido.override_shipping_phone || pedido.tiendanube_shipping_phone || (fromCustomer ? pedido.cust_phone : null),
      destinatario: pedido.override_shipping_recipient || pedido.tiendanube_recipient_name,
      hasOverride: !!pedido.override_shipping_address,
      fromCustomer,
    };
  };

  const abrirEditarDireccion = (pedido) => {
    const dir = getDireccionDisplay(pedido);
    setDireccionForm({
      direccion: dir.direccion || '',
      ciudad: dir.ciudad || '',
      provincia: dir.provincia || '',
      codigo_postal: dir.codigo_postal || '',
      telefono: dir.telefono || '',
      destinatario: dir.destinatario || '',
      notas: pedido.override_notes || ''
    });
    setEditandoDireccion(true);
  };

  const guardarDireccion = async () => {
    try {
      await api.put(
        `/pedidos-simple/${pedidoSeleccionado.soh_id}/override-shipping`,
        direccionForm
      );
      
      showToast('Dirección actualizada correctamente');
      setEditandoDireccion(false);
      await cargarPedidos();
      
      // Actualizar pedido seleccionado
      const pedidoActualizado = await api.get(
        '/pedidos-simple', { params: { solo_activos: true, limit: 1 } }
      );
      const updated = pedidoActualizado.data.find(p => p.soh_id === pedidoSeleccionado.soh_id);
      if (updated) setPedidoSeleccionado(updated);
      
    } catch (error) {
      console.error('Error guardando dirección:', error);
      showToast('Error guardando dirección: ' + (error.response?.data?.detail || error.message), 'error');
    }
  };

  const eliminarOverride = async () => {
    const confirmed = await pedirConfirmacion(
      'Eliminar override',
      'Eliminar override y volver a los datos originales de dirección.',
    );
    if (!confirmed) return;
    
    try {
      await api.delete(
        `/pedidos-simple/${pedidoSeleccionado.soh_id}/override-shipping`
      );
      
      showToast('Override eliminado, mostrando datos originales');
      setEditandoDireccion(false);
      await cargarPedidos();
      
    } catch (error) {
      console.error('Error eliminando override:', error);
      showToast('Error: ' + (error.response?.data?.detail || error.message), 'error');
    }
  };

  const generarEtiqueta = async () => {
    if (numBultos < 1 || numBultos > 10) {
      showToast('El número de bultos debe estar entre 1 y 10', 'error');
      return;
    }

    setGenerandoEtiqueta(true);
    try {
      const params = { 
        num_bultos: numBultos,
        tipo_domicilio_manual: tipoDomicilio
      };
      
      // Si hay tipo de envío manual, agregarlo
      if (tipoEnvio.trim()) {
        params.tipo_envio_manual = tipoEnvio;
      }

      const response = await api.get(
        `/pedidos-simple/${pedidoSeleccionado.soh_id}/etiqueta-zpl`,
        { params: params, responseType: 'blob' }
      );

      // Crear blob y descargar
      const blob = new Blob([response.data], { type: 'text/plain' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `etiqueta_pedido_${pedidoSeleccionado.soh_id}.txt`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);

      setMostrarModalEtiqueta(false);
      showToast(`Etiqueta descargada: ${numBultos} bulto${numBultos > 1 ? 's' : ''}`);
    } catch (error) {
      console.error('Error generando etiqueta:', error);
      showToast('Error generando etiqueta: ' + (error.response?.data?.detail || error.message), 'error');
    } finally {
      setGenerandoEtiqueta(false);
    }
  };

  const getUserLabel = (pedido) => {
    // Usar user_name del backend (viene desde tb_user)
    // Si no existe, fallback a user_id
    return pedido.user_name || `User ${pedido.user_id}`;
  };

  const toggleSeleccionPedido = (sohId) => {
    setPedidosSeleccionados(prev => 
      prev.includes(sohId) 
        ? prev.filter(id => id !== sohId)
        : [...prev, sohId]
    );
  };

  const toggleSeleccionarTodos = () => {
    if (pedidosSeleccionados.length === pedidos.length) {
      setPedidosSeleccionados([]);
    } else {
      setPedidosSeleccionados(pedidos.map(p => p.soh_id));
    }
  };

  const actualizarBultosDomicilio = async (sohId, numBultos, tipoDomicilio) => {
    try {
      await api.put(
        `/pedidos-simple/${sohId}/bultos-domicilio`,
        null,
        { params: { num_bultos: numBultos, tipo_domicilio: tipoDomicilio } }
      );
      
      // Actualizar en el estado local
      setPedidos(prev => prev.map(p => 
        p.soh_id === sohId 
          ? { ...p, override_num_bultos: numBultos, override_tipo_domicilio: tipoDomicilio }
          : p
      ));
    } catch (error) {
      console.error('Error actualizando bultos/domicilio:', error);
      showToast('Error actualizando configuración', 'error');
    }
  };

  const generarEtiquetasBulk = async () => {
    if (pedidosSeleccionados.length === 0) {
      showToast('Seleccioná al menos un pedido', 'error');
      return;
    }

    const confirmed = await pedirConfirmacion(
      'Generar etiquetas',
      `Generar etiquetas para ${pedidosSeleccionados.length} pedido${pedidosSeleccionados.length > 1 ? 's' : ''}. Se usará el número de bultos y tipo de domicilio configurado en cada fila.`,
    );
    if (!confirmed) return;

    setGenerandoEtiqueta(true);
    try {
      let allZpl = '';
      
      for (const sohId of pedidosSeleccionados) {
        // Buscar el pedido en la lista para obtener sus valores de bultos/domicilio
        const pedido = pedidos.find(p => p.soh_id === sohId);
        if (!pedido) continue;

        const params = new URLSearchParams();
        // Usar override si existe, sino default 1 bulto
        params.append('num_bultos', pedido.override_num_bultos || 1);
        if (pedido.override_tipo_domicilio) {
          params.append('tipo_domicilio_manual', pedido.override_tipo_domicilio);
        }

        const response = await api.get(
          `/pedidos-simple/${sohId}/etiqueta-zpl`,
          { params: params, responseType: 'text' }
        );

        allZpl += response.data + '\n\n';
      }

      // Descargar archivo combinado
      const blob = new Blob([allZpl], { type: 'text/plain' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `etiquetas_bulk_${pedidosSeleccionados.length}_pedidos.txt`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);

      setPedidosSeleccionados([]);
      showToast(`Etiquetas descargadas: ${pedidosSeleccionados.length} pedido${pedidosSeleccionados.length > 1 ? 's' : ''}`);
    } catch (error) {
      console.error('Error generando etiquetas bulk:', error);
      showToast('Error generando etiquetas: ' + (error.response?.data?.detail || error.message), 'error');
    } finally {
      setGenerandoEtiqueta(false);
    }
  };

  // ── Envío rápido (inline, usa datos del pedido directamente) ─────────

  const enviarAFlexRapido = async (pedido) => {
    const dir = getDireccionDisplay(pedido);
    if (!dir.direccion) {
      showToast('Este pedido no tiene dirección de envío', 'error');
      return;
    }

    setFlexLoading(true);
    try {
      const { data } = await api.post('/etiquetas-envio/desde-pedido', {
        fecha_envio: new Date().toISOString().split('T')[0],
        soh_id: pedido.soh_id,
        bra_id: pedido.bra_id,
        receiver_name: dir.destinatario || pedido.nombre_cliente || 'Sin nombre',
        street_name: dir.direccion,
        street_number: 'S/N',
        zip_code: dir.codigo_postal || '0000',
        city_name: dir.ciudad || 'Sin ciudad',
        comment: `Pedido GBP:${pedido.soh_id} - Envío rápido desde Pedidos Pendientes`,
      });

      showToast(`Envío flex creado: ${data.shipping_id}${data.cordon ? ` (${data.cordon})` : ''}`);
    } catch (error) {
      console.error('Error enviando a flex:', error);
      showToast('Error creando envío flex: ' + (error.response?.data?.detail || error.message), 'error');
    } finally {
      setFlexLoading(false);
    }
  };

  // ── Flex modal helpers (envío manual completo) ─────────────────────

  const handleFlexFormChange = (field, value) => {
    setFlexForm(prev => ({ ...prev, [field]: value }));
  };

  const resolverCordonPorCP = async (zipCode) => {
    if (!zipCode || zipCode.length < 4) {
      setFlexCordon(null);
      return;
    }
    try {
      const { data } = await api.get(`/codigos-postales/${zipCode}/cordon`);
      setFlexCordon(data.cordon || null);
    } catch {
      setFlexCordon(null);
    }
  };

  const abrirFlexModal = async (pedido) => {
    const dir = getDireccionDisplay(pedido);

    // Separar calle y número si vienen juntos
    let streetName = dir.direccion || '';
    let streetNumber = '';
    if (streetName) {
      const match = streetName.match(/^(.+?)\s+(\d+\s*)$/);
      if (match) {
        streetName = match[1].trim();
        streetNumber = match[2].trim();
      }
    }

    setFlexForm({
      fecha_envio: new Date().toISOString().split('T')[0],
      receiver_name: dir.destinatario || pedido.nombre_cliente || '',
      street_name: streetName,
      street_number: streetNumber,
      zip_code: dir.codigo_postal || '',
      city_name: dir.ciudad || '',
      logistica_id: '',
      comment: '',
    });
    setFlexCordon(null);
    setShowFlexModal(true);

    // Resolver cordón si hay CP
    if (dir.codigo_postal) {
      resolverCordonPorCP(dir.codigo_postal);
    }

    // Cargar logísticas y sucursales si no están cargadas
    if (logisticas.length === 0) {
      try {
        const { data } = await api.get('/logisticas?incluir_inactivas=false');
        setLogisticas(data);
      } catch {
        // silently fail
      }
    }
    if (sucursales.length === 0) {
      try {
        const { data } = await api.get('/clientes/filtros/sucursales');
        setSucursales(data);
      } catch {
        // silently fail
      }
    }
  };

  const guardarEnvioFlex = async () => {
    if (!flexForm.receiver_name.trim()) {
      showToast('Ingresá el nombre del destinatario', 'error');
      return;
    }
    if (!flexForm.zip_code.trim()) {
      showToast('Ingresá el código postal', 'error');
      return;
    }

    setFlexLoading(true);
    try {
      const payload = {
        fecha_envio: flexForm.fecha_envio,
        soh_id: pedidoSeleccionado.soh_id,
        bra_id: pedidoSeleccionado.bra_id,
        receiver_name: flexForm.receiver_name.trim(),
        street_name: flexForm.street_name.trim() || 'S/N',
        street_number: flexForm.street_number.trim() || 'S/N',
        zip_code: flexForm.zip_code.trim(),
        city_name: flexForm.city_name.trim() || 'Sin ciudad',
        comment: flexForm.comment.trim() || null,
        logistica_id: flexForm.logistica_id ? parseInt(flexForm.logistica_id, 10) : null,
      };

      const { data } = await api.post('/etiquetas-envio/desde-pedido', payload);

      setShowFlexModal(false);
      showToast(`Envío flex creado: ${data.shipping_id}${data.cordon ? ` (${data.cordon})` : ''}`);
    } catch (error) {
      console.error('Error creando envío flex:', error);
      showToast('Error creando envío flex: ' + (error.response?.data?.detail || error.message), 'error');
    } finally {
      setFlexLoading(false);
    }
  };

  useEffect(() => {
    cargarPedidos();
    cargarEstadisticas();
    cargarUsuariosDisponibles();
    cargarProvinciasDisponibles();
  }, [cargarPedidos, cargarEstadisticas, cargarUsuariosDisponibles, cargarProvinciasDisponibles]);

  return (
    <div className={styles.container}>
      {/* Header con estadísticas - diseño compacto */}
      <div className={styles.statsBar}>
        <div className={styles.statItem}>
          <span className={styles.statLabel}>TOTAL PEDIDOS</span>
          <span className={styles.statValue}>{estadisticas?.total_pedidos || 0}</span>
        </div>
        
        <div className={styles.statItem}>
          <span className={styles.statLabel}>TOTAL ITEMS</span>
          <span className={styles.statValue}>{estadisticas?.total_items || 0}</span>
        </div>
        
        <div className={styles.statItem}>
          <span className={styles.statLabel}>TIENDANUBE</span>
          <span className={styles.statValue}>{estadisticas?.con_tiendanube || 0}</span>
        </div>
        
        <div className={styles.statItem}>
          <span className={styles.statLabel}>SIN DIRECCIÓN</span>
          <span className={styles.statValue}>{estadisticas?.sin_direccion || 0}</span>
        </div>
        
        <div className={styles.statItem}>
          <span className={styles.statLabel}>ÚLTIMOS {estadisticas?.dias_filtro || 60} DÍAS</span>
          <span className={styles.statValue}>
            {estadisticas?.fecha_desde ? new Date(estadisticas.fecha_desde).toLocaleDateString('es-AR') : '-'}
          </span>
        </div>
      </div>

      {/* Barra de búsqueda full-width */}
      <div className={styles.searchBar}>
        <input
          type="text"
          placeholder="Buscar en todo (cliente, dirección, orden TN, ID pedido, provincia, ciudad...)"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className={styles.searchInput}
        />
      </div>

      {/* Filtros en una sola línea compacta */}
      <div className={styles.filtersUnified}>
        {/* Selects compactos */}
        <select
          value={userIdFiltro}
          onChange={(e) => {
            setUserIdFiltro(e.target.value);
            if (e.target.value) {
              setSoloTN(false);
              setSoloML(false);
              setSoloOtros(false);
            }
          }}
          className={styles.selectCompactFilter}
        >
          <option value="">Canal</option>
          {usuariosDisponibles.map(u => (
            <option key={u.user_id} value={u.user_id}>
              {u.user_name}
            </option>
          ))}
        </select>

        <select
          value={provinciaFiltro}
          onChange={(e) => setProvinciaFiltro(e.target.value)}
          className={styles.selectCompactFilter}
        >
          <option value="">Provincia</option>
          {provinciasDisponibles.map(p => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>

        {/* Toggles tipo btn-tesla con check */}
        <button
          onClick={() => setSoloActivos(!soloActivos)}
          className={`btn-tesla outline-subtle-primary sm ${soloActivos ? 'toggle-active' : ''}`}
        >
          {soloActivos ? '✓ ' : ''}Activos
        </button>

        <button
          onClick={() => {
            setSoloTN(!soloTN);
            if (!soloTN) { setSoloML(false); setSoloOtros(false); }
          }}
          className={`btn-tesla outline-subtle-primary sm ${soloTN ? 'toggle-active' : ''}`}
        >
          {soloTN ? '✓ ' : ''}TiendaNube
        </button>

        <button
          onClick={() => {
            setSoloML(!soloML);
            if (!soloML) { setSoloTN(false); setSoloOtros(false); setExcluirML(false); }
          }}
          className={`btn-tesla outline-subtle-primary sm ${soloML ? 'toggle-active' : ''}`}
        >
          {soloML ? '✓ ' : ''}MercadoLibre
        </button>

        <button
          onClick={() => {
            setSoloOtros(!soloOtros);
            if (!soloOtros) { setSoloTN(false); setSoloML(false); setUserIdFiltro(''); }
          }}
          className={`btn-tesla outline-subtle-primary sm ${soloOtros ? 'toggle-active' : ''}`}
        >
          {soloOtros ? '✓ ' : ''}Otros
        </button>

        <button
          onClick={() => setExcluirML(!excluirML)}
          className={`btn-tesla outline-subtle-primary sm ${excluirML ? 'toggle-active' : ''}`}
          title="Excluir pedidos del Vendedor ML (user_id 50006)"
        >
          {excluirML ? '✓ ' : ''}Excluir Vendedor ML
        </button>

        <button
          onClick={() => setSoloSinDireccion(!soloSinDireccion)}
          className={`btn-tesla outline-subtle-primary sm ${soloSinDireccion ? 'toggle-active' : ''}`}
        >
          {soloSinDireccion ? '✓ ' : ''}Sin Dirección
        </button>

        {/* Separador */}
        <div className={styles.filterSeparator} />

        {/* Acciones */}
        <button onClick={cargarPedidos} className="btn-tesla outline-subtle-primary sm">
          Filtrar
        </button>

        <button
          onClick={sincronizarPedidos}
          disabled={syncing}
          className="btn-tesla outline-subtle-success sm"
        >
          {syncing ? <><Loader2 size={14} className={styles.spinning} /> Sincronizando...</> : <><RefreshCw size={14} /> Sync ERP</>}
        </button>
      </div>

      {/* Bulk Actions */}
      {pedidosSeleccionados.length > 0 && (
        <div className={styles.bulkActions}>
          <button
            onClick={generarEtiquetasBulk}
            disabled={generandoEtiqueta}
            className="btn-tesla outline-subtle-primary sm"
          >
            {generandoEtiqueta ? <><Loader2 size={14} className={styles.spinning} /> Generando...</> : <><Printer size={14} /> Imprimir Etiquetas ({pedidosSeleccionados.length})</>}
          </button>
          <button
            onClick={() => setPedidosSeleccionados([])}
            className="btn-tesla outline-subtle-danger sm"
          >
            <X size={14} /> Limpiar Selección
          </button>
          <span className={styles.bulkCount}>
            {pedidosSeleccionados.length} seleccionados
          </span>
        </div>
      )}

      {/* Tabla de pedidos */}
      {loading ? (
        <div className={styles.loading}>Cargando pedidos...</div>
      ) : pedidos.length === 0 ? (
        <div className={styles.empty}>No hay pedidos con los filtros seleccionados</div>
      ) : (
        <div className={`table-container-tesla ${styles.tableShell}`}>
          <table className="table-tesla">
            <thead className="table-tesla-head">
              <tr>
                <th>
                  <input 
                    type="checkbox" 
                    checked={pedidosSeleccionados.length === pedidos.length && pedidos.length > 0}
                    onChange={toggleSeleccionarTodos}
                    title="Seleccionar todos"
                  />
                </th>
                <th>ID PEDIDO</th>
                <th>CÓDIGO</th>
                <th>CLIENTE</th>
                <th>ITEMS</th>
                <th>BULTOS</th>
                <th>TIPO</th>
                <th>ORDEN TN</th>
                <th>DIRECCIÓN DE ENVÍO</th>
                <th>FECHA ENVÍO</th>
                <th>ACCIONES</th>
              </tr>
            </thead>
            <tbody className="table-tesla-body">
              {pedidos.map((pedido) => (
                <tr 
                  key={pedido.soh_id}
                  className={styles.row}
                >
                  <td onClick={(e) => e.stopPropagation()}>
                    <input 
                      type="checkbox" 
                      checked={pedidosSeleccionados.includes(pedido.soh_id)}
                      onChange={() => toggleSeleccionPedido(pedido.soh_id)}
                    />
                  </td>
                  <td onClick={() => setPedidoSeleccionado(pedido)}>
                    <div className={styles.pedidoId}>
                      <strong>GBP: {pedido.soh_id}</strong>
                      {pedido.user_id && (
                        <div className={styles.userBadge}>
                          {getUserLabel(pedido)}
                        </div>
                      )}
                    </div>
                  </td>
                  
                  <td onClick={() => setPedidoSeleccionado(pedido)}>
                    <div className={styles.codigoInterno}>
                      {pedido.user_id === USER_ID_MERCADOLIBRE ? (
                        // MercadoLibre: mostrar soh_mlguia (shipping ID)
                        <span className={styles.codigoML} title="Shipping ID de ML">
                          <Package size={14} /> {pedido.soh_mlguia || pedido.soh_mlid || 'Sin ID'}
                        </span>
                      ) : (
                        // TiendaNube/Otros: mostrar codigo_envio_interno
                        <span className={styles.codigoTN} title="Código interno">
                          <Tag size={14} /> {pedido.codigo_envio_interno || `${pedido.bra_id}-${pedido.soh_id}`}
                        </span>
                      )}
                    </div>
                  </td>
                  
                  <td onClick={() => setPedidoSeleccionado(pedido)}>
                    <div className={styles.cliente}>
                      <strong>{pedido.nombre_cliente || 'Sin nombre'}</strong>
                      {pedido.cust_id && (
                        <div className={styles.clienteId}>ID: {pedido.cust_id}</div>
                      )}
                    </div>
                  </td>
                  
                  <td className={styles.textCenter} onClick={() => setPedidoSeleccionado(pedido)}>
                    <div className={styles.itemsBadge}>
                      {pedido.total_items} {pedido.total_items === 1 ? 'item' : 'items'}
                    </div>
                  </td>

                  {/* Bultos */}
                  <td className={styles.textCenter} onClick={(e) => e.stopPropagation()}>
                    <select
                      value={pedido.override_num_bultos || 1}
                      onChange={(e) => actualizarBultosDomicilio(pedido.soh_id, parseInt(e.target.value), pedido.override_tipo_domicilio)}
                      className={styles.selectCompact}
                    >
                      {[1,2,3,4,5,6,7,8,9,10].map(n => (
                        <option key={n} value={n}>{n}</option>
                      ))}
                    </select>
                  </td>

                  {/* Tipo Domicilio */}
                  <td className={styles.textCenter} onClick={(e) => e.stopPropagation()}>
                    <select
                      value={pedido.override_tipo_domicilio || 'Particular'}
                      onChange={(e) => actualizarBultosDomicilio(pedido.soh_id, pedido.override_num_bultos || 1, e.target.value)}
                      className={styles.selectCompact}
                    >
                      <option value="Particular">Part.</option>
                      <option value="Comercial">Com.</option>
                      <option value="Sucursal">Suc.</option>
                    </select>
                  </td>
                  
                  <td onClick={() => setPedidoSeleccionado(pedido)}>
                    {pedido.tiendanube_number ? (
                      <div className={styles.ordenTN}>
                        <div className={styles.ordenTNNumber}>
                          <ShoppingCart size={14} /> {pedido.tiendanube_number}
                        </div>
                        {pedido.ws_internalid && (
                          <div className={styles.ordenTNId}>ID: {pedido.ws_internalid}</div>
                        )}
                      </div>
                    ) : pedido.ws_internalid ? (
                      <div className={styles.ordenTNId}>TN #{pedido.ws_internalid}</div>
                    ) : (
                      <span className={styles.textMuted}>—</span>
                    )}
                  </td>
                  
                  <td onClick={() => setPedidoSeleccionado(pedido)}>
                    {(() => {
                      const dir = getDireccionDisplay(pedido);
                      return dir.direccion ? (
                        <div className={styles.direccion}>
                          {dir.hasOverride && (
                            <div className={styles.overrideBadgeSmall}><Pencil size={12} /></div>
                          )}
                          {dir.fromCustomer && (
                            <div className={styles.fallbackBadge} title="Dirección tomada de facturación del cliente">Dir. Facturación</div>
                          )}
                          <div>{dir.direccion}</div>
                          {dir.ciudad && (
                            <div className={styles.localidad}>
                              {dir.ciudad}{dir.provincia ? `, ${dir.provincia}` : ''}
                            </div>
                          )}
                          {dir.telefono && (
                            <div className={styles.telefono}>
                              <Phone size={12} /> {dir.telefono}
                            </div>
                          )}
                        </div>
                      ) : (
                        <span className={styles.sinDireccion}>Sin dirección</span>
                      );
                    })()}
                  </td>
                  
                  <td className={styles.textCenter} onClick={() => setPedidoSeleccionado(pedido)}>
                    {pedido.soh_deliverydate ? (
                      new Date(pedido.soh_deliverydate).toLocaleDateString('es-AR')
                    ) : (
                      <span className={styles.textMuted}>—</span>
                    )}
                  </td>

                  <td className={styles.textCenter} onClick={(e) => e.stopPropagation()}>
                    <button
                      onClick={() => setPedidoSeleccionado(pedido)}
                      className={`btn-tesla outline-subtle-primary sm ${styles.btnDetalle}`}
                    >
                      Ver Detalle
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Modal de detalle */}
      {pedidoSeleccionado && (
        <div className={styles.modal} onClick={() => setPedidoSeleccionado(null)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h2>Pedido GBP: {pedidoSeleccionado.soh_id}</h2>
              <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                <button
                  onClick={() => {
                    // Usar los valores del pedido (override si existe, sino defaults)
                    setNumBultos(pedidoSeleccionado.override_num_bultos || 1);
                    setTipoDomicilio(pedidoSeleccionado.override_tipo_domicilio || 'Particular');
                    setTipoEnvio('');
                    setMostrarModalEtiqueta(true);
                  }}
                  className={`btn-tesla outline-subtle-primary sm ${styles.btnPrintLabel}`}
                  title="Imprimir etiqueta de envío"
                >
                  <Printer size={14} /> Imprimir Etiqueta
                </button>
                <button 
                  onClick={() => setPedidoSeleccionado(null)}
                  className={`btn-tesla outline-subtle-primary sm icon-only ${styles.btnClose}`}
                  aria-label="Cerrar modal"
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            <div className={styles.modalBody}>
              <div className={styles.infoGrid}>
                <div className={styles.infoSection}>
                  <h3>Información del Cliente</h3>
                  <div className={styles.infoRow}>
                    <strong>Cliente GBP:</strong> {pedidoSeleccionado.nombre_cliente || 'Sin nombre'}
                  </div>
                  <div className={styles.infoRow}>
                    <strong>ID Cliente:</strong> {pedidoSeleccionado.cust_id || 'N/A'}
                  </div>
                  <div className={styles.infoRow}>
                    <strong>Canal:</strong> {getUserLabel(pedidoSeleccionado)}
                  </div>
                  {pedidoSeleccionado.tiendanube_recipient_name && (
                    <div className={styles.infoRow}>
                      <strong>Destinatario TN:</strong> {pedidoSeleccionado.tiendanube_recipient_name}
                    </div>
                  )}
                </div>

                <div className={styles.infoSection}>
                  <h3>Configuración de Etiquetas</h3>
                  <div className={styles.infoRow}>
                    <strong>Número de Bultos:</strong>
                    <select
                      value={pedidoSeleccionado.override_num_bultos || 1}
                      onChange={(e) => {
                        const newValue = parseInt(e.target.value);
                        actualizarBultosDomicilio(
                          pedidoSeleccionado.soh_id, 
                          newValue, 
                          pedidoSeleccionado.override_tipo_domicilio
                        );
                        setPedidoSeleccionado({
                          ...pedidoSeleccionado,
                          override_num_bultos: newValue
                        });
                      }}
                      className={styles.selectInModal}
                    >
                      {[1,2,3,4,5,6,7,8,9,10].map(n => (
                        <option key={n} value={n}>{n} bulto{n > 1 ? 's' : ''}</option>
                      ))}
                    </select>
                  </div>
                  <div className={styles.infoRow}>
                    <strong>Tipo de Domicilio:</strong>
                    <select
                      value={pedidoSeleccionado.override_tipo_domicilio || 'Particular'}
                      onChange={(e) => {
                        const newValue = e.target.value;
                        actualizarBultosDomicilio(
                          pedidoSeleccionado.soh_id, 
                          pedidoSeleccionado.override_num_bultos || 1, 
                          newValue
                        );
                        setPedidoSeleccionado({
                          ...pedidoSeleccionado,
                          override_tipo_domicilio: newValue
                        });
                      }}
                      className={styles.selectInModal}
                    >
                      <option value="Particular">Particular</option>
                      <option value="Comercial">Comercial</option>
                      <option value="Sucursal">Sucursal</option>
                    </select>
                  </div>
                  <div className={styles.infoRow} style={{ fontSize: '12px', color: 'var(--text-secondary)', marginTop: '8px' }}>
                    <Lightbulb size={12} /> Estos valores se guardan automáticamente y se usan para generar las etiquetas
                  </div>
                </div>

                {pedidoSeleccionado.ws_internalid && (
                  <div className={styles.infoSection}>
                    <h3>Información TiendaNube</h3>
                    <div className={styles.infoRow}>
                      <strong>Pedido TN ID:</strong> {pedidoSeleccionado.ws_internalid}
                    </div>
                    {pedidoSeleccionado.tiendanube_number && (
                      <div className={styles.infoRow}>
                        <strong>Pedido TN #:</strong> {pedidoSeleccionado.tiendanube_number}
                      </div>
                    )}
                    {pedidoSeleccionado.tiendanube_shipping_phone && (
                      <div className={styles.infoRow}>
                        <strong>Teléfono TN:</strong> {pedidoSeleccionado.tiendanube_shipping_phone}
                      </div>
                    )}
                  </div>
                )}

                <div className={styles.infoSection}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <h3>Dirección de Envío</h3>
                    <button
                      onClick={() => abrirEditarDireccion(pedidoSeleccionado)}
                      className={`btn-tesla outline-subtle-primary sm ${styles.btnEditDireccion}`}
                      title="Editar dirección de envío"
                    >
                      <Pencil size={14} /> Editar
                    </button>
                  </div>
                  
                  {(() => {
                    const dir = getDireccionDisplay(pedidoSeleccionado);
                    return dir.direccion ? (
                      <>
                        {dir.hasOverride && (
                          <div className={styles.overrideBadge}>
                            <AlertTriangle size={14} /> Dirección modificada manualmente
                          </div>
                        )}
                        {dir.fromCustomer && (
                          <div className={styles.fallbackBadge}>
                            Dirección tomada de facturación del cliente (sin dirección de envío)
                          </div>
                        )}
                        <div className={styles.infoRow}>
                          <strong>Dirección:</strong> {dir.direccion}
                        </div>
                        {dir.ciudad && (
                          <div className={styles.infoRow}>
                            <strong>Localidad:</strong> {dir.ciudad}
                          </div>
                        )}
                        {dir.provincia && (
                          <div className={styles.infoRow}>
                            <strong>Provincia:</strong> {dir.provincia}
                          </div>
                        )}
                        {dir.codigo_postal && (
                          <div className={styles.infoRow}>
                            <strong>Código Postal:</strong> {dir.codigo_postal}
                          </div>
                        )}
                        {dir.telefono && (
                          <div className={styles.infoRow}>
                            <strong>Teléfono:</strong> {dir.telefono}
                          </div>
                        )}
                        {dir.destinatario && (
                          <div className={styles.infoRow}>
                            <strong>Destinatario:</strong> {dir.destinatario}
                          </div>
                        )}
                      </>
                    ) : (
                      <div className={styles.textMuted}>Sin dirección de envío</div>
                    );
                  })()}
                </div>

                <div className={styles.infoSection}>
                  <h3><Truck size={16} /> Enviar a Flex</h3>
                  <div className={styles.flexActions}>
                    <button
                      onClick={() => enviarAFlexRapido(pedidoSeleccionado)}
                      disabled={flexLoading || !getDireccionDisplay(pedidoSeleccionado).direccion}
                      className={`btn-tesla outline-subtle-success sm ${styles.btnEnviarFlex}`}
                      title={!getDireccionDisplay(pedidoSeleccionado).direccion ? 'Sin dirección de envío' : 'Envío rápido con datos del pedido'}
                    >
                      {flexLoading ? <><Loader2 size={14} className={styles.spinning} /> Enviando...</> : <><Truck size={14} /> Envío rápido</>}
                    </button>
                    <button
                      onClick={() => abrirFlexModal(pedidoSeleccionado)}
                      className={`btn-tesla outline-subtle-primary sm`}
                      title="Crear envío manual con datos editables"
                    >
                      <Pencil size={14} /> Envío manual
                    </button>
                  </div>
                  {!getDireccionDisplay(pedidoSeleccionado).direccion && (
                    <div className={styles.fieldHint} style={{ marginTop: '8px', color: 'var(--text-tertiary)' }}>
                      Sin dirección — usá Envío manual para cargar datos
                    </div>
                  )}
                </div>

                {pedidoSeleccionado.soh_observation1 && (
                  <div className={styles.infoSection}>
                    <h3>Observaciones</h3>
                    <div className={styles.observacionesDetalle}>
                      {pedidoSeleccionado.soh_observation1}
                    </div>
                  </div>
                )}
                
                {pedidoSeleccionado.soh_internalannotation && (
                  <div className={styles.infoSection}>
                    <h3>Notas Internas</h3>
                    <div className={styles.observacionesDetalle}>
                      {pedidoSeleccionado.soh_internalannotation}
                    </div>
                  </div>
                )}
              </div>

              <div className={styles.itemsSection}>
                <h3>Items del Pedido:</h3>
                <div className={styles.cantidadTotal}>
                  Cantidad Total Items: {pedidoSeleccionado.total_items}
                </div>
                <table className={styles.itemsTable}>
                  <thead>
                    <tr>
                      <th>Item ID</th>
                      <th>Código</th>
                      <th>Descripción</th>
                      <th>Cantidad</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pedidoSeleccionado.items && pedidoSeleccionado.items.map((item, idx) => (
                      <tr key={`${pedidoSeleccionado.soh_id}-${item.item_id}-${idx}`}>
                        <td>{item.item_id}</td>
                        <td>{item.item_code || '—'}</td>
                        <td>{item.item_desc || 'Sin descripción'}</td>
                        <td className={styles.textCenter}>{item.cantidad}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Modal de edición de dirección */}
      {editandoDireccion && pedidoSeleccionado && (
        <div className={styles.modal} onClick={() => setEditandoDireccion(false)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()} style={{ maxWidth: '600px' }}>
            <div className={styles.modalHeader}>
              <h2><Pencil size={18} /> Editar Dirección de Envío</h2>
              <button 
                onClick={() => setEditandoDireccion(false)}
                className={`btn-tesla outline-subtle-primary sm icon-only ${styles.btnClose}`}
                aria-label="Cerrar modal"
              >
                <X size={18} />
              </button>
            </div>

            <div className={styles.modalBody}>
              <div style={{ marginBottom: '15px', padding: '10px', background: 'var(--info-bg)', borderRadius: '6px', color: 'var(--info-text)' }}>
                <strong><FileText size={14} /> Nota:</strong> Este cambio sobrescribe los datos de TN/ERP. Se usará para visualización Y para las etiquetas de envío.
              </div>

              <div className={styles.formGroup}>
                <label>Dirección Completa *</label>
                <textarea
                  value={direccionForm.direccion}
                  onChange={(e) => setDireccionForm({...direccionForm, direccion: e.target.value})}
                  rows="3"
                  className={styles.formInput}
                  placeholder="Calle, número, piso, depto"
                />
              </div>

              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label>Ciudad/Localidad</label>
                  <input
                    type="text"
                    value={direccionForm.ciudad}
                    onChange={(e) => setDireccionForm({...direccionForm, ciudad: e.target.value})}
                    className={styles.formInput}
                  />
                </div>

                <div className={styles.formGroup}>
                  <label>Provincia</label>
                  <input
                    type="text"
                    value={direccionForm.provincia}
                    onChange={(e) => setDireccionForm({...direccionForm, provincia: e.target.value})}
                    className={styles.formInput}
                  />
                </div>
              </div>

              <div className={styles.formRow}>
                <div className={styles.formGroup}>
                  <label>Código Postal</label>
                  <input
                    type="text"
                    value={direccionForm.codigo_postal}
                    onChange={(e) => setDireccionForm({...direccionForm, codigo_postal: e.target.value})}
                    className={styles.formInput}
                  />
                </div>

                <div className={styles.formGroup}>
                  <label>Teléfono</label>
                  <input
                    type="text"
                    value={direccionForm.telefono}
                    onChange={(e) => setDireccionForm({...direccionForm, telefono: e.target.value})}
                    className={styles.formInput}
                  />
                </div>
              </div>

              <div className={styles.formGroup}>
                <label>Destinatario</label>
                <input
                  type="text"
                  value={direccionForm.destinatario}
                  onChange={(e) => setDireccionForm({...direccionForm, destinatario: e.target.value})}
                  className={styles.formInput}
                  placeholder="Nombre de quien recibe"
                />
              </div>

              <div className={styles.formGroup}>
                <label>Notas Adicionales</label>
                <textarea
                  value={direccionForm.notas}
                  onChange={(e) => setDireccionForm({...direccionForm, notas: e.target.value})}
                  rows="2"
                  className={styles.formInput}
                  placeholder="Ej: Timbre roto, entregar por portería, etc."
                />
              </div>

              <div className={styles.modalActions}>
                <button
                  onClick={guardarDireccion}
                  className={`btn-tesla outline-subtle-success ${styles.btnGuardar}`}
                  disabled={!direccionForm.direccion}
                >
                  <Save size={14} /> Guardar
                </button>
                
                {getDireccionDisplay(pedidoSeleccionado).hasOverride && (
                  <button
                    onClick={eliminarOverride}
                    className={`btn-tesla outline-subtle-danger ${styles.btnEliminar}`}
                  >
                    <Trash2 size={14} /> Eliminar Override
                  </button>
                )}

                <button
                  onClick={() => setEditandoDireccion(false)}
                  className={`btn-tesla outline-subtle-primary ${styles.btnCancelar}`}
                >
                  Cancelar
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Modal de etiquetas */}
      {mostrarModalEtiqueta && pedidoSeleccionado && (
        <div className={styles.modal} onClick={() => setMostrarModalEtiqueta(false)}>
          <div className={styles.modalContent} onClick={(e) => e.stopPropagation()} style={{ maxWidth: '400px' }}>
            <div className={styles.modalHeader}>
              <h2><Printer size={18} /> Generar Etiqueta</h2>
              <button 
                onClick={() => setMostrarModalEtiqueta(false)}
                className={`btn-tesla outline-subtle-primary sm icon-only ${styles.btnClose}`}
                aria-label="Cerrar modal"
              >
                <X size={18} />
              </button>
            </div>

            <div className={styles.modalBody}>
              <div style={{ marginBottom: '20px', padding: '12px', background: 'var(--info-bg)', borderRadius: '6px', color: 'var(--info-text)', fontSize: '14px' }}>
                <strong><ClipboardList size={14} /> Datos de la etiqueta:</strong>
                <ul style={{ margin: '8px 0 0 0', paddingLeft: '20px' }}>
                  <li>Usa <strong>override</strong> si existe</li>
                  <li>Sino usa datos de <strong>TiendaNube</strong></li>
                  <li>Fallback: datos del <strong>ERP</strong></li>
                </ul>
              </div>

              <div className={styles.formGroup}>
                <label>Número de Bultos</label>
                <input
                  type="number"
                  min="1"
                  max="10"
                  value={numBultos}
                  onChange={(e) => setNumBultos(parseInt(e.target.value) || 1)}
                  className={styles.formInput}
                  style={{ fontSize: '18px', textAlign: 'center' }}
                />
                <div style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginTop: '5px' }}>
                  Se generará una etiqueta por bulto (1/3, 2/3, 3/3, etc.)
                </div>
              </div>

              <div className={styles.formGroup}>
                <label>Tipo de Domicilio *</label>
                <select
                  value={tipoDomicilio}
                  onChange={(e) => setTipoDomicilio(e.target.value)}
                  className={styles.formInput}
                  style={{ fontSize: '16px' }}
                >
                  <option value="Particular">Particular</option>
                  <option value="Comercial">Comercial</option>
                  <option value="Sucursal">Sucursal</option>
                </select>
                <div style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginTop: '5px' }}>
                  Aparece en el lateral derecho de la etiqueta
                </div>
              </div>

              <div className={styles.formGroup}>
                <label>Tipo de Envío (opcional)</label>
                <input
                  type="text"
                  value={tipoEnvio}
                  onChange={(e) => setTipoEnvio(e.target.value)}
                  className={styles.formInput}
                  placeholder="Ej: Envío a Domicilio, Retiro en Sucursal..."
                />
                <div style={{ fontSize: '12px', color: 'var(--text-tertiary)', marginTop: '5px' }}>
                  Si no se completa, usa el dato del ERP
                </div>
              </div>

              <div className={styles.modalActions}>
                <button
                  onClick={generarEtiqueta}
                  className={`btn-tesla outline-subtle-success ${styles.btnGuardar}`}
                  disabled={generandoEtiqueta || numBultos < 1 || numBultos > 10}
                >
                  {generandoEtiqueta ? <><Loader2 size={14} className={styles.spinning} /> Generando...</> : <><Printer size={14} /> Generar y Descargar</>}
                </button>

                <button
                  onClick={() => setMostrarModalEtiqueta(false)}
                  className={`btn-tesla outline-subtle-primary ${styles.btnCancelar}`}
                >
                  Cancelar
                </button>
              </div>

              <div style={{ marginTop: '15px', padding: '10px', background: 'var(--bg-tertiary)', borderRadius: '6px', fontSize: '13px' }}>
                <strong><Lightbulb size={14} /> Tip:</strong> Abrí el archivo .txt con el software de tu impresora Zebra (Zebra Browser Print o ZebraDesigner) para imprimir.
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Modal Envío Flex */}
      {showFlexModal && pedidoSeleccionado && (
        <div className={styles.modal} onClick={() => setShowFlexModal(false)}>
          <div className={`${styles.modalContent} ${styles.modalWide}`} onClick={(e) => e.stopPropagation()}>
            <div className={styles.modalHeader}>
              <h2><Truck size={18} /> Crear envío flex — Pedido GBP:{pedidoSeleccionado.soh_id}</h2>
              <button
                onClick={() => setShowFlexModal(false)}
                className={`btn-tesla outline-subtle-primary sm icon-only ${styles.btnClose}`}
                aria-label="Cerrar modal"
              >
                <X size={18} />
              </button>
            </div>

            <div className={styles.modalBody}>
              <div className={styles.formGrid}>
                {/* Fila 1: Fecha + Sucursal */}
                <div className={styles.formField}>
                  <label htmlFor="flex-fecha">Fecha de envío</label>
                  <input
                    id="flex-fecha"
                    type="date"
                    value={flexForm.fecha_envio}
                    onChange={(e) => handleFlexFormChange('fecha_envio', e.target.value)}
                    className={styles.formInput}
                  />
                </div>
                <div className={styles.formField}>
                  <label htmlFor="flex-sucursal">Sucursal</label>
                  <select
                    id="flex-sucursal"
                    value={pedidoSeleccionado.bra_id || ''}
                    disabled
                    className={styles.formInput}
                  >
                    <option value="">—</option>
                    {sucursales.map(s => (
                      <option key={s.bra_id} value={s.bra_id}>{s.bra_desc}</option>
                    ))}
                    {!sucursales.find(s => s.bra_id === pedidoSeleccionado.bra_id) && (
                      <option value={pedidoSeleccionado.bra_id}>Sucursal {pedidoSeleccionado.bra_id}</option>
                    )}
                  </select>
                </div>

                {/* Fila 2: Destinatario (span 2) */}
                <div className={`${styles.formField} ${styles.formFieldSpan2}`}>
                  <label htmlFor="flex-receiver">Destinatario *</label>
                  <input
                    id="flex-receiver"
                    type="text"
                    value={flexForm.receiver_name}
                    onChange={(e) => handleFlexFormChange('receiver_name', e.target.value)}
                    className={styles.formInput}
                    placeholder="Nombre del destinatario"
                  />
                </div>

                {/* Fila 3: Calle + Número */}
                <div className={styles.formField}>
                  <label htmlFor="flex-street">Calle</label>
                  <input
                    id="flex-street"
                    type="text"
                    value={flexForm.street_name}
                    onChange={(e) => handleFlexFormChange('street_name', e.target.value)}
                    className={styles.formInput}
                    placeholder="Nombre de la calle"
                  />
                </div>
                <div className={styles.formField}>
                  <label htmlFor="flex-number">Número</label>
                  <input
                    id="flex-number"
                    type="text"
                    value={flexForm.street_number}
                    onChange={(e) => handleFlexFormChange('street_number', e.target.value)}
                    className={styles.formInput}
                    placeholder="N°"
                  />
                </div>

                {/* Fila 4: CP + Ciudad */}
                <div className={styles.formField}>
                  <label htmlFor="flex-zip">CP *</label>
                  <input
                    id="flex-zip"
                    type="text"
                    value={flexForm.zip_code}
                    onChange={(e) => {
                      handleFlexFormChange('zip_code', e.target.value);
                      resolverCordonPorCP(e.target.value);
                    }}
                    className={styles.formInput}
                    placeholder="1234"
                  />
                  {flexCordon && (
                    <span className={styles.fieldHint}>{flexCordon}</span>
                  )}
                </div>
                <div className={styles.formField}>
                  <label htmlFor="flex-city">Ciudad</label>
                  <input
                    id="flex-city"
                    type="text"
                    value={flexForm.city_name}
                    onChange={(e) => handleFlexFormChange('city_name', e.target.value)}
                    className={styles.formInput}
                    placeholder="Localidad"
                  />
                </div>

                {/* Fila 5: Logística (span 2) */}
                <div className={`${styles.formField} ${styles.formFieldSpan2}`}>
                  <label htmlFor="flex-logistica">Logística</label>
                  <select
                    id="flex-logistica"
                    value={flexForm.logistica_id}
                    onChange={(e) => handleFlexFormChange('logistica_id', e.target.value)}
                    className={styles.formInput}
                  >
                    <option value="">— Sin asignar —</option>
                    {logisticas.map(l => (
                      <option key={l.id} value={l.id}>{l.nombre}</option>
                    ))}
                  </select>
                </div>

                {/* Fila 6: Observaciones (span 2) */}
                <div className={`${styles.formField} ${styles.formFieldSpan2}`}>
                  <label htmlFor="flex-comment">Observaciones</label>
                  <textarea
                    id="flex-comment"
                    value={flexForm.comment}
                    onChange={(e) => handleFlexFormChange('comment', e.target.value)}
                    className={`${styles.formInput} ${styles.textarea}`}
                    placeholder="Notas o instrucciones adicionales (opcional)"
                    rows={2}
                  />
                </div>
              </div>

              <div className={styles.modalActions}>
                <button
                  onClick={guardarEnvioFlex}
                  className={`btn-tesla outline-subtle-success ${styles.btnGuardar}`}
                  disabled={flexLoading || !flexForm.receiver_name.trim() || !flexForm.zip_code.trim()}
                >
                  {flexLoading
                    ? <><Loader2 size={14} className={styles.spinning} /> Creando...</>
                    : <><Truck size={14} /> Crear envío</>
                  }
                </button>
                <button
                  onClick={() => setShowFlexModal(false)}
                  className={`btn-tesla outline-subtle-primary ${styles.btnCancelar}`}
                >
                  Cancelar
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Toast notifications */}
      <Toast toast={toast} onClose={hideToast} />

      {/* Confirm dialog */}
      {confirmDialog && (
        <div className={styles.modal} onClick={confirmDialog.onCancel}>
          <div className={styles.confirmModal} onClick={(e) => e.stopPropagation()}>
            <h3 className={styles.confirmTitle}>{confirmDialog.title}</h3>
            <p className={styles.confirmMessage}>{confirmDialog.message}</p>
            <div className={styles.confirmActions}>
              <button
                className="btn-tesla outline-subtle-primary sm"
                onClick={confirmDialog.onCancel}
              >
                Cancelar
              </button>
              <button
                className="btn-tesla outline-subtle-success sm"
                onClick={confirmDialog.onConfirm}
              >
                Confirmar
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
