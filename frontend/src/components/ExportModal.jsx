import { useState, useEffect, useRef, useCallback } from 'react';
import { X } from 'lucide-react';
import api from '../services/api';
import { toLocalTimestamp } from '../utils/dateUtils';
import styles from './ExportModal.module.css';
import { usePermisos } from '../contexts/PermisosContext';

/**
 * Tiendas oficiales (multi-select) para filtrar a nivel MLA.
 * Solo aplica en tabs Rebate ML, Clásica y PVP. Distinto de `filtroTiendaOficial`
 * (singular, scope producto) que vive en filtrosActivos.
 *
 * 'sin_tienda' es un sentinel literal → mlp_official_store_id IS NULL en backend.
 * El resto son IDs numéricos como string para preservar tipos al serializar.
 */
const TIENDAS_OFICIALES_OPCIONES = [
  { id: 'sin_tienda', label: 'Sin tienda' },
  { id: '57997', label: 'Gauss' },
  { id: '2645', label: 'TP-Link' },
  { id: '144', label: 'Forza/Verbatim' },
  { id: '191942', label: 'Multi-marca' },
];

const TIENDAS_OFICIALES_IDS = TIENDAS_OFICIALES_OPCIONES.map(t => t.id);

/**
 * Serializa el Set de IDs de tiendas oficiales a CSV para el backend.
 * Devuelve null cuando todas o ninguna están tildadas (= sin filtro efectivo).
 */
const serializarTiendasOficiales = (set) => {
  if (!set || set.size === 0 || set.size === TIENDAS_OFICIALES_IDS.length) {
    return null;
  }
  return Array.from(set).join(',');
};

/**
 * Construye query string de filtros para exports GET.
 * Centraliza la lógica que antes estaba copy-pasteada en 4 funciones.
 */
const buildFilterQueryString = (filtrosActivos) => {
  let params = '';
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
  if (filtrosActivos.filtroTiendaOficial) params += `&tienda_oficial=${filtrosActivos.filtroTiendaOficial}`;
  return params;
};

/**
 * Display de filtros activos — definido fuera del componente
 * para evitar re-creación en cada render (rompe reconciliación React).
 */
const FiltrosActivosDisplay = ({ filtrosActivos }) => (
  <div className={styles.filtrosActivos}>
    {filtrosActivos?.search && <div>• Búsqueda: &quot;{filtrosActivos.search}&quot;</div>}
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
    {filtrosActivos?.filtroTiendaOficial === '57997' && <div>• Tienda Oficial: Gauss</div>}
    {filtrosActivos?.filtroTiendaOficial === '2645' && <div>• Tienda Oficial: TP-Link</div>}
    {filtrosActivos?.filtroTiendaOficial === '144' && <div>• Tienda Oficial: Forza/Verbatim</div>}
    {filtrosActivos?.filtroTiendaOficial === '191942' && <div>• Tienda Oficial: Multi-marca</div>}
  </div>
);

