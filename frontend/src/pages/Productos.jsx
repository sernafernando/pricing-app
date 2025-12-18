import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { productosAPI } from '../services/api';
import PricingModal from '../components/PricingModal';
import { useDebounce } from '../hooks/useDebounce';
import styles from './Productos.module.css';
import axios from 'axios';
import { useAuthStore } from '../store/authStore';
import { usePermisos } from '../contexts/PermisosContext';
import ExportModal from '../components/ExportModal';
import xlsIcon from '../assets/xls.svg';
import CalcularWebModal from '../components/CalcularWebModal';
import ModalInfoProducto from '../components/ModalInfoProducto';
import './Productos.css';

export default function Productos() {
  const [productos, setProductos] = useState([]);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState(null);
  const [productoSeleccionado, setProductoSeleccionado] = useState(null);
  const [searchInput, setSearchInput] = useState('');
  const [page, setPage] = useState(1);
  const [editandoPrecio, setEditandoPrecio] = useState(null);
  const [precioTemp, setPrecioTemp] = useState('');
  const [filtroStock, setFiltroStock] = useState("todos");
  const [filtroPrecio, setFiltroPrecio] = useState("todos");
  const [totalProductos, setTotalProductos] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  const [auditoriaVisible, setAuditoriaVisible] = useState(false);
  const [auditoriaData, setAuditoriaData] = useState([]);
  const [editandoRebate, setEditandoRebate] = useState(null);
  const [rebateTemp, setRebateTemp] = useState({ participa: false, porcentaje: 3.8 });
  const [mostrarExportModal, setMostrarExportModal] = useState(false);
  const [editandoWebTransf, setEditandoWebTransf] = useState(null);
  const [webTransfTemp, setWebTransfTemp] = useState({ participa: false, porcentaje: 6.0, preservar: false });
  const [mostrarCalcularWebModal, setMostrarCalcularWebModal] = useState(false);
  const [marcas, setMarcas] = useState([]);
  const [marcasSeleccionadas, setMarcasSeleccionadas] = useState([]);
  const [busquedaMarca, setBusquedaMarca] = useState('');
  const [ordenColumna, setOrdenColumna] = useState(null);
  const [ordenDireccion, setOrdenDireccion] = useState('asc');
  const [ordenColumnas, setOrdenColumnas] = useState([]);
  const [subcategorias, setSubcategorias] = useState([]);
  const [subcategoriasSeleccionadas, setSubcategoriasSeleccionadas] = useState([]);
  const [busquedaSubcategoria, setBusquedaSubcategoria] = useState('');
  const [usuarios, setUsuarios] = useState([]);
  const [tiposAccion, setTiposAccion] = useState([]);
  const [filtrosAuditoria, setFiltrosAuditoria] = useState({
    usuarios: [],
    tipos_accion: [],
    fecha_desde: '',
    fecha_hasta: ''
  });
  const [panelFiltroActivo, setPanelFiltroActivo] = useState(null); // 'marcas', 'subcategorias', 'auditoria', null
  const [filtroRebate, setFiltroRebate] = useState(null);
  const [filtroOferta, setFiltroOferta] = useState(null);
  const [filtroWebTransf, setFiltroWebTransf] = useState(null);
  const [filtroTiendaNube, setFiltroTiendaNube] = useState(null); // con_descuento, sin_descuento, no_publicado
  const [filtroMarkupClasica, setFiltroMarkupClasica] = useState(null);
  const [filtroMarkupRebate, setFiltroMarkupRebate] = useState(null);
  const [filtroMarkupOferta, setFiltroMarkupOferta] = useState(null);
  const [filtroMarkupWebTransf, setFiltroMarkupWebTransf] = useState(null);
  const [filtroOutOfCards, setFiltroOutOfCards] = useState(null);
  const [filtroMLA, setFiltroMLA] = useState(null); // con_mla, sin_mla
  const [filtroEstadoMLA, setFiltroEstadoMLA] = useState(null); // 'activa', 'pausada'
  const [filtroNuevos, setFiltroNuevos] = useState(null); // ultimos_7_dias
  const [filtroTiendaOficial, setFiltroTiendaOficial] = useState(null); // '57997', '2645', '144', '191942'
  const [mostrarFiltrosAvanzados, setMostrarFiltrosAvanzados] = useState(false);
  const [colorDropdownAbierto, setColorDropdownAbierto] = useState(null); // item_id del producto
  const [coloresSeleccionados, setColoresSeleccionados] = useState([]);
  const [pms, setPms] = useState([]);
  const [pmsSeleccionados, setPmsSeleccionados] = useState([]);
  const [marcasPorPM, setMarcasPorPM] = useState([]); // Marcas filtradas por PMs seleccionados
  const [subcategoriasPorPM, setSubcategoriasPorPM] = useState([]); // Subcategorías filtradas por PMs seleccionados

  // Estados para navegación por teclado
  const [celdaActiva, setCeldaActiva] = useState(null); // { rowIndex, colIndex }
  const [modoNavegacion, setModoNavegacion] = useState(false);
  const [mostrarShortcutsHelp, setMostrarShortcutsHelp] = useState(false);

  // Estados para vista de cuotas
  const [vistaModoCuotas, setVistaModoCuotas] = useState(false); // false = vista normal, true = vista cuotas
  const [recalcularCuotasAuto, setRecalcularCuotasAuto] = useState(() => {
    // Leer del localStorage, por defecto true
    const saved = localStorage.getItem('recalcularCuotasAuto');
    return saved === null ? true : JSON.parse(saved);
  });
  const [editandoCuota, setEditandoCuota] = useState(null); // {item_id, tipo: '3'|'6'|'9'|'12'}
  const [cuotaTemp, setCuotaTemp] = useState('');

  // Selección múltiple
  const [productosSeleccionados, setProductosSeleccionados] = useState(new Set());
  const [ultimoSeleccionado, setUltimoSeleccionado] = useState(null);

  // Modal de configuración individual
  const [mostrarModalConfig, setMostrarModalConfig] = useState(false);
  const [productoConfig, setProductoConfig] = useState(null);
  const [configTemp, setConfigTemp] = useState({
    recalcular_cuotas_auto: null,
    markup_adicional_cuotas_custom: null
  });
  // Modal de información
  const [mostrarModalInfo, setMostrarModalInfo] = useState(false);
  const [productoInfo, setProductoInfo] = useState(null);

  // Toast notification
  const [toast, setToast] = useState(null);

  // Modal de ban
  const [mostrarModalBan, setMostrarModalBan] = useState(false);
  const [productoBan, setProductoBan] = useState(null);
  const [palabraVerificacion, setPalabraVerificacion] = useState('');
  const [palabraObjetivo, setPalabraObjetivo] = useState('');
  const [motivoBan, setMotivoBan] = useState('');

  const user = useAuthStore((state) => state.user);
  const { tienePermiso } = usePermisos();

  // Permisos granulares de edición
  const puedeEditarPrecioClasica = tienePermiso('productos.editar_precio_clasica');
  const puedeEditarCuotas = tienePermiso('productos.editar_precio_cuotas');
  const puedeToggleRebate = tienePermiso('productos.toggle_rebate');
  const puedeToggleWebTransf = tienePermiso('productos.toggle_web_transferencia');
  const puedeMarcarColor = tienePermiso('productos.marcar_color');
  const puedeMarcarColorLote = tienePermiso('productos.marcar_color_lote');
  const puedeCalcularWebMasivo = tienePermiso('productos.calcular_web_masivo');
  const puedeToggleOutOfCards = tienePermiso('productos.toggle_out_of_cards');

  // Legacy: puedeEditar es true si tiene al menos un permiso de edición
  const puedeEditar = puedeEditarPrecioClasica || puedeEditarCuotas || puedeToggleRebate || puedeToggleWebTransf;

  // Columnas navegables según la vista activa
  const columnasNavegablesNormal = ['precio_clasica', 'precio_rebate', 'mejor_oferta', 'precio_web_transf'];
  const columnasNavegablesCuotas = ['precio_clasica', 'cuotas_3', 'cuotas_6', 'cuotas_9', 'cuotas_12'];
  const columnasEditables = vistaModoCuotas ? columnasNavegablesCuotas : columnasNavegablesNormal;

  const debouncedSearch = useDebounce(searchInput, 500);

  // URL Query Params para persistencia de filtros
  const [searchParams, setSearchParams] = useSearchParams();
  const [filtrosInicializados, setFiltrosInicializados] = useState(false);

  // Función para mostrar toast
  const showToast = (message, type = 'success') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000); // Desaparece después de 3 segundos
  };

  const API_URL = 'https://pricing.gaussonline.com.ar/api';

  // Función para sincronizar filtros a la URL
  const syncFiltersToURL = () => {
    const params = new URLSearchParams();

    // Search
    if (searchInput) params.set('search', searchInput);

    // Stock
    if (filtroStock && filtroStock !== 'todos') params.set('stock', filtroStock);

    // Precio
    if (filtroPrecio && filtroPrecio !== 'todos') params.set('precio', filtroPrecio);

    // Marcas (array -> comma separated string)
    if (marcasSeleccionadas.length > 0) params.set('marcas', marcasSeleccionadas.join(','));

    // Subcategorías
    if (subcategoriasSeleccionadas.length > 0) params.set('subcats', subcategoriasSeleccionadas.join(','));

    // PMs
    if (pmsSeleccionados.length > 0) params.set('pms', pmsSeleccionados.join(','));

    // Rebate
    if (filtroRebate) params.set('rebate', filtroRebate);

    // Oferta
    if (filtroOferta) params.set('oferta', filtroOferta);

    // Web Transf
    if (filtroWebTransf) params.set('webtransf', filtroWebTransf);

    // Tienda Nube
    if (filtroTiendaNube) params.set('tiendanube', filtroTiendaNube);

    // Markup Clásica
    if (filtroMarkupClasica) params.set('mkclasica', filtroMarkupClasica);

    // Markup Rebate
    if (filtroMarkupRebate) params.set('mkrebate', filtroMarkupRebate);

    // Markup Oferta
    if (filtroMarkupOferta) params.set('mkoferta', filtroMarkupOferta);

    // Markup Web Transf
    if (filtroMarkupWebTransf) params.set('mkwebtransf', filtroMarkupWebTransf);

    // Out of Cards
    if (filtroOutOfCards) params.set('outofcards', filtroOutOfCards);

    // MLA
    if (filtroMLA) params.set('mla', filtroMLA);

    // Estado MLA
    if (filtroEstadoMLA) params.set('estado_mla', filtroEstadoMLA);

    // Nuevos
    if (filtroNuevos) params.set('nuevos', filtroNuevos);

    // Tienda Oficial
    if (filtroTiendaOficial) params.set('tienda_oficial', filtroTiendaOficial);

    // Colores
    if (coloresSeleccionados.length > 0) params.set('colores', coloresSeleccionados.join(','));

    // Página
    if (page > 1) params.set('page', page.toString());

    // Page Size
    if (pageSize !== 50) params.set('pagesize', pageSize.toString());

    // Filtros de Auditoría
    if (filtrosAuditoria.usuarios.length > 0) params.set('audit_usuarios', filtrosAuditoria.usuarios.join(','));
    if (filtrosAuditoria.tipos_accion.length > 0) params.set('audit_tipos', filtrosAuditoria.tipos_accion.join(','));
    if (filtrosAuditoria.fecha_desde) params.set('audit_desde', filtrosAuditoria.fecha_desde);
    if (filtrosAuditoria.fecha_hasta) params.set('audit_hasta', filtrosAuditoria.fecha_hasta);

    setSearchParams(params, { replace: true });
  };

  // Función para cargar filtros desde la URL
  const loadFiltersFromURL = () => {
    const search = searchParams.get('search');
    const stock = searchParams.get('stock');
    const precio = searchParams.get('precio');
    const marcas = searchParams.get('marcas');
    const subcats = searchParams.get('subcats');
    const pms = searchParams.get('pms');
    const rebate = searchParams.get('rebate');
    const oferta = searchParams.get('oferta');
    const webtransf = searchParams.get('webtransf');
    const tiendanube = searchParams.get('tiendanube');
    const mkclasica = searchParams.get('mkclasica');
    const mkrebate = searchParams.get('mkrebate');
    const mkoferta = searchParams.get('mkoferta');
    const mkwebtransf = searchParams.get('mkwebtransf');
    const outofcards = searchParams.get('outofcards');
    const mla = searchParams.get('mla');
    const estado_mla = searchParams.get('estado_mla');
    const nuevos = searchParams.get('nuevos');
    const colores = searchParams.get('colores');
    const pageParam = searchParams.get('page');
    const pagesizeParam = searchParams.get('pagesize');
    const auditUsuarios = searchParams.get('audit_usuarios');
    const auditTipos = searchParams.get('audit_tipos');
    const auditDesde = searchParams.get('audit_desde');
    const auditHasta = searchParams.get('audit_hasta');

    // Setear estados desde URL
    if (search) setSearchInput(search);
    if (stock) setFiltroStock(stock);
    if (precio) setFiltroPrecio(precio);
    if (marcas) setMarcasSeleccionadas(marcas.split(',').map(m => m.trim()).filter(Boolean));
    if (subcats) setSubcategoriasSeleccionadas(subcats.split(',').map(s => s.trim()).filter(Boolean));
    if (pms) setPmsSeleccionados(pms.split(',').map(p => p.trim()).filter(Boolean));
    if (rebate) setFiltroRebate(rebate);
    if (oferta) setFiltroOferta(oferta);
    if (webtransf) setFiltroWebTransf(webtransf);
    if (tiendanube) setFiltroTiendaNube(tiendanube);
    if (mkclasica) setFiltroMarkupClasica(mkclasica);
    if (mkrebate) setFiltroMarkupRebate(mkrebate);
    if (mkoferta) setFiltroMarkupOferta(mkoferta);
    if (mkwebtransf) setFiltroMarkupWebTransf(mkwebtransf);
    if (outofcards) setFiltroOutOfCards(outofcards);
    if (mla) setFiltroMLA(mla);
    if (estado_mla) setFiltroEstadoMLA(estado_mla);
    if (nuevos) setFiltroNuevos(nuevos);
    if (colores) setColoresSeleccionados(colores.split(',').map(c => c.trim()).filter(Boolean));
    if (pageParam) setPage(parseInt(pageParam, 10));
    if (pagesizeParam) setPageSize(parseInt(pagesizeParam, 10));

    // Filtros de Auditoría
    if (auditUsuarios || auditTipos || auditDesde || auditHasta) {
      setFiltrosAuditoria({
        usuarios: auditUsuarios ? auditUsuarios.split(',').map(u => u.trim()).filter(Boolean) : [],
        tipos_accion: auditTipos ? auditTipos.split(',').map(t => t.trim()).filter(Boolean) : [],
        fecha_desde: auditDesde || '',
        fecha_hasta: auditHasta || ''
      });
    }
  };

  // useEffect inicial: cargar filtros desde URL al montar el componente
  useEffect(() => {
    loadFiltersFromURL();
    // Marcar que los filtros ya fueron inicializados
    setFiltrosInicializados(true);
  }, []); // Solo al montar

  // useEffect para sincronizar filtros a URL cuando cambian
  useEffect(() => {
    // Solo sincronizar después de que los filtros fueron inicializados desde URL
    if (filtrosInicializados) {
      syncFiltersToURL();
    }
  }, [
    filtrosInicializados,
    searchInput,
    filtroStock,
    filtroPrecio,
    marcasSeleccionadas,
    subcategoriasSeleccionadas,
    pmsSeleccionados,
    filtroRebate,
    filtroOferta,
    filtroWebTransf,
    filtroTiendaNube,
    filtroMarkupClasica,
    filtroMarkupRebate,
    filtroMarkupOferta,
    filtroMarkupWebTransf,
    filtroOutOfCards,
    filtroMLA,
    filtroEstadoMLA,
    filtroNuevos,
    filtroTiendaOficial,
    coloresSeleccionados,
    audit_usuarios: filtrosAuditoria.usuarios,
    audit_tipos_accion: filtrosAuditoria.tipos_accion,
    audit_fecha_desde: filtrosAuditoria.fecha_desde,
    audit_fecha_hasta: filtrosAuditoria.fecha_hasta
  }}
          showToast={showToast}
        />
      )}

      {mostrarExportModal && (
        <ExportModal
          onClose={() => setMostrarExportModal(false)}
          filtrosActivos={{
            search: debouncedSearch,
            con_stock: filtroStock === 'con_stock' ? true : filtroStock === 'sin_stock' ? false : null,
            con_precio: filtroPrecio === 'con_precio' ? true : filtroPrecio === 'sin_precio' ? false : null,
            marcas: marcasSeleccionadas,
            subcategorias: subcategoriasSeleccionadas,
            pmsSeleccionados,
            filtroRebate,
            filtroOferta,
            filtroWebTransf,
            filtroTiendaNube,
            filtroMarkupClasica,
            filtroMarkupRebate,
            filtroMarkupOferta,
            filtroMarkupWebTransf,
            filtroOutOfCards,
            filtroMLA,
            filtroEstadoMLA,
            filtroNuevos,
            coloresSeleccionados,
            audit_usuarios: filtrosAuditoria.usuarios,
            audit_tipos_accion: filtrosAuditoria.tipos_accion,
            audit_fecha_desde: filtrosAuditoria.fecha_desde,
            audit_fecha_hasta: filtrosAuditoria.fecha_hasta
          }}
          showToast={showToast}
        />
      )}

      {/* Modal de confirmación de ban */}
      {mostrarModalBan && productoBan && (
        <div className="modal-ban-overlay">
          <div className="modal-ban-content">
            <h2 className="modal-ban-title">⚠️ Confirmar Ban</h2>

            <div className="modal-ban-info">
              <p><strong>Producto:</strong> {productoBan.codigo}</p>
              <p><strong>Descripción:</strong> {productoBan.descripcion}</p>
              <p><strong>Item ID:</strong> {productoBan.item_id}</p>
              {productoBan.ean && <p><strong>EAN:</strong> {productoBan.ean}</p>}
            </div>

            <div className="modal-ban-warning">
              <p>Para confirmar, escribe la siguiente palabra:</p>
              <p className="modal-ban-word">{palabraObjetivo}</p>
            </div>

            <div className="modal-ban-field">
              <label>Palabra de verificación:</label>
              <input
                type="text"
                value={palabraVerificacion}
                onChange={(e) => setPalabraVerificacion(e.target.value)}
                placeholder="Escribe la palabra aquí"
                className="modal-ban-input"
                autoFocus
              />
            </div>

            <div className="modal-ban-field">
              <label>Motivo (opcional):</label>
              <textarea
                value={motivoBan}
                onChange={(e) => setMotivoBan(e.target.value)}
                placeholder="Razón por la cual se banea este producto"
                className="modal-ban-textarea"
              />
            </div>

            <div className="modal-ban-actions">
              <button
                onClick={() => {
                  setMostrarModalBan(false);
                  setProductoBan(null);
                  setPalabraVerificacion('');
                  setPalabraObjetivo('');
                  setMotivoBan('');
                }}
                className="modal-ban-btn-cancel"
              >
                Cancelar
              </button>
              <button
                onClick={confirmarBan}
                className="modal-ban-btn-confirm"
              >
                Confirmar Ban
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Barra de acciones flotante para selección múltiple */}
      {productosSeleccionados.size > 0 && (
        <div style={{
          position: 'fixed',
          bottom: '20px',
          left: '50%',
          transform: 'translateX(-50%)',
          backgroundColor: '#2563eb',
          color: 'white',
          padding: '15px 25px',
          borderRadius: '8px',
          boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
          zIndex: 1000,
          display: 'flex',
          alignItems: 'center',
          gap: '15px'
        }}>
          <span style={{ fontWeight: 'bold' }}>
            {productosSeleccionados.size} producto{productosSeleccionados.size !== 1 ? 's' : ''} seleccionado{productosSeleccionados.size !== 1 ? 's' : ''}
          </span>
          {puedeMarcarColorLote && (
          <div style={{ display: 'flex', gap: '8px' }}>
            {COLORES_DISPONIBLES.map(c => (
              <button
                key={c.id}
                onClick={() => pintarLote(c.id)}
                style={{
                  width: '30px',
                  height: '30px',
                  borderRadius: '4px',
                  border: '2px solid white',
                  backgroundColor: c.color || '#f3f4f6',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center'
                }}
                title={c.nombre}
              >
                {!c.id && '✕'}
              </button>
            ))}
          </div>
          )}
          <button
            onClick={limpiarSeleccion}
            style={{
              backgroundColor: '#dc2626',
              color: 'white',
              border: 'none',
              padding: '8px 15px',
              borderRadius: '4px',
              cursor: 'pointer',
              fontWeight: 'bold'
            }}
          >
            Cancelar
          </button>
        </div>
      )}

      {/* Modal de configuración individual */}
      {mostrarModalConfig && productoConfig && (
        <div className="shortcuts-modal-overlay" onClick={() => setMostrarModalConfig(false)}>
          <div className="shortcuts-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: '500px' }}>
            <div className="shortcuts-header">
              <h2>⚙️ Configuración de Cuotas</h2>
              <button onClick={() => setMostrarModalConfig(false)} className="close-btn">✕</button>
            </div>
            <div style={{ padding: '20px' }}>
              <h3 style={{ marginBottom: '10px' }}>{productoConfig.descripcion}</h3>
              <p style={{ color: '#666', marginBottom: '20px', fontSize: '14px' }}>
                Código: {productoConfig.codigo} | Marca: {productoConfig.marca}
              </p>

              <div style={{ marginBottom: '20px' }}>
                <label style={{ display: 'block', fontWeight: 'bold', marginBottom: '8px' }}>
                  Recalcular cuotas automáticamente:
                </label>
                <select
                  value={configTemp.recalcular_cuotas_auto === null ? 'null' : configTemp.recalcular_cuotas_auto.toString()}
                  onChange={(e) => setConfigTemp({ ...configTemp, recalcular_cuotas_auto: e.target.value })}
                  style={{
                    width: '100%',
                    padding: '8px',
                    borderRadius: '4px',
                    border: '1px solid #d1d5db'
                  }}
                >
                  <option value="null">Usar configuración global ({recalcularCuotasAuto ? 'Sí' : 'No'})</option>
                  <option value="true">Siempre recalcular</option>
                  <option value="false">Nunca recalcular</option>
                </select>
              </div>

              <div style={{ marginBottom: '20px' }}>
                <label style={{ display: 'block', fontWeight: 'bold', marginBottom: '8px' }}>
                  Markup adicional para cuotas (%):
                </label>
                <input
                  type="number"
                  min="0"
                  max="100"
                  step="0.1"
                  value={configTemp.markup_adicional_cuotas_custom}
                  onChange={(e) => setConfigTemp({ ...configTemp, markup_adicional_cuotas_custom: e.target.value })}
                  onFocus={(e) => e.target.select()}
                  placeholder="Dejar vacío para usar configuración global"
                  style={{
                    width: '100%',
                    padding: '8px',
                    borderRadius: '4px',
                    border: '1px solid #d1d5db'
                  }}
                />
                <p style={{ fontSize: '12px', color: '#666', marginTop: '5px' }}>
                  Dejar vacío para usar la configuración global
                </p>
              </div>

              <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
                <button
                  onClick={() => setMostrarModalConfig(false)}
                  style={{
                    padding: '10px 20px',
                    borderRadius: '4px',
                    border: '1px solid #d1d5db',
                    backgroundColor: 'white',
                    cursor: 'pointer'
                  }}
                >
                  Cancelar
                </button>
                <button
                  onClick={guardarConfigIndividual}
                  style={{
                    padding: '10px 20px',
                    borderRadius: '4px',
                    border: 'none',
                    backgroundColor: '#2563eb',
                    color: 'white',
                    cursor: 'pointer',
                    fontWeight: 'bold'
                  }}
                >
                  Guardar
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Modal de ayuda de shortcuts */}
      {mostrarShortcutsHelp && (
        <div className="shortcuts-modal-overlay" onClick={() => setMostrarShortcutsHelp(false)}>
          <div className="shortcuts-modal" onClick={(e) => e.stopPropagation()}>
            <div className="shortcuts-header">
              <h2>⌨️ Atajos de Teclado</h2>
              <button onClick={() => setMostrarShortcutsHelp(false)} className="close-btn">✕</button>
            </div>
            <div className="shortcuts-content">
              <div className="shortcuts-section">
                <h3>Navegación en Tabla</h3>
                <div className="shortcut-item">
                  <kbd>Enter</kbd>
                  <span>Activar modo navegación</span>
                </div>
                <div className="shortcut-item">
                  <kbd>↑</kbd> <kbd>↓</kbd> <kbd>←</kbd> <kbd>→</kbd>
                  <span>Navegar por celdas (una a la vez)</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Shift</kbd> + <kbd>↑</kbd>
                  <span>Ir al inicio de la tabla</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Shift</kbd> + <kbd>↓</kbd>
                  <span>Ir al final de la tabla</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Re Pág</kbd> (PageUp)
                  <span>Subir 10 filas</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Av Pág</kbd> (PageDown)
                  <span>Bajar 10 filas</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Home</kbd>
                  <span>Ir a primera columna</span>
                </div>
                <div className="shortcut-item">
                  <kbd>End</kbd>
                  <span>Ir a última columna</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Enter</kbd> o <kbd>Espacio</kbd>
                  <span>Editar celda activa</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Tab</kbd> (en edición)
                  <span>Navegar entre campos del formulario</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Esc</kbd>
                  <span>Salir de edición (mantiene navegación)</span>
                </div>
              </div>

              <div className="shortcuts-section">
                <h3>Acciones Rápidas (en fila activa)</h3>
                <div className="shortcut-item">
                  <kbd>Ctrl</kbd>+<kbd>I</kbd>
                  <span>Ver información detallada del producto</span>
                </div>
                <div className="shortcut-item">
                  <kbd>0</kbd>-<kbd>7</kbd>
                  <span>Asignar color (0=Sin color, 1=Rojo, 2=Naranja, 3=Amarillo, 4=Verde, 5=Azul, 6=Púrpura, 7=Gris)</span>
                </div>
                <div className="shortcut-item">
                  <kbd>R</kbd>
                  <span>Toggle Rebate ON/OFF</span>
                </div>
                <div className="shortcut-item">
                  <kbd>W</kbd>
                  <span>Toggle Web Transferencia ON/OFF</span>
                </div>
                <div className="shortcut-item">
                  <kbd>O</kbd>
                  <span>Toggle Out of Cards</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Ctrl</kbd>+<kbd>F1</kbd> o <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>1</kbd>
                  <span>Copiar código del producto</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Ctrl</kbd>+<kbd>F2</kbd> o <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>2</kbd>
                  <span>Copiar primer enlace ML</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Ctrl</kbd>+<kbd>F3</kbd> o <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>3</kbd>
                  <span>Copiar segundo enlace ML</span>
                </div>
              </div>

              <div className="shortcuts-section">
                <h3>Filtros</h3>
                <div className="shortcut-item">
                  <kbd>Ctrl</kbd> + <kbd>F</kbd>
                  <span>Buscar productos</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Alt</kbd> + <kbd>M</kbd>
                  <span>Toggle filtro Marcas</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Alt</kbd> + <kbd>S</kbd>
                  <span>Toggle filtro Subcategorías</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Alt</kbd> + <kbd>P</kbd>
                  <span>Toggle filtro PMs</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Alt</kbd> + <kbd>C</kbd>
                  <span>Toggle filtro Colores</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Alt</kbd> + <kbd>A</kbd>
                  <span>Toggle filtro Auditoría</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Alt</kbd> + <kbd>F</kbd>
                  <span>Toggle filtros avanzados</span>
                </div>
              </div>

              <div className="shortcuts-section">
                <h3>🔍 Operadores de Búsqueda</h3>
                <div className="shortcut-item">
                  <kbd>ean:123456</kbd>
                  <span>Búsqueda exacta por EAN</span>
                </div>
                <div className="shortcut-item">
                  <kbd>codigo:ABC123</kbd>
                  <span>Búsqueda exacta por código</span>
                </div>
                <div className="shortcut-item">
                  <kbd>marca:Samsung</kbd>
                  <span>Búsqueda exacta por marca</span>
                </div>
                <div className="shortcut-item">
                  <kbd>desc:texto</kbd>
                  <span>Búsqueda en descripción (contiene)</span>
                </div>
                <div className="shortcut-item">
                  <kbd>*123</kbd>
                  <span>Termina en "123" (en cualquier campo)</span>
                </div>
                <div className="shortcut-item">
                  <kbd>123*</kbd>
                  <span>Comienza con "123" (en cualquier campo)</span>
                </div>
                <div className="shortcut-item">
                  <kbd>texto</kbd>
                  <span>Búsqueda normal (contiene en desc, marca o código)</span>
                </div>
              </div>

              <div className="shortcuts-section">
                <h3>Acciones Globales</h3>
                <div className="shortcut-item">
                  <kbd>Ctrl</kbd> + <kbd>E</kbd>
                  <span>Abrir modal de exportar</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Ctrl</kbd> + <kbd>K</kbd>
                  <span>Calcular Web Transferencia masivo</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Alt</kbd> + <kbd>V</kbd>
                  <span>Toggle Vista Normal / Vista Cuotas</span>
                </div>
                <div className="shortcut-item">
                  <kbd>Alt</kbd> + <kbd>R</kbd>
                  <span>Toggle Auto-recalcular cuotas</span>
                </div>
                <div className="shortcut-item">
                  <kbd>?</kbd>
                  <span>Mostrar/ocultar esta ayuda</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Indicador de modo navegación */}
      {modoNavegacion && (
        <div className="navigation-indicator">
          ⌨️ Modo Navegación Activo - Presiona <kbd>Esc</kbd> para salir o <kbd>?</kbd> para ayuda
        </div>
      )}

      {/* Toast notification */}
      {toast && (
        <div className={`${styles.toast} ${toast.type === 'error' ? styles.error : ''}`}>
          {toast.message}
        </div>
      )}
    </div>
      );
    }
