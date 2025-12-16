import { useState, useEffect } from 'react';
import axios from 'axios';
import styles from './ExportModal.module.css';
import { usePermisos } from '../contexts/PermisosContext';

export default function ExportModal({ onClose, filtrosActivos, showToast, esTienda = false }) {
  const { tienePermiso } = usePermisos();

  // Permisos de exportación
  const puedeExportarVistaActual = tienePermiso('productos.exportar_vista_actual');
  const puedeExportarRebate = tienePermiso('productos.exportar_rebate');
  const puedeExportarWebTransf = tienePermiso('productos.exportar_web_transferencia');
  const puedeExportarClasica = tienePermiso('productos.exportar_clasica');
  const puedeExportarGremio = tienePermiso('tienda.exportar_lista_gremio');

  // Determinar tabs disponibles según permisos y contexto
  const tabsDisponibles = [];
  if (puedeExportarVistaActual) tabsDisponibles.push('vista_actual');
  if (esTienda && puedeExportarGremio) tabsDisponibles.push('lista_gremio');
  if (!esTienda && puedeExportarRebate) tabsDisponibles.push('rebate');
  if (puedeExportarWebTransf) tabsDisponibles.push('web_transf');
  if (puedeExportarClasica) tabsDisponibles.push('clasica');

  // Tab inicial: primera disponible o ninguna
  const tabInicial = tabsDisponibles.length > 0 ? tabsDisponibles[0] : null;
  const [tab, setTab] = useState(tabInicial);
  const [exportando, setExportando] = useState(false);
  const [aplicarFiltros, setAplicarFiltros] = useState(true);
  const [porcentajeClasica, setPorcentajeClasica] = useState('0');
  const [tipoCuotas, setTipoCuotas] = useState('clasica'); // clasica, 3, 6, 9, 12
  const [monedaClasica, setMonedaClasica] = useState('ARS'); // ARS o USD
  const [monedaWebTransf, setMonedaWebTransf] = useState('ARS'); // ARS o USD
  const [dolarVenta, setDolarVenta] = useState(null);
  const [offsetDolar, setOffsetDolar] = useState('0');

  // Auto-focus en primer input al abrir modal
  useEffect(() => {
    const modal = document.querySelector(`.${styles.modal}`);
    if (modal) {
      const firstInput = modal.querySelector('input');
      if (firstInput) {
        // Pequeño delay para asegurar que el modal esté renderizado
        setTimeout(() => firstInput.focus(), 100);
      }
    }
  }, []);

  // Cerrar modal con Escape y capturar Tab para navegación interna
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && !exportando) {
        onClose();
        return;
      }

      // Capturar Tab para mantenerlo dentro del modal
      if (e.key === 'Tab') {
        const modal = document.querySelector(`.${styles.modal}`);
        if (modal) {
          const focusableElements = modal.querySelectorAll(
            'input, button, [tabindex]:not([tabindex="-1"])'
          );
          const firstElement = focusableElements[0];
          const lastElement = focusableElements[focusableElements.length - 1];

          if (e.shiftKey) {
            // Tab + Shift: ir hacia atrás
            if (document.activeElement === firstElement) {
              e.preventDefault();
              lastElement.focus();
            }
          } else {
            // Tab: ir hacia adelante
            if (document.activeElement === lastElement) {
              e.preventDefault();
              firstElement.focus();
            }
          }
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose, exportando]);

  const hayFiltros =
    !!filtrosActivos?.search ||
    filtrosActivos?.con_stock !== null ||
    filtrosActivos?.con_precio !== null ||
    (filtrosActivos?.marcas?.length > 0) ||
    (filtrosActivos?.subcategorias?.length > 0) ||
    filtrosActivos?.filtroRebate !== null ||
    filtrosActivos?.filtroOferta !== null ||
    filtrosActivos?.filtroWebTransf !== null ||
    filtrosActivos?.filtroTiendaNube !== null ||
    filtrosActivos?.filtroMarkupClasica !== null ||
    filtrosActivos?.filtroMarkupRebate !== null ||
    filtrosActivos?.filtroMarkupOferta !== null ||
    filtrosActivos?.filtroMarkupWebTransf !== null ||
    filtrosActivos?.filtroOutOfCards !== null ||
    (filtrosActivos?.coloresSeleccionados?.length > 0) ||
    (filtrosActivos?.pmsSeleccionados?.length > 0) ||
    (filtrosActivos?.audit_usuarios?.length > 0) ||
    (filtrosActivos?.audit_tipos_accion?.length > 0) ||
    !!filtrosActivos?.audit_fecha_desde ||
    !!filtrosActivos?.audit_fecha_hasta ||
    filtrosActivos?.filtroMLA !== null ||
    filtrosActivos?.filtroEstadoMLA !== null ||
    filtrosActivos?.filtroNuevos !== null;

  const agregarFiltrosAvanzados = (params) => {
    if (filtrosActivos.filtroRebate === 'con_rebate') params.con_rebate = true;
    if (filtrosActivos.filtroRebate === 'sin_rebate') params.con_rebate = false;
    if (filtrosActivos.filtroOferta === 'con_oferta') params.con_oferta = true;
    if (filtrosActivos.filtroOferta === 'sin_oferta') params.con_oferta = false;
    if (filtrosActivos.filtroWebTransf === 'con_web_transf') params.con_web_transf = true;
    if (filtrosActivos.filtroWebTransf === 'sin_web_transf') params.con_web_transf = false;
    if (filtrosActivos.filtroTiendaNube === 'con_descuento') params.tiendanube_con_descuento = true;
    if (filtrosActivos.filtroTiendaNube === 'sin_descuento') params.tiendanube_sin_descuento = true;
    if (filtrosActivos.filtroTiendaNube === 'no_publicado') params.tiendanube_no_publicado = true;
    if (filtrosActivos.filtroMarkupClasica === 'positivo') params.markup_clasica_positivo = true;
    if (filtrosActivos.filtroMarkupClasica === 'negativo') params.markup_clasica_positivo = false;
    if (filtrosActivos.filtroMarkupRebate === 'positivo') params.markup_rebate_positivo = true;
    if (filtrosActivos.filtroMarkupRebate === 'negativo') params.markup_rebate_positivo = false;
    if (filtrosActivos.filtroMarkupOferta === 'positivo') params.markup_oferta_positivo = true;
    if (filtrosActivos.filtroMarkupOferta === 'negativo') params.markup_oferta_positivo = false;
    if (filtrosActivos.filtroMarkupWebTransf === 'positivo') params.markup_web_transf_positivo = true;
    if (filtrosActivos.filtroMarkupWebTransf === 'negativo') params.markup_web_transf_positivo = false;
    if (filtrosActivos.filtroOutOfCards === 'con_out_of_cards') params.out_of_cards = true;
    if (filtrosActivos.filtroOutOfCards === 'sin_out_of_cards') params.out_of_cards = false;
    if (filtrosActivos.coloresSeleccionados?.length > 0) params.colores = filtrosActivos.coloresSeleccionados.join(',');
    if (filtrosActivos.pmsSeleccionados?.length > 0) params.pms = filtrosActivos.pmsSeleccionados.join(',');
    if (filtrosActivos.audit_usuarios?.length > 0) params.audit_usuarios = filtrosActivos.audit_usuarios.join(',');
    if (filtrosActivos.audit_tipos_accion?.length > 0) params.audit_tipos_accion = filtrosActivos.audit_tipos_accion.join(',');
    if (filtrosActivos.audit_fecha_desde) params.audit_fecha_desde = filtrosActivos.audit_fecha_desde;
    if (filtrosActivos.audit_fecha_hasta) params.audit_fecha_hasta = filtrosActivos.audit_fecha_hasta;
    if (filtrosActivos.filtroMLA === 'con_mla') params.con_mla = true;
    if (filtrosActivos.filtroMLA === 'sin_mla') params.con_mla = false;
    if (filtrosActivos.filtroEstadoMLA === 'activa') params.estado_mla = 'activa';
    if (filtrosActivos.filtroEstadoMLA === 'pausada') params.estado_mla = 'pausada';
    if (filtrosActivos.filtroNuevos === 'ultimos_7_dias') params.nuevos_ultimos_7_dias = true;
    return params;
  };

  const FiltrosActivosDisplay = () => (
    <div className={styles.filtrosActivos}>
      {filtrosActivos?.search && <div>• Búsqueda: "{filtrosActivos.search}"</div>}
      {filtrosActivos?.con_stock === true && <div>• Con stock</div>}
      {filtrosActivos?.con_stock === false && <div>• Sin stock</div>}
      {filtrosActivos?.con_precio === true && <div>• Con precio</div>}
      {filtrosActivos?.con_precio === false && <div>• Sin precio</div>}
      {filtrosActivos?.marcas?.length > 0 && <div>• {filtrosActivos.marcas.length} marca(s)</div>}
      {filtrosActivos?.subcategorias?.length > 0 && <div>• {filtrosActivos.subcategorias.length} subcategoría(s)</div>}
      {filtrosActivos?.filtroRebate === 'con_rebate' && <div>• Con Rebate</div>}
      {filtrosActivos?.filtroRebate === 'sin_rebate' && <div>• Sin Rebate</div>}
      {filtrosActivos?.filtroOferta === 'con_oferta' && <div>• Con Oferta</div>}
      {filtrosActivos?.filtroOferta === 'sin_oferta' && <div>• Sin Oferta</div>}
      {filtrosActivos?.filtroWebTransf === 'con_web_transf' && <div>• Con Web Transferencia</div>}
      {filtrosActivos?.filtroWebTransf === 'sin_web_transf' && <div>• Sin Web Transferencia</div>}
      {filtrosActivos?.filtroTiendaNube === 'con_descuento' && <div>• Tienda Nube: Con Descuento</div>}
      {filtrosActivos?.filtroTiendaNube === 'sin_descuento' && <div>• Tienda Nube: Sin Descuento</div>}
      {filtrosActivos?.filtroTiendaNube === 'no_publicado' && <div>• Tienda Nube: No Publicado</div>}
      {filtrosActivos?.filtroOutOfCards === 'con_out_of_cards' && <div>• Con Out of Cards</div>}
      {filtrosActivos?.filtroOutOfCards === 'sin_out_of_cards' && <div>• Sin Out of Cards</div>}
      {filtrosActivos?.filtroMarkupClasica === 'positivo' && <div>• Markup Clásica: Positivo</div>}
      {filtrosActivos?.filtroMarkupClasica === 'negativo' && <div>• Markup Clásica: Negativo</div>}
      {filtrosActivos?.filtroMarkupRebate === 'positivo' && <div>• Markup Rebate: Positivo</div>}
      {filtrosActivos?.filtroMarkupRebate === 'negativo' && <div>• Markup Rebate: Negativo</div>}
      {filtrosActivos?.filtroMarkupOferta === 'positivo' && <div>• Markup Oferta: Positivo</div>}
      {filtrosActivos?.filtroMarkupOferta === 'negativo' && <div>• Markup Oferta: Negativo</div>}
      {filtrosActivos?.filtroMarkupWebTransf === 'positivo' && <div>• Markup Web Transf: Positivo</div>}
      {filtrosActivos?.filtroMarkupWebTransf === 'negativo' && <div>• Markup Web Transf: Negativo</div>}
      {filtrosActivos?.audit_usuarios?.length > 0 && <div>• {filtrosActivos.audit_usuarios.length} usuario(s) auditoría</div>}
      {filtrosActivos?.audit_tipos_accion?.length > 0 && <div>• {filtrosActivos.audit_tipos_accion.length} tipo(s) de acción</div>}
      {filtrosActivos?.audit_fecha_desde && <div>• Auditoría desde: {filtrosActivos.audit_fecha_desde}</div>}
      {filtrosActivos?.audit_fecha_hasta && <div>• Auditoría hasta: {filtrosActivos.audit_fecha_hasta}</div>}
      {filtrosActivos?.coloresSeleccionados?.length > 0 && <div>• {filtrosActivos.coloresSeleccionados.length} color(es) seleccionado(s)</div>}
      {filtrosActivos?.pmsSeleccionados?.length > 0 && <div>• {filtrosActivos.pmsSeleccionados.length} PM(s) seleccionado(s)</div>}
      {filtrosActivos?.filtroMLA === 'con_mla' && <div>• Con MLA</div>}
      {filtrosActivos?.filtroMLA === 'sin_mla' && <div>• Sin MLA</div>}
      {filtrosActivos?.filtroEstadoMLA === 'activa' && <div>• Estado MLA: Activas</div>}
      {filtrosActivos?.filtroEstadoMLA === 'pausada' && <div>• Estado MLA: Pausadas</div>}
      {filtrosActivos?.filtroNuevos === 'ultimos_7_dias' && <div>• Nuevos (últimos 7 días)</div>}
    </div>
  );

  const [fechaDesde, setFechaDesde] = useState(() => {
    const hoy = new Date();
    return hoy.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  });
  const [fechaHasta, setFechaHasta] = useState(() => {
    const hoy = new Date();
    const ultimoDia = new Date(hoy.getFullYear(), hoy.getMonth() + 1, 0);
    return ultimoDia.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  });

  const [porcentajeWebTransf, setPorcentajeWebTransf] = useState('0');

  // Cargar dólar venta al abrir el modal
  useEffect(() => {
    const cargarDolarVenta = async () => {
      try {
        const token = localStorage.getItem('token');
        const response = await axios.get('https://pricing.gaussonline.com.ar/api/tipo-cambio/actual', {
          headers: { Authorization: `Bearer ${token}` }
        });
        setDolarVenta(response.data.venta);
      } catch (error) {
        console.error('Error cargando dólar venta:', error);
      }
    };
    cargarDolarVenta();
  }, []);

  const convertirFechaParaAPI = (fechaDD_MM_YYYY) => {
    const [d, m, y] = fechaDD_MM_YYYY.split('/');
    return `${y}-${m}-${d}`;
  };

  const exportarVistaActual = async () => {
    setExportando(true);
    try {
      const token = localStorage.getItem('token');

      let params = `page=1&page_size=10000`;

      if (aplicarFiltros) {
        if (filtrosActivos.search) params += `&search=${encodeURIComponent(filtrosActivos.search)}`;
        if (filtrosActivos.con_stock === true) params += `&con_stock=true`;
        if (filtrosActivos.con_stock === false) params += `&con_stock=false`;
        if (filtrosActivos.con_precio === true) params += `&con_precio=true`;
        if (filtrosActivos.con_precio === false) params += `&con_precio=false`;
        if (filtrosActivos.marcas?.length > 0) params += `&marcas=${filtrosActivos.marcas.join(',')}`;
        if (filtrosActivos.subcategorias?.length > 0) params += `&subcategorias=${filtrosActivos.subcategorias.join(',')}`;
        if (filtrosActivos.filtroRebate === 'con_rebate') params += `&con_rebate=true`;
        if (filtrosActivos.filtroRebate === 'sin_rebate') params += `&con_rebate=false`;
        if (filtrosActivos.filtroOferta === 'con_oferta') params += `&con_oferta=true`;
        if (filtrosActivos.filtroOferta === 'sin_oferta') params += `&con_oferta=false`;
        if (filtrosActivos.filtroWebTransf === 'con_web_transf') params += `&con_web_transf=true`;
        if (filtrosActivos.filtroWebTransf === 'sin_web_transf') params += `&con_web_transf=false`;
        if (filtrosActivos.filtroTiendaNube === 'con_descuento') params += `&tiendanube_con_descuento=true`;
        if (filtrosActivos.filtroTiendaNube === 'sin_descuento') params += `&tiendanube_sin_descuento=true`;
        if (filtrosActivos.filtroTiendaNube === 'no_publicado') params += `&tiendanube_no_publicado=true`;
        if (filtrosActivos.filtroMarkupClasica === 'positivo') params += `&markup_clasica_positivo=true`;
        if (filtrosActivos.filtroMarkupClasica === 'negativo') params += `&markup_clasica_positivo=false`;
        if (filtrosActivos.filtroMarkupRebate === 'positivo') params += `&markup_rebate_positivo=true`;
        if (filtrosActivos.filtroMarkupRebate === 'negativo') params += `&markup_rebate_positivo=false`;
        if (filtrosActivos.filtroMarkupOferta === 'positivo') params += `&markup_oferta_positivo=true`;
        if (filtrosActivos.filtroMarkupOferta === 'negativo') params += `&markup_oferta_positivo=false`;
        if (filtrosActivos.filtroMarkupWebTransf === 'positivo') params += `&markup_web_transf_positivo=true`;
        if (filtrosActivos.filtroMarkupWebTransf === 'negativo') params += `&markup_web_transf_positivo=false`;
        if (filtrosActivos.filtroOutOfCards === 'con_out_of_cards') params += `&out_of_cards=true`;
        if (filtrosActivos.filtroOutOfCards === 'sin_out_of_cards') params += `&out_of_cards=false`;
        if (filtrosActivos.coloresSeleccionados?.length > 0) params += `&colores=${filtrosActivos.coloresSeleccionados.join(',')}`;
        if (filtrosActivos.pmsSeleccionados?.length > 0) params += `&pms=${filtrosActivos.pmsSeleccionados.join(',')}`;
        if (filtrosActivos.audit_usuarios?.length > 0) params += `&audit_usuarios=${filtrosActivos.audit_usuarios.join(',')}`;
        if (filtrosActivos.audit_tipos_accion?.length > 0) params += `&audit_tipos_accion=${filtrosActivos.audit_tipos_accion.join(',')}`;
        if (filtrosActivos.audit_fecha_desde) params += `&audit_fecha_desde=${filtrosActivos.audit_fecha_desde}`;
        if (filtrosActivos.audit_fecha_hasta) params += `&audit_fecha_hasta=${filtrosActivos.audit_fecha_hasta}`;
        if (filtrosActivos.filtroMLA === 'con_mla') params += `&con_mla=true`;
        if (filtrosActivos.filtroMLA === 'sin_mla') params += `&con_mla=false`;
        if (filtrosActivos.filtroEstadoMLA === 'activa') params += `&estado_mla=activa`;
        if (filtrosActivos.filtroEstadoMLA === 'pausada') params += `&estado_mla=pausada`;
        if (filtrosActivos.filtroNuevos === 'ultimos_7_dias') params += `&nuevos_ultimos_7_dias=true`;
      }

      const url = `https://pricing.gaussonline.com.ar/api/exportar-vista-actual?${params}`;
      const response = await axios.get(url, {
        responseType: 'blob',
        headers: { Authorization: `Bearer ${token}` }
      });

      const blob = new Blob([response.data], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
      });
      const link = document.createElement('a');
      link.href = window.URL.createObjectURL(blob);
      const ahora = new Date();
      const timestamp = ahora.toISOString().replace(/[:.]/g, '-').slice(0, -5);
      const nombreArchivo = `vista_actual_${timestamp}.xlsx`;
      link.setAttribute('download', nombreArchivo);
      document.body.appendChild(link);
      link.click();
      link.remove();
      showToast('✅ Exportación completada');
      onClose();
    } catch (error) {
      console.error('Error exportando:', error);
      showToast('❌ Error al exportar Vista Actual', 'error');
    } finally {
      setExportando(false);
    }
  };

  const exportarRebate = async () => {
    setExportando(true);
    try {
      const token = localStorage.getItem('token');
      const body = {
        fecha_desde: convertirFechaParaAPI(fechaDesde),
        fecha_hasta: convertirFechaParaAPI(fechaHasta)
      };

      if (aplicarFiltros) {
        body.filtros = {
          search: filtrosActivos.search || null,
          con_stock: filtrosActivos.con_stock,
          con_precio: filtrosActivos.con_precio,
          marcas: filtrosActivos.marcas?.length > 0 ? filtrosActivos.marcas.join(',') : null,
          subcategorias: filtrosActivos.subcategorias?.length > 0 ? filtrosActivos.subcategorias.join(',') : null
        };
        body.filtros = agregarFiltrosAvanzados(body.filtros);
      }

      const response = await axios.post(
        'https://pricing.gaussonline.com.ar/api/productos/exportar-rebate',
        body,
        {
          headers: { Authorization: `Bearer ${token}` },
          responseType: 'blob'
        }
      );
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      const ahora = new Date();
      const timestamp = ahora.toISOString().replace(/[:.]/g, '-').slice(0, -5);
      const nombreArchivo = `rebate_export_${timestamp}.xlsx`;
      link.setAttribute('download', nombreArchivo);
      document.body.appendChild(link);
      link.click();
      link.remove();
      showToast('✅ Exportación completada');
      onClose();
    } catch (error) {
      console.error('Error exportando:', error);
      showToast('❌ Error al exportar', 'error');
    } finally {
      setExportando(false);
    }
  };

  const exportarClasica = async () => {
    setExportando(true);
    try {
      const token = localStorage.getItem('token');
      let params = `porcentaje_adicional=${parseFloat(porcentajeClasica.toString().replace(',', '.')) || 0}&tipo_cuotas=${tipoCuotas}`;

      // Agregar currency_id y offset_dolar
      const currencyId = monedaClasica === 'USD' ? 2 : 1;
      params += `&currency_id=${currencyId}`;
      if (monedaClasica === 'USD') {
        const offset = parseFloat(offsetDolar.toString().replace(',', '.')) || 0;
        params += `&offset_dolar=${offset}`;
      }

      if (aplicarFiltros) {
        if (filtrosActivos.search) params += `&search=${encodeURIComponent(filtrosActivos.search)}`;
        if (filtrosActivos.con_stock !== null) params += `&con_stock=${filtrosActivos.con_stock}`;
        if (filtrosActivos.con_precio !== null) params += `&con_precio=${filtrosActivos.con_precio}`;
        if (filtrosActivos.marcas?.length > 0) params += `&marcas=${filtrosActivos.marcas.join(',')}`;
        if (filtrosActivos.subcategorias?.length > 0) params += `&subcategorias=${filtrosActivos.subcategorias.join(',')}`;
        if (filtrosActivos.filtroRebate === 'con_rebate') params += `&con_rebate=true`;
        if (filtrosActivos.filtroRebate === 'sin_rebate') params += `&con_rebate=false`;
        if (filtrosActivos.filtroOferta === 'con_oferta') params += `&con_oferta=true`;
        if (filtrosActivos.filtroOferta === 'sin_oferta') params += `&con_oferta=false`;
        if (filtrosActivos.filtroWebTransf === 'con_web_transf') params += `&con_web_transf=true`;
        if (filtrosActivos.filtroWebTransf === 'sin_web_transf') params += `&con_web_transf=false`;
        if (filtrosActivos.filtroTiendaNube === 'con_descuento') params += `&tiendanube_con_descuento=true`;
        if (filtrosActivos.filtroTiendaNube === 'sin_descuento') params += `&tiendanube_sin_descuento=true`;
        if (filtrosActivos.filtroTiendaNube === 'no_publicado') params += `&tiendanube_no_publicado=true`;
        if (filtrosActivos.filtroMarkupClasica === 'positivo') params += `&markup_clasica_positivo=true`;
        if (filtrosActivos.filtroMarkupClasica === 'negativo') params += `&markup_clasica_positivo=false`;
        if (filtrosActivos.filtroMarkupRebate === 'positivo') params += `&markup_rebate_positivo=true`;
        if (filtrosActivos.filtroMarkupRebate === 'negativo') params += `&markup_rebate_positivo=false`;
        if (filtrosActivos.filtroMarkupOferta === 'positivo') params += `&markup_oferta_positivo=true`;
        if (filtrosActivos.filtroMarkupOferta === 'negativo') params += `&markup_oferta_positivo=false`;
        if (filtrosActivos.filtroMarkupWebTransf === 'positivo') params += `&markup_web_transf_positivo=true`;
        if (filtrosActivos.filtroMarkupWebTransf === 'negativo') params += `&markup_web_transf_positivo=false`;
        if (filtrosActivos.filtroOutOfCards === 'con_out_of_cards') params += `&out_of_cards=true`;
        if (filtrosActivos.filtroOutOfCards === 'sin_out_of_cards') params += `&out_of_cards=false`;
        if (filtrosActivos.coloresSeleccionados?.length > 0) params += `&colores=${filtrosActivos.coloresSeleccionados.join(',')}`;
        if (filtrosActivos.pmsSeleccionados?.length > 0) params += `&pms=${filtrosActivos.pmsSeleccionados.join(',')}`;
        if (filtrosActivos.audit_usuarios?.length > 0) params += `&audit_usuarios=${filtrosActivos.audit_usuarios.join(',')}`;
        if (filtrosActivos.audit_tipos_accion?.length > 0) params += `&audit_tipos_accion=${filtrosActivos.audit_tipos_accion.join(',')}`;
        if (filtrosActivos.audit_fecha_desde) params += `&audit_fecha_desde=${filtrosActivos.audit_fecha_desde}`;
        if (filtrosActivos.audit_fecha_hasta) params += `&audit_fecha_hasta=${filtrosActivos.audit_fecha_hasta}`;
        if (filtrosActivos.filtroMLA === 'con_mla') params += `&con_mla=true`;
        if (filtrosActivos.filtroMLA === 'sin_mla') params += `&con_mla=false`;
        if (filtrosActivos.filtroEstadoMLA === 'activa') params += `&estado_mla=activa`;
        if (filtrosActivos.filtroEstadoMLA === 'pausada') params += `&estado_mla=pausada`;
        if (filtrosActivos.filtroNuevos === 'ultimos_7_dias') params += `&nuevos_ultimos_7_dias=true`;
      }

      const response = await axios.get(
        `https://pricing.gaussonline.com.ar/api/exportar-clasica?${params}`,
        {
          headers: { Authorization: `Bearer ${token}` },
          responseType: 'blob'
        }
      );
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      const ahora = new Date();
      const timestamp = ahora.toISOString().replace(/[:.]/g, '-').slice(0, -5);

      // Determinar nombre del archivo según tipo de cuotas
      let nombreBase = 'clasica';
      if (tipoCuotas === '3') nombreBase = '3_cuotas';
      else if (tipoCuotas === '6') nombreBase = '6_cuotas';
      else if (tipoCuotas === '9') nombreBase = '9_cuotas';
      else if (tipoCuotas === '12') nombreBase = '12_cuotas';

      const nombreArchivo = `${nombreBase}_${timestamp}.xlsx`;
      link.setAttribute('download', nombreArchivo);
      document.body.appendChild(link);
      link.click();
      link.remove();
      showToast('✅ Exportación completada');
      onClose();
    } catch (error) {
      console.error('Error exportando:', error);
      showToast('❌ Error al exportar Clásica', 'error');
    } finally {
      setExportando(false);
    }
  };

  const exportarListaGremio = async () => {
    setExportando(true);
    try {
      const token = localStorage.getItem('token');
      let params = `con_precio_gremio=true`;

      if (aplicarFiltros) {
        if (filtrosActivos.search) params += `&search=${encodeURIComponent(filtrosActivos.search)}`;
        if (filtrosActivos.con_stock === true) params += `&con_stock=true`;
        if (filtrosActivos.con_stock === false) params += `&con_stock=false`;
        if (filtrosActivos.marcas?.length > 0) params += `&marcas=${filtrosActivos.marcas.join(',')}`;
        if (filtrosActivos.subcategorias?.length > 0) params += `&subcategorias=${filtrosActivos.subcategorias.join(',')}`;
        if (filtrosActivos.coloresSeleccionados?.length > 0) params += `&colores=${filtrosActivos.coloresSeleccionados.join(',')}`;
      }

      const response = await axios.get(
        `https://pricing.gaussonline.com.ar/api/exportar-lista-gremio?${params}`,
        {
          headers: { Authorization: `Bearer ${token}` },
          responseType: 'blob'
        }
      );
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      const ahora = new Date();
      const timestamp = ahora.toISOString().replace(/[:.]/g, '-').slice(0, -5);
      const nombreArchivo = `lista_gremio_${timestamp}.xlsx`;
      link.setAttribute('download', nombreArchivo);
      document.body.appendChild(link);
      link.click();
      link.remove();
      showToast('✅ Exportación completada');
      onClose();
    } catch (error) {
      console.error('Error exportando:', error);
      showToast('❌ Error al exportar Lista Gremio', 'error');
    } finally {
      setExportando(false);
    }
  };

  const exportarWebTransf = async () => {
    setExportando(true);
    try {
      const token = localStorage.getItem('token');
      let params = `porcentaje_adicional=${parseFloat(porcentajeWebTransf.toString().replace(',', '.')) || 0}`;

      // Agregar currency_id y offset_dolar
      const currencyId = monedaWebTransf === 'USD' ? 2 : 1;
      params += `&currency_id=${currencyId}`;
      if (monedaWebTransf === 'USD') {
        const offset = parseFloat(offsetDolar.toString().replace(',', '.')) || 0;
        params += `&offset_dolar=${offset}`;
      }

      if (aplicarFiltros) {
        if (filtrosActivos.search) params += `&search=${encodeURIComponent(filtrosActivos.search)}`;
        if (filtrosActivos.con_stock !== null) params += `&con_stock=${filtrosActivos.con_stock}`;
        if (filtrosActivos.con_precio !== null) params += `&con_precio=${filtrosActivos.con_precio}`;
        if (filtrosActivos.marcas?.length > 0) params += `&marcas=${filtrosActivos.marcas.join(',')}`;
        if (filtrosActivos.subcategorias?.length > 0) params += `&subcategorias=${filtrosActivos.subcategorias.join(',')}`;
        if (filtrosActivos.filtroRebate === 'con_rebate') params += `&con_rebate=true`;
        if (filtrosActivos.filtroRebate === 'sin_rebate') params += `&con_rebate=false`;
        if (filtrosActivos.filtroOferta === 'con_oferta') params += `&con_oferta=true`;
        if (filtrosActivos.filtroOferta === 'sin_oferta') params += `&con_oferta=false`;
        if (filtrosActivos.filtroWebTransf === 'con_web_transf') params += `&con_web_transf=true`;
        if (filtrosActivos.filtroWebTransf === 'sin_web_transf') params += `&con_web_transf=false`;
        if (filtrosActivos.filtroTiendaNube === 'con_descuento') params += `&tiendanube_con_descuento=true`;
        if (filtrosActivos.filtroTiendaNube === 'sin_descuento') params += `&tiendanube_sin_descuento=true`;
        if (filtrosActivos.filtroTiendaNube === 'no_publicado') params += `&tiendanube_no_publicado=true`;
        if (filtrosActivos.filtroMarkupClasica === 'positivo') params += `&markup_clasica_positivo=true`;
        if (filtrosActivos.filtroMarkupClasica === 'negativo') params += `&markup_clasica_positivo=false`;
        if (filtrosActivos.filtroMarkupRebate === 'positivo') params += `&markup_rebate_positivo=true`;
        if (filtrosActivos.filtroMarkupRebate === 'negativo') params += `&markup_rebate_positivo=false`;
        if (filtrosActivos.filtroMarkupOferta === 'positivo') params += `&markup_oferta_positivo=true`;
        if (filtrosActivos.filtroMarkupOferta === 'negativo') params += `&markup_oferta_positivo=false`;
        if (filtrosActivos.filtroMarkupWebTransf === 'positivo') params += `&markup_web_transf_positivo=true`;
        if (filtrosActivos.filtroMarkupWebTransf === 'negativo') params += `&markup_web_transf_positivo=false`;
        if (filtrosActivos.filtroOutOfCards === 'con_out_of_cards') params += `&out_of_cards=true`;
        if (filtrosActivos.filtroOutOfCards === 'sin_out_of_cards') params += `&out_of_cards=false`;
        if (filtrosActivos.coloresSeleccionados?.length > 0) params += `&colores=${filtrosActivos.coloresSeleccionados.join(',')}`;
        if (filtrosActivos.pmsSeleccionados?.length > 0) params += `&pms=${filtrosActivos.pmsSeleccionados.join(',')}`;
        if (filtrosActivos.audit_usuarios?.length > 0) params += `&audit_usuarios=${filtrosActivos.audit_usuarios.join(',')}`;
        if (filtrosActivos.audit_tipos_accion?.length > 0) params += `&audit_tipos_accion=${filtrosActivos.audit_tipos_accion.join(',')}`;
        if (filtrosActivos.audit_fecha_desde) params += `&audit_fecha_desde=${filtrosActivos.audit_fecha_desde}`;
        if (filtrosActivos.audit_fecha_hasta) params += `&audit_fecha_hasta=${filtrosActivos.audit_fecha_hasta}`;
        if (filtrosActivos.filtroMLA === 'con_mla') params += `&con_mla=true`;
        if (filtrosActivos.filtroMLA === 'sin_mla') params += `&con_mla=false`;
        if (filtrosActivos.filtroEstadoMLA === 'activa') params += `&estado_mla=activa`;
        if (filtrosActivos.filtroEstadoMLA === 'pausada') params += `&estado_mla=pausada`;
        if (filtrosActivos.filtroNuevos === 'ultimos_7_dias') params += `&nuevos_ultimos_7_dias=true`;
      }

      const response = await axios.get(
        `https://pricing.gaussonline.com.ar/api/exportar-web-transferencia?${params}`,
        {
          headers: { Authorization: `Bearer ${token}` },
          responseType: 'blob'
        }
      );
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      const ahora = new Date();
      const timestamp = ahora.toISOString().replace(/[:.]/g, '-').slice(0, -5);
      const nombreArchivo = `web_transferencia_${timestamp}.xlsx`;
      link.setAttribute('download', nombreArchivo);
      document.body.appendChild(link);
      link.click();
      link.remove();
      showToast('✅ Exportación completada');
      onClose();
    } catch (error) {
      console.error('Error exportando:', error);
      showToast('❌ Error al exportar Web Transferencia', 'error');
    } finally {
      setExportando(false);
    }
  };

  return (
    <div className={styles.overlay}>
      <div className={styles.modal}>
        <div className={styles.header}>
          <h2 className={styles.title}>📊 Exportar Precios</h2>
          <button onClick={onClose} className={styles.closeButton}>×</button>
        </div>

        {tabsDisponibles.length === 0 ? (
          <div className={styles.noPermiso}>
            No tienes permisos para exportar datos.
          </div>
        ) : (
          <div className={styles.tabs}>
            {puedeExportarVistaActual && (
              <button
                onClick={() => setTab('vista_actual')}
                className={`${styles.tab} ${tab === 'vista_actual' ? styles.active : ''}`}
              >
                Vista Actual
              </button>
            )}
            {esTienda && puedeExportarGremio && (
              <button
                onClick={() => setTab('lista_gremio')}
                className={`${styles.tab} ${tab === 'lista_gremio' ? styles.active : ''}`}
              >
                Lista Gremio
              </button>
            )}
            {!esTienda && puedeExportarRebate && (
              <button
                onClick={() => setTab('rebate')}
                className={`${styles.tab} ${tab === 'rebate' ? styles.active : ''}`}
              >
                Rebate ML
              </button>
            )}
            {puedeExportarWebTransf && (
              <button
                onClick={() => setTab('web_transf')}
                className={`${styles.tab} ${tab === 'web_transf' ? styles.active : ''}`}
              >
                Web Transferencia
              </button>
            )}
            {puedeExportarClasica && (
              <button
                onClick={() => setTab('clasica')}
                className={`${styles.tab} ${tab === 'clasica' ? styles.active : ''}`}
              >
                Clásica
              </button>
            )}
          </div>
        )}

        {tabsDisponibles.length > 0 && (
        <div className={styles.content}>
          {tab === 'vista_actual' && puedeExportarVistaActual && (
            <div>
              {hayFiltros && (
                <div className={styles.filterCheckbox}>
                  <label>
                    <input
                      type="checkbox"
                      checked={aplicarFiltros}
                      onChange={(e) => setAplicarFiltros(e.target.checked)}
                    />
                    Exportar solo productos filtrados
                  </label>
                  {aplicarFiltros && <FiltrosActivosDisplay />}
                </div>
              )}

              <p className={styles.description}>
                Exporta todos los productos tal como se ven en la tabla actual con todos los precios y datos disponibles.
                <br />
                <strong>Incluye:</strong> Código, Descripción, Stock, Costo, Clásica, Rebate, Oferta, Web Transferencia, Tienda Nube y todos los markups.
              </p>

              <div className={styles.buttonGroup}>
                <button onClick={onClose} disabled={exportando} className={`${styles.button} ${styles.buttonSecondary}`}>
                  Cancelar
                </button>
                <button onClick={exportarVistaActual} disabled={exportando} className={`${styles.button} ${styles.buttonPrimary}`}>
                  {exportando ? '⏳ Exportando...' : '📥 Exportar Vista Actual'}
                </button>
              </div>
            </div>
          )}

          {tab === 'lista_gremio' && puedeExportarGremio && (
            <div>
              {hayFiltros && (
                <div className={styles.filterCheckbox}>
                  <label>
                    <input
                      type="checkbox"
                      checked={aplicarFiltros}
                      onChange={(e) => setAplicarFiltros(e.target.checked)}
                    />
                    Exportar solo productos filtrados
                  </label>
                  {aplicarFiltros && <FiltrosActivosDisplay />}
                </div>
              )}

              <p className={styles.description}>
                Exporta la lista de precios Gremio para productos con precio configurado.
                <br />
                <strong>Incluye:</strong> Marca, Categoría, Subcategoría, Código, Descripción, Precio Gremio s/IVA, Precio Gremio c/IVA
              </p>

              <div className={styles.buttonGroup}>
                <button onClick={onClose} disabled={exportando} className={`${styles.button} ${styles.buttonSecondary}`}>
                  Cancelar
                </button>
                <button onClick={exportarListaGremio} disabled={exportando} className={`${styles.button} ${styles.buttonPrimary}`}>
                  {exportando ? '⏳ Exportando...' : '📥 Exportar Lista Gremio'}
                </button>
              </div>
            </div>
          )}

          {tab === 'rebate' && puedeExportarRebate && (
            <div>
              {hayFiltros && (
                <div className={styles.filterCheckbox}>
                  <label>
                    <input
                      type="checkbox"
                      checked={aplicarFiltros}
                      onChange={(e) => setAplicarFiltros(e.target.checked)}
                    />
                    Exportar solo productos filtrados
                  </label>
                  {aplicarFiltros && <FiltrosActivosDisplay />}
                </div>
              )}

              <div className={styles.formGrid}>
                <div className={styles.formGroup}>
                  <label className={styles.label}>Fecha Desde:</label>
                  <input
                    type="text"
                    placeholder="DD/MM/YYYY"
                    value={fechaDesde}
                    onChange={(e) => setFechaDesde(e.target.value)}
                    onFocus={(e) => e.target.select()}
                    className={styles.input}
                  />
                </div>
                <div className={styles.formGroup}>
                  <label className={styles.label}>Fecha Hasta:</label>
                  <input
                    type="text"
                    placeholder="DD/MM/YYYY"
                    value={fechaHasta}
                    onChange={(e) => setFechaHasta(e.target.value)}
                    onFocus={(e) => e.target.select()}
                    className={styles.input}
                  />
                </div>
              </div>

              <div className={styles.buttonGroup}>
                <button onClick={onClose} disabled={exportando} className={`${styles.button} ${styles.buttonSecondary}`}>
                  Cancelar
                </button>
                <button onClick={exportarRebate} disabled={exportando} className={`${styles.button} ${styles.buttonPrimary}`}>
                  {exportando ? '⏳ Exportando...' : '📥 Exportar Rebate'}
                </button>
              </div>
            </div>
          )}

          {tab === 'web_transf' && puedeExportarWebTransf && (
            <div>
              {hayFiltros && (
                <div className={styles.filterCheckbox}>
                  <label>
                    <input
                      type="checkbox"
                      checked={aplicarFiltros}
                      onChange={(e) => setAplicarFiltros(e.target.checked)}
                    />
                    Exportar solo productos filtrados
                  </label>
                  {aplicarFiltros && <FiltrosActivosDisplay />}
                </div>
              )}

              <p className={styles.description}>
                Exporta los precios de Web Transferencia activos en formato Excel.
                <br />
                <strong>Formato:</strong> Código/EAN | Precio | ID Moneda (1=ARS, 2=USD)
              </p>

              <div className={styles.formGroup}>
                <label className={styles.label}>Moneda:</label>
                <select
                  value={monedaWebTransf}
                  onChange={(e) => setMonedaWebTransf(e.target.value)}
                  className={styles.input}
                >
                  <option value="ARS">Pesos (ARS)</option>
                  <option value="USD">Dólares (USD)</option>
                </select>
              </div>

              {monedaWebTransf === 'USD' && dolarVenta && (
                <div className={styles.formGroup}>
                  <label className={styles.label}>
                    Dólar venta: ${dolarVenta.toFixed(2)}
                  </label>
                  <label className={styles.label}>Offset (±):</label>
                  <input
                    type="text"
                    inputMode="decimal"
                    placeholder="Ej: 10 o -10"
                    value={offsetDolar}
                    onChange={(e) => setOffsetDolar(e.target.value)}
                    onBlur={(e) => {
                      const valor = e.target.value.replace(',', '.');
                      const numero = parseFloat(valor);
                      if (!isNaN(numero)) {
                        setOffsetDolar(numero.toString());
                      } else {
                        setOffsetDolar('0');
                      }
                    }}
                    onFocus={(e) => e.target.select()}
                    className={styles.input}
                  />
                  <small className={styles.filterInfo}>
                    Dólar ajustado: ${(dolarVenta + (parseFloat(offsetDolar.replace(',', '.')) || 0)).toFixed(2)}
                  </small>
                </div>
              )}

              <div className={styles.formGroup}>
                <label className={styles.label}>Porcentaje adicional (%):</label>
                <input
                  type="text"
                  inputMode="decimal"
                  placeholder="Ej: 25"
                  value={porcentajeWebTransf}
                  onChange={(e) => {
                    // Aceptar cualquier entrada, dejar que el usuario escriba libremente
                    setPorcentajeWebTransf(e.target.value);
                  }}
                  onBlur={(e) => {
                    // Al salir del campo, validar que sea un número válido
                    const valor = e.target.value.replace(',', '.');
                    const numero = parseFloat(valor);
                    if (!isNaN(numero)) {
                      setPorcentajeWebTransf(numero.toString());
                    } else {
                      setPorcentajeWebTransf('0');
                    }
                  }}
                  onFocus={(e) => e.target.select()}
                  className={styles.input}
                />
                <small className={styles.filterInfo}>
                  Suma este porcentaje a los precios de Web Transferencia
                </small>
              </div>

              <div className={styles.buttonGroup}>
                <button onClick={onClose} disabled={exportando} className={`${styles.button} ${styles.buttonSecondary}`}>
                  Cancelar
                </button>
                <button onClick={exportarWebTransf} disabled={exportando} className={`${styles.button} ${styles.buttonPrimary}`}>
                  {exportando ? '⏳ Exportando...' : '📥 Exportar Excel'}
                </button>
              </div>
            </div>
          )}

          {tab === 'clasica' && puedeExportarClasica && (
            <div>
              {hayFiltros && (
                <div className={styles.filterCheckbox}>
                  <label>
                    <input
                      type="checkbox"
                      checked={aplicarFiltros}
                      onChange={(e) => setAplicarFiltros(e.target.checked)}
                    />
                    Exportar solo productos filtrados
                  </label>
                  {aplicarFiltros && <FiltrosActivosDisplay />}
                </div>
              )}

              <p className={styles.description}>
                Exporta precios de Clásica. Si el producto tiene rebate activo, aplica el % sobre el precio rebate. Si no, exporta el precio clásica original.
              </p>

              <div className={styles.formGroup}>
                <label className={styles.label}>Tipo de precio a exportar:</label>
                <select
                  value={tipoCuotas}
                  onChange={(e) => setTipoCuotas(e.target.value)}
                  className={styles.input}
                >
                  <option value="clasica">Clásica</option>
                  <option value="3">3 Cuotas</option>
                  <option value="6">6 Cuotas</option>
                  <option value="9">9 Cuotas</option>
                  <option value="12">12 Cuotas</option>
                </select>
              </div>

              <div className={styles.formGroup}>
                <label className={styles.label}>Moneda:</label>
                <select
                  value={monedaClasica}
                  onChange={(e) => setMonedaClasica(e.target.value)}
                  className={styles.input}
                >
                  <option value="ARS">Pesos (ARS)</option>
                  <option value="USD">Dólares (USD)</option>
                </select>
              </div>

              {monedaClasica === 'USD' && dolarVenta && (
                <div className={styles.formGroup}>
                  <label className={styles.label}>
                    Dólar venta: ${dolarVenta.toFixed(2)}
                  </label>
                  <label className={styles.label}>Offset (±):</label>
                  <input
                    type="text"
                    inputMode="decimal"
                    placeholder="Ej: 10 o -10"
                    value={offsetDolar}
                    onChange={(e) => setOffsetDolar(e.target.value)}
                    onBlur={(e) => {
                      const valor = e.target.value.replace(',', '.');
                      const numero = parseFloat(valor);
                      if (!isNaN(numero)) {
                        setOffsetDolar(numero.toString());
                      } else {
                        setOffsetDolar('0');
                      }
                    }}
                    onFocus={(e) => e.target.select()}
                    className={styles.input}
                  />
                  <small className={styles.filterInfo}>
                    Dólar ajustado: ${(dolarVenta + (parseFloat(offsetDolar.replace(',', '.')) || 0)).toFixed(2)}
                  </small>
                </div>
              )}

              <div className={styles.formGroup}>
                <label className={styles.label}>Porcentaje adicional sobre rebate (%):</label>
                <input
                  type="text"
                  inputMode="decimal"
                  placeholder="Ej: 20"
                  value={porcentajeClasica}
                  onChange={(e) => {
                    // Aceptar cualquier entrada, dejar que el usuario escriba libremente
                    setPorcentajeClasica(e.target.value);
                  }}
                  onBlur={(e) => {
                    // Al salir del campo, validar que sea un número válido
                    const valor = e.target.value.replace(',', '.');
                    const numero = parseFloat(valor);
                    if (!isNaN(numero)) {
                      setPorcentajeClasica(numero.toString());
                    } else {
                      setPorcentajeClasica('0');
                    }
                  }}
                  onFocus={(e) => e.target.select()}
                  className={styles.input}
                />
                <small className={styles.filterInfo}>
                  Solo aplica a productos con rebate activo
                </small>
              </div>

              <div className={styles.buttonGroup}>
                <button onClick={onClose} disabled={exportando} className={`${styles.button} ${styles.buttonSecondary}`}>
                  Cancelar
                </button>
                <button onClick={exportarClasica} disabled={exportando} className={`${styles.button} ${styles.buttonPrimary}`}>
                  {exportando ? '⏳ Exportando...' : '📥 Exportar Excel'}
                </button>
              </div>
            </div>
          )}
        </div>
        )}
      </div>
    </div>
  );
}