export default function ExportModal({ onClose, filtrosActivos, showToast, esTienda = false }) {
  const { tienePermiso } = usePermisos();
  const modalRef = useRef(null);

  // Permisos de exportación
  const puedeExportarVistaActual = tienePermiso('productos.exportar_vista_actual');
  const puedeExportarRebate = tienePermiso('productos.exportar_rebate');
  const puedeExportarWebTransf = tienePermiso('productos.exportar_web_transferencia');
  const puedeExportarClasica = tienePermiso('productos.exportar_clasica');
  const puedeExportarPVP = tienePermiso('productos.exportar_pvp');
  const puedeExportarGremio = tienePermiso('tienda.exportar_lista_gremio');
  const puedeExportarSugerido = tienePermiso('tienda.exportar_lista_sugerido');
  const puedeExportarListaTienda = tienePermiso('tienda.exportar_lista_tienda');

  // Determinar tabs disponibles según permisos y contexto
  const tabsDisponibles = [];
  if (puedeExportarVistaActual) tabsDisponibles.push('vista_actual');
  if (esTienda && puedeExportarGremio) tabsDisponibles.push('lista_gremio');
  if (esTienda && puedeExportarSugerido) tabsDisponibles.push('lista_sugerido');
  if (esTienda && puedeExportarListaTienda) tabsDisponibles.push('lista_web_transf');
  if (!esTienda && puedeExportarRebate) tabsDisponibles.push('rebate');
  if (puedeExportarWebTransf) tabsDisponibles.push('web_transf');
  if (puedeExportarClasica) tabsDisponibles.push('clasica');
  if (puedeExportarPVP) tabsDisponibles.push('pvp');

  // Tab inicial: primera disponible o ninguna
  const tabInicial = tabsDisponibles.length > 0 ? tabsDisponibles[0] : null;
  const [tab, setTab] = useState(tabInicial);
  const [exportando, setExportando] = useState(false);
  const [aplicarFiltros, setAplicarFiltros] = useState(true);
  const [porcentajeClasica, setPorcentajeClasica] = useState('0');
  const [tipoCuotas, setTipoCuotas] = useState('clasica'); // clasica, 3, 6, 9, 12
  const [formatoRebate, setFormatoRebate] = useState('nuevo'); // nuevo, tradicional
  const [tipoCuotasRebate, setTipoCuotasRebate] = useState('clasica'); // clasica, 3, 6, 9, 12
  const [porcentajeRebateCuotas, setPorcentajeRebateCuotas] = useState('1.5'); // % rebate para cuotas
  const [offsetPvpLleno, setOffsetPvpLleno] = useState('0'); // % offset sobre precio cuotas para PVP LLENO
  const [tipoCuotasPVP, setTipoCuotasPVP] = useState('pvp'); // pvp, pvp_3, pvp_6, pvp_9, pvp_12
  const [porcentajePVP, setPorcentajePVP] = useState('0');
  const [monedaClasica, setMonedaClasica] = useState('ARS'); // ARS o USD
  const [monedaPVP, setMonedaPVP] = useState('ARS'); // ARS o USD
  const [monedaWebTransf, setMonedaWebTransf] = useState('ARS'); // ARS o USD
  const [monedaGremio, setMonedaGremio] = useState('ARS'); // ARS o USD para lista gremio
  const [monedaSugerido, setMonedaSugerido] = useState('ARS'); // ARS o USD para lista sugerido
  const [monedaListaWebTransf, setMonedaListaWebTransf] = useState('ARS'); // ARS o USD para lista web transf
  const [dolarVenta, setDolarVenta] = useState(null);
  const [offsetDolar, setOffsetDolar] = useState('0');

  // Tiendas oficiales (filtro a nivel MLA, solo aplica en tabs Rebate/Clásica/PVP).
  // Default: todas tildadas → no filtra (idéntico al comportamiento actual).
  const [tiendasOficialesMLA, setTiendasOficialesMLA] = useState(
    () => new Set(TIENDAS_OFICIALES_IDS)
  );

  /**
   * Render del display informativo del subset activo (Spec R2 scenario 4).
   * Solo se muestra cuando `serializarTiendasOficiales` produce un CSV no-null,
   * es decir SOLO cuando el filtro está aplicando (subset estricto).
   * Se mantiene SEPARADO de `FiltrosActivosDisplay` porque `tiendasOficialesMLA`
   * NO es un filtro de productos — viaja por su propia vía al backend.
   */
  const renderTiendasOficialesActivas = () => {
    const csv = serializarTiendasOficiales(tiendasOficialesMLA);
    if (!csv) return null; // todas o ninguna tildada → sin filtro efectivo
    const labels = TIENDAS_OFICIALES_OPCIONES
      .filter(opcion => tiendasOficialesMLA.has(opcion.id))
      .map(opcion => opcion.label)
      .join(', ');
    return (
      <small className={styles.filterInfo}>
        Filtro activo en MLAs: {labels}
      </small>
    );
  };

  const renderTiendasOficialesCheckboxes = () => (
    <div className={styles.formGroup}>
      <label className={styles.label}>Tiendas oficiales (MLAs):</label>
      <div className={styles.tiendasOficialesGroup}>
        {TIENDAS_OFICIALES_OPCIONES.map(opcion => (
          <label key={opcion.id} className={styles.tiendaCheckboxLabel}>
            <input
              type="checkbox"
              checked={tiendasOficialesMLA.has(opcion.id)}
              onChange={(e) => {
                const next = new Set(tiendasOficialesMLA);
                if (e.target.checked) next.add(opcion.id);
                else next.delete(opcion.id);
                setTiendasOficialesMLA(next);
              }}
            />
            {opcion.label}
          </label>
        ))}
      </div>
      <small className={styles.filterInfo}>
        Filtra qué MLAs se exportan. Si están todas tildadas o ninguna, no se aplica filtro.
      </small>
      {renderTiendasOficialesActivas()}
    </div>
  );

  // Auto-focus en primer input al abrir modal (via ref)
  useEffect(() => {
    const el = modalRef.current;
    if (el) {
      const firstInput = el.querySelector('input');
      if (firstInput) {
        // requestAnimationFrame es más confiable que setTimeout para post-render
        requestAnimationFrame(() => firstInput.focus());
      }
    }
  }, []);

  // Cerrar modal con Escape y capturar Tab para focus trap (via ref)
  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Escape' && !exportando) {
      onClose();
      return;
    }

    // Focus trap dentro del modal
    if (e.key === 'Tab') {
      const el = modalRef.current;
      if (el) {
        const focusableElements = el.querySelectorAll(
          'input, button, select, [tabindex]:not([tabindex="-1"])'
        );
        const firstElement = focusableElements[0];
        const lastElement = focusableElements[focusableElements.length - 1];

        if (e.shiftKey) {
          if (document.activeElement === firstElement) {
            e.preventDefault();
            lastElement.focus();
          }
        } else {
          if (document.activeElement === lastElement) {
            e.preventDefault();
            firstElement.focus();
          }
        }
      }
    }
  }, [onClose, exportando]);

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

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
    filtrosActivos?.filtroNuevos !== null ||
    filtrosActivos?.filtroTiendaOficial !== null;

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
    if (filtrosActivos.filtroTiendaOficial) params.tienda_oficial = filtrosActivos.filtroTiendaOficial;
    return params;
  };

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
        const response = await api.get('/tipo-cambio/actual');
        setDolarVenta(response.data.venta);
      } catch {
        // Silencioso: dólar no es crítico, el modal funciona sin él
      }
    };
    cargarDolarVenta();
  }, []);

  const convertirFechaParaAPI = (fechaDD_MM_YYYY) => {
    const [d, m, y] = fechaDD_MM_YYYY.split('/');
    return `${y}-${m}-${d}`;
  };

  /** Helper: descarga un blob como archivo Excel */
  const descargarBlob = (blobData, nombreArchivo) => {
    const url = window.URL.createObjectURL(new Blob([blobData]));
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', nombreArchivo);
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  };

  const exportarVistaActual = async () => {
    setExportando(true);
    try {
      let params = `page=1&page_size=10000`;
      if (aplicarFiltros) {
        params += buildFilterQueryString(filtrosActivos);
      }

      const response = await api.get(`/exportar-vista-actual?${params}`, {
        responseType: 'blob'
      });

      const timestamp = toLocalTimestamp();
      descargarBlob(response.data, `vista_actual_${timestamp}.xlsx`);
      showToast('Exportación completada');
      onClose();
    } catch {
      showToast('Error al exportar Vista Actual', 'error');
    } finally {
      setExportando(false);
    }
  };

  const exportarRebate = async () => {
    setExportando(true);
    try {
      const body = {
        fecha_desde: convertirFechaParaAPI(fechaDesde),
        fecha_hasta: convertirFechaParaAPI(fechaHasta),
        formato: formatoRebate,
        tipo_cuotas: tipoCuotasRebate
      };

      // Para cuotas, enviar rebate override y offset PVP LLENO
      if (tipoCuotasRebate !== 'clasica') {
        body.porcentaje_rebate_override = parseFloat(porcentajeRebateCuotas.toString().replace(',', '.')) || 1.5;
        body.offset_pvp_lleno = parseFloat(offsetPvpLleno.toString().replace(',', '.')) || 0;
      }

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

      // Tiendas oficiales viajan en el TOP-LEVEL del body (no dentro de filtros)
      // porque en backend el campo está en ExportRebateRequest.tiendas_oficiales.
      const tiendasOfMLA = serializarTiendasOficiales(tiendasOficialesMLA);
      if (tiendasOfMLA) {
        body.tiendas_oficiales = tiendasOfMLA;
      }

      const response = await api.post('/productos/exportar-rebate', body, {
        responseType: 'blob'
      });
      const timestamp = toLocalTimestamp();
      descargarBlob(response.data, `rebate_export_${timestamp}.xlsx`);
      showToast('Exportación completada');
      onClose();
    } catch {
      showToast('Error al exportar', 'error');
    } finally {
      setExportando(false);
    }
  };

  const exportarClasica = async () => {
    setExportando(true);
    try {
      let params = `porcentaje_adicional=${parseFloat(porcentajeClasica.toString().replace(',', '.')) || 0}&tipo_cuotas=${tipoCuotas}`;

      // Agregar currency_id y offset_dolar
      const currencyId = monedaClasica === 'USD' ? 2 : 1;
      params += `&currency_id=${currencyId}`;
      if (monedaClasica === 'USD') {
        const offset = parseFloat(offsetDolar.toString().replace(',', '.')) || 0;
        params += `&offset_dolar=${offset}`;
      }

      if (aplicarFiltros) {
        params += buildFilterQueryString(filtrosActivos);
      }

      // Filtro de tiendas oficiales a nivel MLA (independiente de aplicarFiltros).
      const tiendasOfMLA = serializarTiendasOficiales(tiendasOficialesMLA);
      if (tiendasOfMLA) {
        params += `&tiendas_oficiales=${encodeURIComponent(tiendasOfMLA)}`;
      }

      const response = await api.get(`/exportar-clasica?${params}`, {
        responseType: 'blob'
      });

      const timestamp = toLocalTimestamp();

      // Determinar nombre del archivo según tipo de cuotas
      let nombreBase = 'clasica';
      if (tipoCuotas === '3') nombreBase = '3_cuotas';
      else if (tipoCuotas === '6') nombreBase = '6_cuotas';
      else if (tipoCuotas === '9') nombreBase = '9_cuotas';
      else if (tipoCuotas === '12') nombreBase = '12_cuotas';

      descargarBlob(response.data, `${nombreBase}_${timestamp}.xlsx`);
      showToast('Exportación completada');
      onClose();
    } catch {
      showToast('Error al exportar Clásica', 'error');
    } finally {
      setExportando(false);
    }
  };

  const exportarListaGremio = async () => {
    setExportando(true);
    try {
      let params = `con_precio_gremio=true`;

      // Agregar moneda y offset
      const currencyId = monedaGremio === 'USD' ? 2 : 1;
      params += `&currency_id=${currencyId}`;
      if (monedaGremio === 'USD') {
        const offset = parseFloat(offsetDolar.toString().replace(',', '.')) || 0;
        params += `&offset_dolar=${offset}`;
      }

      if (aplicarFiltros) {
        params += buildFilterQueryString(filtrosActivos);
      }

      const response = await api.get(`/exportar-lista-gremio?${params}`, {
        responseType: 'blob'
      });
      const timestamp = toLocalTimestamp();
      const monedaSufijo = monedaGremio === 'USD' ? '_USD' : '_ARS';
      descargarBlob(response.data, `lista_gremio${monedaSufijo}_${timestamp}.xlsx`);
      showToast('Exportación completada');
      onClose();
    } catch {
      showToast('Error al exportar Lista Gremio', 'error');
    } finally {
      setExportando(false);
    }
  };

  const exportarListaSugerido = async () => {
    setExportando(true);
    try {
      let params = `con_precio_sugerido=true`;

      // Agregar moneda y offset
      const currencyId = monedaSugerido === 'USD' ? 2 : 1;
      params += `&currency_id=${currencyId}`;
      if (monedaSugerido === 'USD') {
        const offset = parseFloat(offsetDolar.toString().replace(',', '.')) || 0;
        params += `&offset_dolar=${offset}`;
      }

      if (aplicarFiltros) {
        params += buildFilterQueryString(filtrosActivos);
      }

      const response = await api.get(`/exportar-lista-sugerido?${params}`, {
        responseType: 'blob'
      });
      const timestamp = toLocalTimestamp();
      const monedaSufijo = monedaSugerido === 'USD' ? '_USD' : '_ARS';
      descargarBlob(response.data, `lista_sugerido${monedaSufijo}_${timestamp}.xlsx`);
      showToast('Exportación completada');
      onClose();
    } catch {
      showToast('Error al exportar Lista Sugerido', 'error');
    } finally {
      setExportando(false);
    }
  };

  const exportarListaWebTransf = async () => {
    setExportando(true);
    try {
      let params = '';

      // Agregar moneda y offset
      const currencyId = monedaListaWebTransf === 'USD' ? 2 : 1;
      params += `currency_id=${currencyId}`;
      if (monedaListaWebTransf === 'USD') {
        const offset = parseFloat(offsetDolar.toString().replace(',', '.')) || 0;
        params += `&offset_dolar=${offset}`;
      }

      if (aplicarFiltros) {
        params += buildFilterQueryString(filtrosActivos);
      }

      const response = await api.get(`/exportar-lista-web-transferencia?${params}`, {
        responseType: 'blob'
      });
      const timestamp = toLocalTimestamp();
      const monedaSufijo = monedaListaWebTransf === 'USD' ? '_USD' : '_ARS';
      descargarBlob(response.data, `lista_web_transf${monedaSufijo}_${timestamp}.xlsx`);
      showToast('Exportación completada');
      onClose();
    } catch {
      showToast('Error al exportar Lista Web Transferencia', 'error');
    } finally {
      setExportando(false);
    }
  };

  const exportarWebTransf = async () => {
    setExportando(true);
    try {
      let params = `porcentaje_adicional=${parseFloat(porcentajeWebTransf.toString().replace(',', '.')) || 0}`;

      // Agregar currency_id y offset_dolar
      const currencyId = monedaWebTransf === 'USD' ? 2 : 1;
      params += `&currency_id=${currencyId}`;
      if (monedaWebTransf === 'USD') {
        const offset = parseFloat(offsetDolar.toString().replace(',', '.')) || 0;
        params += `&offset_dolar=${offset}`;
      }

      if (aplicarFiltros) {
        params += buildFilterQueryString(filtrosActivos);
      }

      const response = await api.get(`/exportar-web-transferencia?${params}`, {
        responseType: 'blob'
      });
      const timestamp = toLocalTimestamp();
      descargarBlob(response.data, `web_transferencia_${timestamp}.xlsx`);
      showToast('Exportación completada');
      onClose();
    } catch {
      showToast('Error al exportar Web Transferencia', 'error');
    } finally {
      setExportando(false);
    }
  };

  const exportarPVP = async () => {
    setExportando(true);
    try {
      let params = `porcentaje_adicional=${parseFloat(porcentajePVP.toString().replace(',', '.')) || 0}&tipo_cuotas=${tipoCuotasPVP}`;

      // Agregar currency_id y offset_dolar
      const currencyId = monedaPVP === 'USD' ? 2 : 1;
      params += `&currency_id=${currencyId}`;
      if (monedaPVP === 'USD') {
        const offset = parseFloat(offsetDolar.toString().replace(',', '.')) || 0;
        params += `&offset_dolar=${offset}`;
      }

      if (aplicarFiltros) {
        params += buildFilterQueryString(filtrosActivos);
      }

      // Filtro de tiendas oficiales a nivel MLA (independiente de aplicarFiltros).
      const tiendasOfMLA = serializarTiendasOficiales(tiendasOficialesMLA);
      if (tiendasOfMLA) {
        params += `&tiendas_oficiales=${encodeURIComponent(tiendasOfMLA)}`;
      }

      const response = await api.get(`/exportar-clasica?${params}`, {
        responseType: 'blob'
      });
      const timestamp = toLocalTimestamp();

      // Determinar nombre del archivo según tipo de cuotas
      let nombreBase = 'pvp';
      if (tipoCuotasPVP === 'pvp_3') nombreBase = 'pvp_3_cuotas';
      else if (tipoCuotasPVP === 'pvp_6') nombreBase = 'pvp_6_cuotas';
      else if (tipoCuotasPVP === 'pvp_9') nombreBase = 'pvp_9_cuotas';
      else if (tipoCuotasPVP === 'pvp_12') nombreBase = 'pvp_12_cuotas';

      descargarBlob(response.data, `${nombreBase}_${timestamp}.xlsx`);
      showToast('Exportación completada');
      onClose();
    } catch {
      showToast('Error al exportar PVP', 'error');
    } finally {
      setExportando(false);
    }
  };

  return (
    <div className={styles.overlay}>
      <div className={styles.modal} ref={modalRef}>
        <div className={styles.header}>
          <h2 className={styles.title}>Exportar Precios</h2>
          <button onClick={onClose} className={styles.closeButton} aria-label="Cerrar modal"><X size={18} /></button>
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
            {esTienda && puedeExportarSugerido && (
              <button
                onClick={() => setTab('lista_sugerido')}
                className={`${styles.tab} ${tab === 'lista_sugerido' ? styles.active : ''}`}
              >
                Lista Sugerido
              </button>
            )}
            {esTienda && puedeExportarListaTienda && (
              <button
                onClick={() => setTab('lista_web_transf')}
                className={`${styles.tab} ${tab === 'lista_web_transf' ? styles.active : ''}`}
              >
                Lista Web Transf.
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
            {puedeExportarPVP && (
              <button
                onClick={() => setTab('pvp')}
                className={`${styles.tab} ${tab === 'pvp' ? styles.active : ''}`}
              >
                PVP
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
                  {aplicarFiltros && <FiltrosActivosDisplay filtrosActivos={filtrosActivos} />}
                </div>
              )}

              <p className={styles.description}>
                Exporta todos los productos tal como se ven en la tabla actual con todos los precios y datos disponibles.
                <br />
                <strong>Incluye:</strong> Código, Descripción, Stock, Costo, Clásica, Rebate, Oferta, Web Transferencia, Tienda Nube y todos los markups.
              </p>

              <div className={styles.buttonGroup}>
                <button onClick={onClose} disabled={exportando} className="btn-tesla ghost">
                  Cancelar
                </button>
                <button onClick={exportarVistaActual} disabled={exportando} className="btn-tesla outline-subtle-success">
                  {exportando ? 'Exportando...' : 'Exportar Vista Actual'}
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
                  {aplicarFiltros && <FiltrosActivosDisplay filtrosActivos={filtrosActivos} />}
                </div>
              )}

              <p className={styles.description}>
                Exporta la lista de precios Gremio para productos con precio configurado.
                <br />
                <strong>Incluye:</strong> Marca, Categoría, Subcategoría, Código, Descripción, Precio Gremio s/IVA, Precio Gremio c/IVA
              </p>

              <div className={styles.formGroup}>
                <label className={styles.label}>Moneda:</label>
                <select
                  value={monedaGremio}
                  onChange={(e) => setMonedaGremio(e.target.value)}
                  className={styles.input}
                >
                  <option value="ARS">Pesos (ARS)</option>
                  <option value="USD">Dólares (USD)</option>
                </select>
              </div>

              {monedaGremio === 'USD' && dolarVenta && (
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

              <div className={styles.buttonGroup}>
                <button onClick={onClose} disabled={exportando} className="btn-tesla ghost">
                  Cancelar
                </button>
                <button onClick={exportarListaGremio} disabled={exportando} className="btn-tesla outline-subtle-success">
                  {exportando ? 'Exportando...' : 'Exportar Lista Gremio'}
                </button>
              </div>
            </div>
          )}

          {tab === 'lista_sugerido' && puedeExportarSugerido && (
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
                  {aplicarFiltros && <FiltrosActivosDisplay filtrosActivos={filtrosActivos} />}
                </div>
              )}

              <p className={styles.description}>
                Exporta la lista de precios sugeridos. El precio se calcula como:
                <br />
                <strong>costo × (1 + varios%) × (1 + (markup clásica + markup sugerido)%)</strong>
                <br />
                <strong>Incluye:</strong> Marca, Categoría, Subcategoría, Código, Descripción, Stock, Markups, Precio Sugerido s/IVA, Precio Sugerido c/IVA
              </p>

              <div className={styles.formGroup}>
                <label className={styles.label}>Moneda:</label>
                <select
                  value={monedaSugerido}
                  onChange={(e) => setMonedaSugerido(e.target.value)}
                  className={styles.input}
                >
                  <option value="ARS">Pesos (ARS)</option>
                  <option value="USD">Dólares (USD)</option>
                </select>
              </div>

              {monedaSugerido === 'USD' && dolarVenta && (
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

              <div className={styles.buttonGroup}>
                <button onClick={onClose} disabled={exportando} className="btn-tesla ghost">
                  Cancelar
                </button>
                <button onClick={exportarListaSugerido} disabled={exportando} className="btn-tesla outline-subtle-success">
                  {exportando ? 'Exportando...' : 'Exportar Lista Sugerido'}
                </button>
              </div>
            </div>
          )}

          {tab === 'lista_web_transf' && puedeExportarListaTienda && (
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
                  {aplicarFiltros && <FiltrosActivosDisplay filtrosActivos={filtrosActivos} />}
                </div>
              )}

              <p className={styles.description}>
                Exporta la lista de precios Web Transferencia para productos con precio configurado.
                <br />
                <strong>Incluye:</strong> Marca, Categoría, Subcategoría, Código, Descripción, Precio Web Transf. s/IVA, Precio Web Transf. c/IVA
              </p>

              <div className={styles.formGroup}>
                <label className={styles.label}>Moneda:</label>
                <select
                  value={monedaListaWebTransf}
                  onChange={(e) => setMonedaListaWebTransf(e.target.value)}
                  className={styles.input}
                >
                  <option value="ARS">Pesos (ARS)</option>
                  <option value="USD">Dólares (USD)</option>
                </select>
              </div>

              {monedaListaWebTransf === 'USD' && dolarVenta && (
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

              <div className={styles.buttonGroup}>
                <button onClick={onClose} disabled={exportando} className="btn-tesla ghost">
                  Cancelar
                </button>
                <button onClick={exportarListaWebTransf} disabled={exportando} className="btn-tesla outline-subtle-success">
                  {exportando ? 'Exportando...' : 'Exportar Lista Web Transf.'}
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
                  {aplicarFiltros && <FiltrosActivosDisplay filtrosActivos={filtrosActivos} />}
                </div>
              )}

              {renderTiendasOficialesCheckboxes()}

              <div className={styles.formGroup}>
                <label className={styles.label}>Formato de exportación:</label>
                <select
                  value={formatoRebate}
                  onChange={(e) => setFormatoRebate(e.target.value)}
                  className={styles.input}
                >
                  <option value="nuevo">Nuevo (DxI)</option>
                  <option value="tradicional">Tradicional (Viejo)</option>
                </select>
              </div>

              <div className={styles.formGroup}>
                <label className={styles.label}>Tipo de precio (Lista):</label>
                <select
                  value={tipoCuotasRebate}
                  onChange={(e) => setTipoCuotasRebate(e.target.value)}
                  className={styles.input}
                >
                  <option value="clasica">Clásica</option>
                  <option value="3">3 Cuotas</option>
                  <option value="6">6 Cuotas</option>
                  <option value="9">9 Cuotas</option>
                  <option value="12">12 Cuotas</option>
                </select>
              </div>

              {tipoCuotasRebate !== 'clasica' && (
                <div className={styles.formGroup}>
                  <label className={styles.label}>Porcentaje de Rebate (%):</label>
                  <input
                    type="text"
                    inputMode="decimal"
                    placeholder="Ej: 1.5"
                    value={porcentajeRebateCuotas}
                    onChange={(e) => setPorcentajeRebateCuotas(e.target.value)}
                    onBlur={(e) => {
                      const valor = e.target.value.replace(',', '.');
                      const numero = parseFloat(valor);
                      if (!isNaN(numero) && numero >= 0) {
                        setPorcentajeRebateCuotas(numero.toString());
                      } else {
                        setPorcentajeRebateCuotas('1.5');
                      }
                    }}
                    onFocus={(e) => e.target.select()}
                    className={styles.input}
                  />
                  <small className={styles.filterInfo}>
                    PVP SELLER = precio cuotas / (1 - rebate%). Se aplica a todos los productos.
                  </small>
                </div>
              )}

              {tipoCuotasRebate !== 'clasica' && (
                <div className={styles.formGroup}>
                  <label className={styles.label}>Offset PVP LLENO (%):</label>
                  <input
                    type="text"
                    inputMode="decimal"
                    placeholder="Ej: 5"
                    value={offsetPvpLleno}
                    onChange={(e) => setOffsetPvpLleno(e.target.value)}
                    onBlur={(e) => {
                      const valor = e.target.value.replace(',', '.');
                      const numero = parseFloat(valor);
                      if (!isNaN(numero)) {
                        setOffsetPvpLleno(numero.toString());
                      } else {
                        setOffsetPvpLleno('0');
                      }
                    }}
                    onFocus={(e) => e.target.select()}
                    className={styles.input}
                  />
                  <small className={styles.filterInfo}>
                    PVP LLENO = precio cuotas * (1 + offset%). Debe ser mayor que PVP SELLER.
                  </small>
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
                <button onClick={onClose} disabled={exportando} className="btn-tesla ghost">
                  Cancelar
                </button>
                <button onClick={exportarRebate} disabled={exportando} className="btn-tesla outline-subtle-success">
                  {exportando ? 'Exportando...' : 'Exportar Rebate'}
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
                  {aplicarFiltros && <FiltrosActivosDisplay filtrosActivos={filtrosActivos} />}
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
                    setPorcentajeWebTransf(e.target.value);
                  }}
                  onBlur={(e) => {
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
                <button onClick={onClose} disabled={exportando} className="btn-tesla ghost">
                  Cancelar
                </button>
                <button onClick={exportarWebTransf} disabled={exportando} className="btn-tesla outline-subtle-success">
                  {exportando ? 'Exportando...' : 'Exportar Excel'}
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
                  {aplicarFiltros && <FiltrosActivosDisplay filtrosActivos={filtrosActivos} />}
                </div>
              )}

              {renderTiendasOficialesCheckboxes()}

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
                    setPorcentajeClasica(e.target.value);
                  }}
                  onBlur={(e) => {
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
                <button onClick={onClose} disabled={exportando} className="btn-tesla ghost">
                  Cancelar
                </button>
                <button onClick={exportarClasica} disabled={exportando} className="btn-tesla outline-subtle-success">
                  {exportando ? 'Exportando...' : 'Exportar Excel'}
                </button>
              </div>
            </div>
          )}

          {tab === 'pvp' && puedeExportarPVP && (
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
                  {aplicarFiltros && <FiltrosActivosDisplay filtrosActivos={filtrosActivos} />}
                </div>
              )}

              {renderTiendasOficialesCheckboxes()}

              <p className={styles.description}>
                Exporta precios de PVP (Listas 12, 18, 19, 20, 21). Usa precios base de lista PVP.
              </p>

              <div className={styles.formGroup}>
                <label className={styles.label}>Tipo de precio a exportar:</label>
                <select
                  value={tipoCuotasPVP}
                  onChange={(e) => setTipoCuotasPVP(e.target.value)}
                  className={styles.input}
                >
                  <option value="pvp">PVP Base</option>
                  <option value="pvp_3">PVP 3 Cuotas</option>
                  <option value="pvp_6">PVP 6 Cuotas</option>
                  <option value="pvp_9">PVP 9 Cuotas</option>
                  <option value="pvp_12">PVP 12 Cuotas</option>
                </select>
              </div>

              <div className={styles.formGroup}>
                <label className={styles.label}>Moneda:</label>
                <select
                  value={monedaPVP}
                  onChange={(e) => setMonedaPVP(e.target.value)}
                  className={styles.input}
                >
                  <option value="ARS">Pesos (ARS)</option>
                  <option value="USD">Dólares (USD)</option>
                </select>
              </div>

              {monedaPVP === 'USD' && dolarVenta && (
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
                  placeholder="Ej: 10"
                  value={porcentajePVP}
                  onChange={(e) => {
                    setPorcentajePVP(e.target.value);
                  }}
                  onBlur={(e) => {
                    const valor = e.target.value.replace(',', '.');
                    const numero = parseFloat(valor);
                    if (!isNaN(numero)) {
                      setPorcentajePVP(numero.toString());
                    } else {
                      setPorcentajePVP('0');
                    }
                  }}
                  onFocus={(e) => e.target.select()}
                  className={styles.input}
                />
                <small className={styles.filterInfo}>
                  Suma este porcentaje a los precios PVP
                </small>
              </div>

              <div className={styles.buttonGroup}>
                <button onClick={onClose} disabled={exportando} className="btn-tesla ghost">
                  Cancelar
                </button>
                <button onClick={exportarPVP} disabled={exportando} className="btn-tesla outline-subtle-success">
                  {exportando ? 'Exportando...' : 'Exportar PVP'}
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
