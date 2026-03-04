/**
 * Modal de caso RMA - 7 tabs con todos los campos del ciclo de vida.
 *
 * Tabs: Info | Recepción | Revisión | Reclamo ML | Proveedor | Proceso | Historial
 *
 * - Caso nuevo: solo tab Info con 3 formas de agregar items:
 *   1. Búsqueda de traza (por serie o ML ID) → autocompleta datos de la venta
 *   2. Búsqueda de producto (por EAN/código/descripción) → busca en catálogo del ERP
 *   3. Item manual → carga libre sin datos previos
 * - Caso existente: todas las tabs, edición inline por item via PUT
 * - Campos caso-level se guardan con el botón Guardar
 * - Campos item-level se guardan inline (onChange → PUT)
 */

import { useState, useEffect, useRef } from 'react';
import { usePermisos } from '../contexts/PermisosContext';
import { useDebounce } from '../hooks/useDebounce';
import api from '../services/api';
import ModalTesla, { ModalSection, ModalFooterButtons, ModalLoading } from './ModalTesla';
import { Search, Plus, Trash2, ExternalLink, Clock, User, PenLine, ShoppingCart, FileText, CalendarDays, Tag, Phone, Mail, AlertTriangle, Shield, Hash, Package, RotateCcw, MessageSquare, Star, Truck, ArrowLeftRight, DollarSign } from 'lucide-react';
import styles from './ModalRma.module.css';

// ── Traducciones de campos de claims ML ──────────────────────────────────────
const TRIAGE_TAGS_ES = {
  repentant: 'Arrepentimiento',
  defective: 'Defectuoso',
  not_working: 'No funciona',
  different: 'Producto diferente',
  incomplete: 'Incompleto',
};

const EXPECTED_RESOLUTIONS_ES = {
  return_product: 'Devolución',
  change_product: 'Cambio',
  refund: 'Reembolso',
  product: 'Producto',
  other: 'Otro',
};

const CLAIM_STAGE_ES = {
  claim: 'Reclamo',
  dispute: 'Mediación',
  recontact: 'Recontacto',
  stale: 'Estancado',
  none: 'N/A',
};

const CLAIM_ACTIONS_ES = {
  refund: 'Reembolso',
  allow_return: 'Autorizar devolución',
  allow_return_label: 'Generar etiqueta de devolución',
  allow_partial_refund: 'Reembolso parcial',
  open_dispute: 'Abrir mediación',
  send_message_to_complainant: 'Enviar mensaje al comprador',
  send_message_to_mediator: 'Enviar mensaje al mediador',
  send_potential_shipping: 'Promesa de envío',
  add_shipping_evidence: 'Evidencia de envío',
  send_tracking_number: 'Enviar tracking',
  send_attachments: 'Enviar adjuntos',
  return_review: 'Revisar devolución',
};

const RESOLUTION_REASON_ES = {
  payment_refunded: 'Pago devuelto',
  item_returned: 'Producto devuelto',
  prefered_to_keep_product: 'Prefirió quedarse el producto',
  partial_refunded: 'Reembolso parcial',
  opened_claim_by_mistake: 'Reclamo por error',
  worked_out_with_seller: 'Arregló con el vendedor',
  seller_sent_product: 'Vendedor envió el producto',
  seller_explained_functions: 'Vendedor explicó funcionamiento',
  respondent_timeout: 'Vendedor no respondió',
  coverage_decision: 'Cobertura de ML',
  item_changed: 'Producto cambiado',
  change_expired: 'Cambio expirado',
  low_cost: 'Bajo costo (envío > producto)',
  already_shipped: 'Ya fue enviado',
  not_delivered: 'No entregado',
  return_expired: 'Devolución vencida',
  return_canceled: 'Devolución cancelada',
};

const CLOSED_BY_ES = {
  seller: 'vendedor',
  buyer: 'comprador',
  mediator: 'mediador',
};

// ── Traducciones de devolución (return) ──────────────────────────────────────
const RETURN_STATUS_ES = {
  pending: 'Pendiente',
  label_generated: 'Etiqueta generada',
  ready_to_ship: 'Listo para enviar',
  shipped: 'Enviado',
  delivered: 'Entregado',
  expired: 'Vencido',
  cancelled: 'Cancelado',
  not_returned: 'No devuelto',
  waiting_for_return: 'Esperando devolución',
};

const RETURN_SUBTYPE_ES = {
  low_cost: 'Bajo costo',
  return_partial: 'Devolución parcial',
  return_total: 'Devolución total',
};

const RETURN_MONEY_STATUS_ES = {
  retained: 'Retenido',
  refunded: 'Reembolsado',
  available: 'Disponible',
  pending: 'Pendiente',
};

const SHIPMENT_STATUS_ES = {
  pending: 'Pendiente',
  ready_to_ship: 'Listo para enviar',
  shipped: 'En tránsito',
  delivered: 'Entregado',
  cancelled: 'Cancelado',
  not_delivered: 'No entregado',
};

// ── Traducciones de cambio (change) ──────────────────────────────────────────
const CHANGE_TYPE_ES = {
  change: 'Cambio',
  replace: 'Reemplazo',
};

const CHANGE_STATUS_ES = {
  pending: 'Pendiente',
  processing: 'En proceso',
  completed: 'Completado',
  cancelled: 'Cancelado',
  expired: 'Vencido',
};

// ── Traducciones de resoluciones esperadas ───────────────────────────────────
const EXPECTED_RES_STATUS_ES = {
  pending: 'Pendiente',
  accepted: 'Aceptada',
  rejected: 'Rechazada',
};

const PLAYER_ROLE_ES = {
  complainant: 'Comprador',
  respondent: 'Vendedor',
  mediator: 'Mediador',
};

/**
 * Sanitiza HTML permitiendo solo tags seguros para mensajes de ML.
 * Remueve scripts, event handlers y tags peligrosos.
 */
const sanitizeMessageHtml = (html) => {
  if (!html) return '';
  const ALLOWED_TAGS = ['strong', 'b', 'em', 'i', 'u', 'br', 'p', 'ul', 'ol', 'li', 'a'];
  const div = document.createElement('div');
  div.innerHTML = html;
  // Remove scripts and event handlers
  for (const el of div.querySelectorAll('script, style, iframe, object, embed')) {
    el.remove();
  }
  for (const el of div.querySelectorAll('*')) {
    // Strip event handlers (onclick, onerror, etc.)
    for (const attr of [...el.attributes]) {
      if (attr.name.startsWith('on') || attr.name === 'style') {
        el.removeAttribute(attr.name);
      }
    }
    // Strip disallowed tags but keep their text content
    if (!ALLOWED_TAGS.includes(el.tagName.toLowerCase())) {
      el.replaceWith(...el.childNodes);
    }
  }
  // Sanitize <a> tags — only allow href, add safety attrs
  for (const a of div.querySelectorAll('a')) {
    const href = a.getAttribute('href') || '';
    if (!href.startsWith('http')) {
      a.replaceWith(...a.childNodes);
    } else {
      a.setAttribute('target', '_blank');
      a.setAttribute('rel', 'noopener noreferrer');
    }
  }
  return div.innerHTML;
};

const IMG_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.webp'];
const isImageAttachment = (key) => {
  if (!key) return false;
  const lower = typeof key === 'string' ? key.toLowerCase() : '';
  return IMG_EXTENSIONS.some((ext) => lower.endsWith(ext));
};

const attachmentProxyUrl = (key) => `/api/seriales/ml-attachment?id=${encodeURIComponent(key)}`;

export default function ModalRma({ caso, onClose }) {
  const { tienePermiso } = usePermisos();
  const puedeGestionar = tienePermiso('rma.gestionar');
  const esNuevo = !caso;

  const [activeTab, setActiveTab] = useState('info');
  const [loading, setLoading] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const [opciones, setOpciones] = useState({});
  const [casoData, setCasoData] = useState(caso || {});
  const [historial, setHistorial] = useState([]);

  // Búsqueda de traza para nuevo caso
  const [searchSerial, setSearchSerial] = useState('');
  const [trazaResult, setTrazaResult] = useState(null);
  const [buscandoTraza, setBuscandoTraza] = useState(false);

  // Búsqueda de producto por EAN/código/descripción
  const [searchProducto, setSearchProducto] = useState('');
  const [productoResults, setProductoResults] = useState([]);
  const [buscandoProducto, setBuscandoProducto] = useState(false);
  const debouncedSearchProducto = useDebounce(searchProducto, 400);
  const productoInputRef = useRef(null);

  // Item manual
  const [showManualForm, setShowManualForm] = useState(false);
  const [manualItem, setManualItem] = useState({ producto_desc: '', precio: '', ean: '', serial_number: '' });

  // Claim messages modal
  const [claimMsgsOpen, setClaimMsgsOpen] = useState(false);
  const [claimMsgs, setClaimMsgs] = useState([]);
  const [orderMsgs, setOrderMsgs] = useState([]);
  const [claimMsgsLoading, setClaimMsgsLoading] = useState(false);
  const [claimMsgsClaimId, setClaimMsgsClaimId] = useState(null);
  const [lightboxUrl, setLightboxUrl] = useState(null);

  useEffect(() => {
    cargarOpciones();
    if (caso?.id) {
      cargarCasoCompleto();
      cargarHistorial();
    }
  }, []);

  // Búsqueda de productos con debounce
  useEffect(() => {
    if (!esNuevo) return;
    if (!debouncedSearchProducto || debouncedSearchProducto.length < 2) {
      setProductoResults([]);
      return;
    }
    const buscarProductos = async () => {
      setBuscandoProducto(true);
      try {
        const { data } = await api.get('/productos', {
          params: { search: debouncedSearchProducto, page_size: 10, page: 1 },
        });
        setProductoResults(data.productos || []);
      } catch {
        setProductoResults([]);
      } finally {
        setBuscandoProducto(false);
      }
    };
    buscarProductos();
  }, [debouncedSearchProducto, esNuevo]);

  const cargarOpciones = async () => {
    try {
      const { data } = await api.get('/rma-seguimiento/opciones', { params: { solo_activas: true } });
      const grouped = {};
      for (const op of data) {
        if (!grouped[op.categoria]) grouped[op.categoria] = [];
        grouped[op.categoria].push(op);
      }
      setOpciones(grouped);
    } catch {
      // opciones vacías
    }
  };

  const cargarCasoCompleto = async () => {
    setLoading(true);
    try {
      const { data } = await api.get(`/rma-seguimiento/${caso.id}`);
      setCasoData(data);
    } catch {
      // mantener datos existentes
    } finally {
      setLoading(false);
    }
  };

  const cargarHistorial = async () => {
    try {
      const { data } = await api.get(`/rma-seguimiento/${caso.id}/historial`);
      setHistorial(data);
    } catch {
      // historial vacío
    }
  };

  const abrirMensajesClaim = async (claimId, orderId) => {
    setClaimMsgsClaimId(claimId);
    setClaimMsgsOpen(true);
    setClaimMsgsLoading(true);
    setClaimMsgs([]);
    setOrderMsgs([]);
    try {
      // Fetch both in parallel: claim messages + order (pack) messages
      const promises = [
        api.get(`/seriales/claims/${claimId}/messages`).catch(() => ({ data: [] })),
      ];
      if (orderId) {
        promises.push(
          api.get(`/seriales/orders/${orderId}/messages`).catch(() => ({ data: [] })),
        );
      }
      const results = await Promise.all(promises);
      setClaimMsgs(results[0].data || []);
      if (results[1]) setOrderMsgs(results[1].data || []);
    } catch {
      setClaimMsgs([]);
      setOrderMsgs([]);
    } finally {
      setClaimMsgsLoading(false);
    }
  };

  const buscarTraza = async () => {
    if (!searchSerial.trim()) return;
    setBuscandoTraza(true);
    setTrazaResult(null);
    try {
      // Siempre buscar primero como serial
      const res = await api.get(`/seriales/traza/${searchSerial}`);
      setTrazaResult(res.data);
    } catch {
      // No es serial — intentar como ML (order_id, pack_id, shipping_id)
      try {
        const res = await api.get(`/seriales/traza/ml/${searchSerial}`);
        setTrazaResult(res.data);
      } catch {
        setTrazaResult({ error: 'No se encontraron resultados' });
      }
    } finally {
      setBuscandoTraza(false);
    }
  };

  const agregarItemDesdeTraza = (serial, articulo, pedido, movimientos = []) => {
    // Buscar movimiento tipo CLIENTE para obtener factura y precio
    const movCliente = movimientos?.find((m) => m.tipo === 'CLIENTE');

    const nuevoItem = {
      serial_number: serial || null,
      item_id: articulo?.item_id || null,
      ean: null,
      producto_desc: articulo?.descripcion || 'Sin descripción',
      precio: null,
      link_ml: pedido?.ml_id ? `https://www.mercadolibre.com.ar/ventas/${pedido.ml_id}/detalle` : null,
      // Datos extra de la operación para referencia
      is_id: movCliente?.is_id || null,
      it_transaction: movCliente?.ct_transaction || null,
    };

    // Determinar origen basado en si hay ML ID
    const origenDetectado = pedido?.ml_id ? 'mercadolibre' : null;

    // Extraer teléfono como número (el campo cliente_numero es int en el backend)
    const telRaw = pedido?.cliente_telefono?.replace(/\D/g, '');
    const telNumero = telRaw ? Number(telRaw) : null;

    setCasoData((prev) => ({
      ...prev,
      items: [...(prev.items || []), nuevoItem],
      ml_id: prev.ml_id || pedido?.ml_id || null,
      cliente_nombre: prev.cliente_nombre || pedido?.cliente || null,
      cliente_dni: prev.cliente_dni || pedido?.cliente_dni || null,
      cliente_numero: prev.cliente_numero || telNumero,
      cust_id: prev.cust_id || pedido?.cust_id || null,
      origen: prev.origen || origenDetectado,
    }));
  };

  const agregarItemDesdeProducto = (producto) => {
    const nuevoItem = {
      serial_number: null,
      item_id: producto.item_id || null,
      ean: producto.codigo || null,
      producto_desc: producto.descripcion || 'Sin descripción',
      precio: producto.precio_lista_ml || producto.costo || null,
      link_ml: null,
    };

    setCasoData((prev) => ({
      ...prev,
      items: [...(prev.items || []), nuevoItem],
    }));
    setSearchProducto('');
    setProductoResults([]);
  };

  const agregarItemManual = () => {
    if (!manualItem.producto_desc.trim()) return;
    const nuevoItem = {
      serial_number: manualItem.serial_number || null,
      item_id: null,
      ean: manualItem.ean || null,
      producto_desc: manualItem.producto_desc.trim(),
      precio: manualItem.precio ? Number(manualItem.precio) : null,
      link_ml: null,
    };
    setCasoData((prev) => ({
      ...prev,
      items: [...(prev.items || []), nuevoItem],
    }));
    setManualItem({ producto_desc: '', precio: '', ean: '', serial_number: '' });
    setShowManualForm(false);
  };

  const handleGuardar = async () => {
    setGuardando(true);
    try {
      if (esNuevo) {
        await api.post('/rma-seguimiento', {
          cust_id: casoData.cust_id,
          cliente_nombre: casoData.cliente_nombre,
          cliente_dni: casoData.cliente_dni,
          cliente_numero: casoData.cliente_numero,
          ml_id: casoData.ml_id,
          origen: casoData.origen,
          items: (casoData.items || []).map((i) => ({
            serial_number: i.serial_number,
            item_id: i.item_id,
            is_id: i.is_id,
            it_transaction: i.it_transaction,
            ean: i.ean,
            producto_desc: i.producto_desc,
            precio: i.precio,
            estado_facturacion: i.estado_facturacion,
            link_ml: i.link_ml,
          })),
        });
      } else {
        await api.put(`/rma-seguimiento/${caso.id}`, {
          estado: casoData.estado,
          marcado_borrar_pedido: casoData.marcado_borrar_pedido,
          estado_reclamo_ml_id: casoData.estado_reclamo_ml_id,
          cobertura_ml_id: casoData.cobertura_ml_id,
          monto_cubierto: casoData.monto_cubierto,
          observaciones: casoData.observaciones,
          corroborar_nc: casoData.corroborar_nc,
        });
      }
      onClose(true);
    } catch {
      // error feedback
    } finally {
      setGuardando(false);
    }
  };

  const handleItemUpdate = async (itemId, field, value) => {
    if (!caso?.id) return;
    try {
      const { data } = await api.put(`/rma-seguimiento/${caso.id}/items/${itemId}`, { [field]: value });
      setCasoData((prev) => ({
        ...prev,
        items: prev.items.map((i) => (i.id === itemId ? data : i)),
      }));
    } catch {
      // error
    }
  };

  const renderDropdown = (categoria, value, onChange, disabled = false) => {
    const opts = opciones[categoria] || [];
    return (
      <select value={value || ''} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)} disabled={disabled} className={styles.select}>
        <option value="">— Seleccionar —</option>
        {opts.map((op) => (
          <option key={op.id} value={op.id}>{op.valor}</option>
        ))}
      </select>
    );
  };

  const renderItemMeta = (item, tipoUsuario, tipoFecha) => {
    const userId = item[tipoUsuario];
    const fecha = item[tipoFecha];
    if (!fecha) return null;
    return (
      <div className={styles.meta}>
        <User size={12} /> Usuario #{userId} <Clock size={12} /> {new Date(fecha).toLocaleString('es-AR')}
      </div>
    );
  };

  const tabs = [
    { id: 'info', label: 'Información' },
    ...(esNuevo ? [] : [
      { id: 'recepcion', label: 'Recepción' },
      { id: 'revision', label: 'Revisión' },
      { id: 'reclamo', label: 'Reclamo ML' },
      { id: 'proveedor', label: 'Proveedor' },
      { id: 'proceso', label: 'Proceso' },
      { id: 'historial', label: 'Historial', badge: historial.length || undefined },
    ]),
  ];

  return (
    <>
    <ModalTesla
      isOpen={true}
      onClose={() => onClose(false)}
      closeOnOverlay={false}
      title={esNuevo ? 'Nuevo Caso RMA' : `Caso ${casoData.numero_caso || ''}`}
      subtitle={casoData.cliente_nombre || 'Sin cliente'}
      size="xl"
      tabs={tabs}
      activeTab={activeTab}
      onTabChange={setActiveTab}
      footer={
        puedeGestionar && (
          <ModalFooterButtons
            onCancel={() => onClose(false)}
            onConfirm={handleGuardar}
            confirmText={esNuevo ? 'Crear Caso' : 'Guardar'}
            confirmLoading={guardando}
          />
        )
      }
    >
      {loading ? <ModalLoading message="Cargando caso..." /> : (
        <>
          {/* ═══════════ TAB: Información ═══════════ */}
          {activeTab === 'info' && (
            <div>
              {/* Búsqueda de traza (solo nuevo) */}
              {esNuevo && (
                <ModalSection title="Buscar artículo por serie o ML ID">
                  <div className={styles.searchRow}>
                    <div className={styles.searchInputWrapper}>
                      <input
                        type="text"
                        placeholder="Ingresar serie o ID de venta ML..."
                        value={searchSerial}
                        onChange={(e) => setSearchSerial(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && buscarTraza()}
                        className={styles.input}
                      />
                      <button className="btn-tesla outline-subtle-primary sm" onClick={buscarTraza} disabled={buscandoTraza}>
                        <Search size={14} /> {buscandoTraza ? 'Buscando...' : 'Buscar'}
                      </button>
                    </div>
                  </div>

                  {trazaResult && !trazaResult.error && (
                    <div className={styles.trazaResults}>
                      <p className={styles.trazaResultsLabel}>Resultados de traza:</p>

                      {/* Datos de la operación (pedidos asociados) */}
                      {(trazaResult.pedidos || []).length > 0 && (
                        <div className={styles.trazaOperacion}>
                          {trazaResult.pedidos.map((pedido) => (
                            <div key={pedido.soh_id} className={styles.trazaOperacionCard}>
                              <div className={styles.trazaOperacionHeader}>
                                <ShoppingCart size={14} />
                                {pedido.ml_id ? (
                                  <a
                                    href={`https://www.mercadolibre.com.ar/ventas/${pedido.ml_id}/detalle`}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className={styles.trazaOperacionLink}
                                  >
                                    Venta ML #{pedido.ml_id} <ExternalLink size={12} />
                                  </a>
                                ) : (
                                  <span className={styles.trazaOperacionTitle}>Pedido #{pedido.soh_id}</span>
                                )}
                                {pedido.estado && (
                                  <span className={styles.trazaOperacionBadge}>{pedido.estado}</span>
                                )}
                              </div>
                              <div className={styles.trazaOperacionDetails}>
                                {pedido.cust_id && (
                                  <div className={styles.trazaOperacionDetail}>
                                    <Hash size={12} />
                                    <span>Cliente #{pedido.cust_id}</span>
                                  </div>
                                )}
                                {pedido.cliente && (
                                  <div className={styles.trazaOperacionDetail}>
                                    <User size={12} />
                                    <span>{pedido.cliente}</span>
                                  </div>
                                )}
                                {pedido.soh_id && pedido.ml_id && (
                                  <div className={styles.trazaOperacionDetail}>
                                    <ShoppingCart size={12} />
                                    <span>Pedido #{pedido.soh_id}</span>
                                  </div>
                                )}
                                {pedido.fecha && (
                                  <div className={styles.trazaOperacionDetail}>
                                    <CalendarDays size={12} />
                                    <span>{new Date(pedido.fecha).toLocaleDateString('es-AR')}</span>
                                  </div>
                                )}
                                {pedido.shipping_id && (
                                  <div className={styles.trazaOperacionDetail}>
                                    <Tag size={12} />
                                    <span>Envío #{pedido.shipping_id}</span>
                                  </div>
                                )}
                                {pedido.cliente_dni && (
                                  <div className={styles.trazaOperacionDetail}>
                                    <FileText size={12} />
                                    <span>{pedido.cliente_dni}</span>
                                  </div>
                                )}
                                {pedido.cliente_telefono && (
                                  <div className={styles.trazaOperacionDetail}>
                                    <Phone size={12} />
                                    <span>{pedido.cliente_telefono}</span>
                                  </div>
                                )}
                                {pedido.cliente_email && (
                                  <div className={styles.trazaOperacionDetail}>
                                    <Mail size={12} />
                                    <span>{pedido.cliente_email}</span>
                                  </div>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Factura/documento de venta (del movimiento tipo CLIENTE) */}
                      {(trazaResult.movimientos || []).some((m) => m.tipo === 'CLIENTE') && (
                        <div className={styles.trazaFactura}>
                          {trazaResult.movimientos
                            .filter((m) => m.tipo === 'CLIENTE')
                            .map((mov) => (
                              <div key={mov.is_id} className={styles.trazaFacturaItem}>
                                <FileText size={12} />
                                <span>{mov.nro_documento || 'Sin documento'}</span>
                                {mov.fecha_documento && (
                                  <span className={styles.trazaFacturaFecha}>
                                    {new Date(mov.fecha_documento).toLocaleDateString('es-AR')}
                                  </span>
                                )}
                                {mov.dias_a_la_fecha != null && (
                                  <span className={styles.trazaFacturaDias}>
                                    hace {mov.dias_a_la_fecha} días
                                  </span>
                                )}
                              </div>
                            ))}
                        </div>
                      )}

                      {/* Claims de MercadoLibre asociados */}
                      {(trazaResult.claims || []).length > 0 && (
                        <div className={styles.trazaClaims}>
                          {trazaResult.claims.map((claim) => (
                            <div
                              key={claim.claim_id}
                              className={`${styles.trazaClaimCard} ${claim.status === 'opened' ? styles.trazaClaimOpen : styles.trazaClaimClosed}`}
                            >
                              <div className={styles.trazaClaimHeader}>
                                <AlertTriangle size={14} />
                                <span className={styles.trazaClaimTitle}>
                                  Reclamo #{claim.claim_id}
                                </span>
                                {claim.affects_reputation && (
                                  <span className={styles.trazaClaimRepBadge} title="Afecta reputación">
                                    <Star size={10} />
                                  </span>
                                )}
                                {claim.has_incentive && claim.status === 'opened' && (
                                  <span className={styles.trazaClaimIncentiveBadge} title="Incentivo 48hs para resolver">
                                    <Clock size={10} /> 48hs
                                  </span>
                                )}
                                <span className={`${styles.trazaClaimBadge} ${claim.status === 'opened' ? styles.trazaClaimBadgeOpen : styles.trazaClaimBadgeClosed}`}>
                                  {claim.status === 'opened' ? 'Abierto' : 'Cerrado'}
                                </span>
                              </div>

                              {/* Motivo */}
                              <div className={styles.trazaClaimMotivo}>
                                {claim.reason_detail || claim.reason_category || 'Sin motivo'}
                              </div>

                              {/* Descripción del detalle (de /detail) */}
                              {claim.detail_description && (
                                <div className={styles.trazaClaimDescription}>
                                  {claim.detail_description}
                                </div>
                              )}

                              {/* Tags y resoluciones esperadas */}
                              <div className={styles.trazaClaimTags}>
                                {(claim.triage_tags || []).map((tag) => (
                                  <span key={tag} className={styles.trazaClaimTag}>{TRIAGE_TAGS_ES[tag] || tag}</span>
                                ))}
                                {(claim.expected_resolutions || []).map((res) => (
                                  <span key={res} className={styles.trazaClaimResolution}>{EXPECTED_RESOLUTIONS_ES[res] || res.replace(/_/g, ' ')}</span>
                                ))}
                                {claim.messages_total != null && claim.messages_total > 0 && (
                                  <button
                                    type="button"
                                    className={styles.trazaClaimMsgBadge}
                                    onClick={() => abrirMensajesClaim(claim.claim_id, claim.resource_id)}
                                    aria-label={`Ver ${claim.messages_total} mensaje${claim.messages_total > 1 ? 's' : ''}`}
                                  >
                                    <MessageSquare size={10} /> {claim.messages_total}
                                  </button>
                                )}
                              </div>

                              {/* Detalles */}
                              <div className={styles.trazaClaimDetails}>
                                {claim.claim_stage && (
                                  <div className={styles.trazaClaimDetail}>
                                    <Shield size={12} />
                                    <span>Etapa: {CLAIM_STAGE_ES[claim.claim_stage] || claim.claim_stage}</span>
                                  </div>
                                )}
                                {claim.action_responsible === 'seller' && claim.status === 'opened' && (
                                  <div className={`${styles.trazaClaimDetail} ${styles.trazaClaimUrgent}`}>
                                    <AlertTriangle size={12} />
                                    <span>Requiere acción del vendedor</span>
                                  </div>
                                )}
                                {claim.nearest_due_date && claim.status === 'opened' && (
                                  <div className={`${styles.trazaClaimDetail} ${styles.trazaClaimUrgent}`}>
                                    <Clock size={12} />
                                    <span>Vence: {new Date(claim.nearest_due_date).toLocaleDateString('es-AR')}</span>
                                  </div>
                                )}
                                {claim.date_created && (
                                  <div className={styles.trazaClaimDetail}>
                                    <CalendarDays size={12} />
                                    <span>Creado: {new Date(claim.date_created).toLocaleDateString('es-AR')}</span>
                                  </div>
                                )}
                              </div>

                              {/* Acciones obligatorias */}
                              {(claim.mandatory_actions || []).length > 0 && claim.status === 'opened' && (
                                <div className={styles.trazaClaimMandatory}>
                                  Acciones obligatorias: {claim.mandatory_actions.map((a) => CLAIM_ACTIONS_ES[a] || a.replace(/_/g, ' ')).join(', ')}
                                </div>
                              )}

                              {/* Devolución (return) */}
                              {claim.claim_return && (
                                <div className={styles.trazaClaimReturnSection}>
                                  <div className={styles.trazaClaimSubHeader}>
                                    <RotateCcw size={12} />
                                    <span>Devolución</span>
                                    <span className={styles.trazaClaimSubBadge}>
                                      {RETURN_STATUS_ES[claim.claim_return.status] || claim.claim_return.status}
                                    </span>
                                  </div>
                                  <div className={styles.trazaClaimSubDetails}>
                                    {claim.claim_return.subtype && (
                                      <span>{RETURN_SUBTYPE_ES[claim.claim_return.subtype] || claim.claim_return.subtype}</span>
                                    )}
                                    {claim.claim_return.status_money && (
                                      <span>
                                        <DollarSign size={10} /> {RETURN_MONEY_STATUS_ES[claim.claim_return.status_money] || claim.claim_return.status_money}
                                      </span>
                                    )}
                                    {claim.claim_return.refund_at && claim.claim_return.refund_at !== 'n/a' && (
                                      <span>Reembolso al: {SHIPMENT_STATUS_ES[claim.claim_return.refund_at] || claim.claim_return.refund_at}</span>
                                    )}
                                  </div>
                                  {/* Shipments de la devolución */}
                                  {(claim.claim_return.shipments || []).length > 0 && (
                                    <div className={styles.trazaClaimShipments}>
                                      {claim.claim_return.shipments.map((s, idx) => (
                                        <div key={s.shipment_id || idx} className={styles.trazaClaimShipment}>
                                          <Truck size={10} />
                                          <span>
                                            {s.shipment_type === 'return' ? 'Devolución' : s.shipment_type === 'return_from_triage' ? 'Desde triage' : s.shipment_type || 'Envío'}
                                            {' — '}
                                            {SHIPMENT_STATUS_ES[s.status] || s.status}
                                          </span>
                                          {s.tracking_number && (
                                            <span className={styles.trazaClaimTracking}>#{s.tracking_number}</span>
                                          )}
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                </div>
                              )}

                              {/* Cambio/reemplazo (change) */}
                              {claim.claim_change && (
                                <div className={styles.trazaClaimChangeSection}>
                                  <div className={styles.trazaClaimSubHeader}>
                                    <ArrowLeftRight size={12} />
                                    <span>{CHANGE_TYPE_ES[claim.claim_change.change_type] || claim.claim_change.change_type || 'Cambio'}</span>
                                    <span className={styles.trazaClaimSubBadge}>
                                      {CHANGE_STATUS_ES[claim.claim_change.status] || claim.claim_change.status}
                                    </span>
                                  </div>
                                  {(claim.claim_change.new_order_ids || []).length > 0 && (
                                    <div className={styles.trazaClaimSubDetails}>
                                      <span>Nueva orden: {claim.claim_change.new_order_ids.join(', ')}</span>
                                    </div>
                                  )}
                                </div>
                              )}

                              {/* Resoluciones esperadas detalladas (negociación) */}
                              {(claim.expected_resolutions_detail || []).length > 0 && (
                                <div className={styles.trazaClaimExpResSection}>
                                  <div className={styles.trazaClaimSubHeader}>
                                    <FileText size={12} />
                                    <span>Negociación</span>
                                  </div>
                                  {claim.expected_resolutions_detail.map((er, idx) => (
                                    <div key={idx} className={styles.trazaClaimExpRes}>
                                      <span className={styles.trazaClaimExpResRole}>
                                        {PLAYER_ROLE_ES[er.player_role] || er.player_role}:
                                      </span>
                                      <span>
                                        {EXPECTED_RESOLUTIONS_ES[er.expected_resolution] || er.expected_resolution?.replace(/_/g, ' ')}
                                      </span>
                                      <span className={`${styles.trazaClaimExpResBadge} ${er.status === 'accepted' ? styles.trazaClaimExpResAccepted : er.status === 'rejected' ? styles.trazaClaimExpResRejected : ''}`}>
                                        {EXPECTED_RES_STATUS_ES[er.status] || er.status}
                                      </span>
                                    </div>
                                  ))}
                                </div>
                              )}

                              {/* Resolución (si cerrado) */}
                              {claim.status === 'closed' && claim.resolution_reason && (
                                <div className={styles.trazaClaimResolved}>
                                  Resolución: {RESOLUTION_REASON_ES[claim.resolution_reason] || claim.resolution_reason.replace(/_/g, ' ')}
                                  {claim.resolution_closed_by && ` (por ${CLOSED_BY_ES[claim.resolution_closed_by] || claim.resolution_closed_by})`}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Artículo encontrado (búsqueda por serial) */}
                      {trazaResult.articulo && (
                        <div className={styles.trazaItem}>
                          <div>
                            <div className={styles.trazaItemDesc}>{trazaResult.articulo.descripcion}</div>
                            <div className={styles.trazaItemMeta}>
                              {trazaResult.serial} — {trazaResult.articulo.codigo}
                            </div>
                          </div>
                          <button className="btn-tesla outline-subtle-success sm" onClick={() => agregarItemDesdeTraza(trazaResult.serial, trazaResult.articulo, trazaResult.pedidos?.[0], trazaResult.movimientos)}>
                            <Plus size={14} /> Agregar
                          </button>
                        </div>
                      )}

                      {/* Seriales encontrados (búsqueda por ML ID) */}
                      {trazaResult.seriales?.map((s, idx) => (
                        <div key={idx} className={styles.trazaItem}>
                          <div>
                            <div className={styles.trazaItemDesc}>{s.articulo?.descripcion || 'Sin descripción'}</div>
                            <div className={styles.trazaItemMeta}>{s.serial}</div>
                          </div>
                          <button className="btn-tesla outline-subtle-success sm" onClick={() => agregarItemDesdeTraza(s.serial, s.articulo, trazaResult.pedidos?.[0], s.movimientos)}>
                            <Plus size={14} /> Agregar
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                  {trazaResult?.error && (
                    <p className={styles.trazaError}>{trazaResult.error}</p>
                  )}
                </ModalSection>
              )}

              {/* Buscar por EAN / código / descripción (solo nuevo) */}
              {esNuevo && (
                <ModalSection title="Buscar producto por EAN / código / descripción">
                  <div className={styles.productoSearchContainer}>
                    <div className={styles.productoSearchRow}>
                      <div className={styles.productoInputWrapper}>
                        <input
                          ref={productoInputRef}
                          type="text"
                          placeholder="Escribí un EAN, código o parte de la descripción..."
                          value={searchProducto}
                          onChange={(e) => setSearchProducto(e.target.value)}
                          className={`${styles.input} ${styles.productoInputWithIcon}`}
                        />
                        <Search size={14} className={styles.productoSearchIcon} />
                      </div>
                      <button
                        className="btn-tesla ghost sm"
                        onClick={() => setShowManualForm(!showManualForm)}
                        title="Agregar artículo manual"
                        aria-label="Agregar artículo manual"
                      >
                        <PenLine size={14} /> Manual
                      </button>
                    </div>

                    {buscandoProducto && (
                      <p className={styles.searchHint}>Buscando...</p>
                    )}

                    {productoResults.length > 0 && (
                      <div className={styles.productoResults}>
                        {productoResults.map((p) => (
                          <div
                            key={p.item_id}
                            className={styles.productoResultItem}
                            onClick={() => agregarItemDesdeProducto(p)}
                          >
                            <div className={styles.productoResultInfo}>
                              <div className={styles.productoResultDesc}>
                                {p.descripcion}
                              </div>
                              <div className={styles.productoResultMeta}>
                                <span>{p.codigo}</span>
                                {p.marca && <span>{p.marca}</span>}
                                {p.stock > 0 && <span className={styles.productoResultStock}>Stock: {p.stock}</span>}
                                {p.stock === 0 && <span className={styles.productoResultNoStock}>Sin stock</span>}
                              </div>
                            </div>
                            {p.precio_lista_ml && (
                              <span className={styles.productoResultPrice}>
                                ${Number(p.precio_lista_ml).toLocaleString('es-AR')}
                              </span>
                            )}
                            <Plus size={16} className={styles.productoResultAdd} />
                          </div>
                        ))}
                      </div>
                    )}

                    {!buscandoProducto && searchProducto.length >= 2 && productoResults.length === 0 && debouncedSearchProducto === searchProducto && (
                      <p className={styles.noResults}>
                        No se encontraron productos. Podés agregarlo manualmente.
                      </p>
                    )}
                  </div>

                  {/* Formulario de item manual */}
                  {showManualForm && (
                    <div className={styles.manualForm}>
                      <p className={styles.manualFormLabel}>
                        Agregar artículo que no está en el sistema:
                      </p>
                      <div className={styles.manualFormGrid}>
                        <input
                          className={styles.input}
                          placeholder="Descripción del producto *"
                          value={manualItem.producto_desc}
                          onChange={(e) => setManualItem({ ...manualItem, producto_desc: e.target.value })}
                          onKeyDown={(e) => e.key === 'Enter' && agregarItemManual()}
                        />
                        <input
                          className={styles.input}
                          type="number"
                          step="0.01"
                          placeholder="Precio"
                          value={manualItem.precio}
                          onChange={(e) => setManualItem({ ...manualItem, precio: e.target.value })}
                          onKeyDown={(e) => e.key === 'Enter' && agregarItemManual()}
                        />
                        <input
                          className={styles.input}
                          placeholder="EAN / Código"
                          value={manualItem.ean}
                          onChange={(e) => setManualItem({ ...manualItem, ean: e.target.value })}
                          onKeyDown={(e) => e.key === 'Enter' && agregarItemManual()}
                        />
                        <input
                          className={styles.input}
                          placeholder="Nro. Serie (opcional)"
                          value={manualItem.serial_number}
                          onChange={(e) => setManualItem({ ...manualItem, serial_number: e.target.value })}
                          onKeyDown={(e) => e.key === 'Enter' && agregarItemManual()}
                        />
                      </div>
                      <div className={styles.manualFormActions}>
                        <button className="btn-tesla ghost sm" onClick={() => setShowManualForm(false)}>
                          Cancelar
                        </button>
                        <button
                          className="btn-tesla outline-subtle-success sm"
                          onClick={agregarItemManual}
                          disabled={!manualItem.producto_desc.trim()}
                        >
                          <Plus size={14} /> Agregar
                        </button>
                      </div>
                    </div>
                  )}
                </ModalSection>
              )}

              {/* Datos del caso */}
              <ModalSection title="Datos del caso">
                <div className={styles.grid3}>
                  <label>
                    <span className={styles.label}>Cliente</span>
                    <input className={styles.input} value={casoData.cliente_nombre || ''} onChange={(e) => setCasoData({ ...casoData, cliente_nombre: e.target.value })} disabled={!puedeGestionar} />
                  </label>
                  <label>
                    <span className={styles.label}>DNI / CUIT</span>
                    <input className={styles.input} value={casoData.cliente_dni || ''} onChange={(e) => setCasoData({ ...casoData, cliente_dni: e.target.value })} disabled={!puedeGestionar} />
                  </label>
                  <label>
                    <span className={styles.label}>N° Cliente (ERP)</span>
                    <input className={styles.input} type="number" value={casoData.cust_id || ''} onChange={(e) => setCasoData({ ...casoData, cust_id: e.target.value ? Number(e.target.value) : null })} disabled={!puedeGestionar} placeholder="ID del cliente en ERP" />
                  </label>
                  <label>
                    <span className={styles.label}>Teléfono de contacto</span>
                    <input className={styles.input} type="tel" value={casoData.cliente_numero || ''} onChange={(e) => setCasoData({ ...casoData, cliente_numero: e.target.value ? Number(e.target.value.replace(/\D/g, '')) : null })} disabled={!puedeGestionar} placeholder="Ej: 1155443322" />
                  </label>
                  <label>
                    <span className={styles.label}>ML ID</span>
                    <input className={styles.input} value={casoData.ml_id || ''} onChange={(e) => setCasoData({ ...casoData, ml_id: e.target.value })} disabled={!puedeGestionar} />
                  </label>
                  <label>
                    <span className={styles.label}>Origen</span>
                    <select className={styles.select} value={casoData.origen || ''} onChange={(e) => setCasoData({ ...casoData, origen: e.target.value })} disabled={!puedeGestionar}>
                      <option value="">— Seleccionar —</option>
                      <option value="mercadolibre">MercadoLibre</option>
                      <option value="tienda_nube">Tienda Nube</option>
                      <option value="mostrador">Mostrador</option>
                    </select>
                  </label>
                </div>
              </ModalSection>

              {/* Items */}
              <ModalSection title={`Artículos (${(casoData.items || []).length})`}>
                {(casoData.items || []).length === 0 ? (
                  <p className={styles.emptyItems}>No hay artículos. Usá la búsqueda de traza para agregar.</p>
                ) : (
                  <div className={styles.itemsList}>
                    {(casoData.items || []).map((item, idx) => (
                      <div key={item.id || idx} className={styles.itemCard}>
                        <div className={styles.itemInfo}>
                          <div className={styles.itemDesc}>{item.producto_desc || '—'}</div>
                          <div className={styles.itemMeta}>
                            {item.serial_number && <span>S/N: {item.serial_number}</span>}
                            {item.precio && <span>${Number(item.precio).toLocaleString('es-AR')}</span>}
                            {item.estado_facturacion && <span>{item.estado_facturacion}</span>}
                          </div>
                        </div>
                        {item.link_ml && (
                          <a href={item.link_ml} target="_blank" rel="noopener noreferrer" className="btn-tesla ghost sm" title="Ver en ML">
                            <ExternalLink size={14} />
                          </a>
                        )}
                        {esNuevo && (
                          <button className="btn-tesla ghost sm" onClick={() => setCasoData((prev) => ({ ...prev, items: prev.items.filter((_, i) => i !== idx) }))} title="Quitar" aria-label="Quitar artículo">
                            <Trash2 size={14} />
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </ModalSection>

              {/* Campos caso-level (solo edición) */}
              {!esNuevo && (
                <>
                  <ModalSection title="Estado del caso">
                    <div className={styles.grid2}>
                      <label>
                        <span className={styles.label}>Estado del caso</span>
                        <select className={styles.select} value={casoData.estado || 'abierto'} onChange={(e) => setCasoData({ ...casoData, estado: e.target.value })} disabled={!puedeGestionar}>
                          <option value="abierto">Abierto</option>
                          <option value="en_espera">En espera</option>
                          <option value="cerrado">Cerrado</option>
                        </select>
                      </label>
                      <label className={styles.checkLabel}>
                        <input type="checkbox" checked={casoData.marcado_borrar_pedido || false} onChange={(e) => setCasoData({ ...casoData, marcado_borrar_pedido: e.target.checked })} disabled={!puedeGestionar} />
                        Marcado para borrar pedido
                      </label>
                    </div>
                  </ModalSection>

                  <ModalSection title="Observaciones">
                    <textarea
                      className={styles.textarea}
                      rows={3}
                      value={casoData.observaciones || ''}
                      onChange={(e) => setCasoData({ ...casoData, observaciones: e.target.value })}
                      placeholder="Observaciones generales del caso..."
                      disabled={!puedeGestionar}
                    />
                  </ModalSection>

                  <ModalSection title="Auditoría">
                    <div className={styles.grid2}>
                      <label>
                        <span className={styles.label}>Corroborar NC</span>
                        <input className={styles.input} value={casoData.corroborar_nc || ''} onChange={(e) => setCasoData({ ...casoData, corroborar_nc: e.target.value })} disabled={!puedeGestionar} />
                      </label>
                      <div>
                        <span className={styles.label}>Fecha</span>
                        <span className={styles.itemDesc}>{casoData.fecha_caso || '—'}</span>
                      </div>
                    </div>
                  </ModalSection>
                </>
              )}
            </div>
          )}

          {/* ═══════════ TAB: Recepción ═══════════ */}
          {activeTab === 'recepcion' && (
            <div>
              {(casoData.items || []).map((item) => (
                <ModalSection key={item.id} title={item.producto_desc || `Item #${item.id}`}>
                  <div className={styles.grid3}>
                    <label>
                      <span className={styles.label}>Estado de recepción</span>
                      {renderDropdown('estado_recepcion', item.estado_recepcion_id, (v) => handleItemUpdate(item.id, 'estado_recepcion_id', v), !puedeGestionar)}
                    </label>
                    <label>
                      <span className={styles.label}>Costo de envío</span>
                      <input className={styles.input} type="number" step="0.01" value={item.costo_envio || ''} onChange={(e) => handleItemUpdate(item.id, 'costo_envio', e.target.value ? Number(e.target.value) : null)} disabled={!puedeGestionar} />
                    </label>
                    <label>
                      <span className={styles.label}>Causa de devolución</span>
                      {renderDropdown('causa_devolucion', item.causa_devolucion_id, (v) => handleItemUpdate(item.id, 'causa_devolucion_id', v), !puedeGestionar)}
                    </label>
                  </div>
                  {renderItemMeta(item, 'recepcion_usuario_id', 'recepcion_fecha')}
                </ModalSection>
              ))}
            </div>
          )}

          {/* ═══════════ TAB: Revisión ═══════════ */}
          {activeTab === 'revision' && (
            <div>
              {(casoData.items || []).map((item) => (
                <ModalSection key={item.id} title={item.producto_desc || `Item #${item.id}`}>
                  <div className={styles.grid3}>
                    <label>
                      <span className={styles.label}>Apto para la venta</span>
                      {renderDropdown('apto_venta', item.apto_venta_id, (v) => handleItemUpdate(item.id, 'apto_venta_id', v), !puedeGestionar)}
                    </label>
                    <label className={styles.checkLabel}>
                      <input type="checkbox" checked={item.requirio_reacondicionamiento || false} onChange={(e) => handleItemUpdate(item.id, 'requirio_reacondicionamiento', e.target.checked)} disabled={!puedeGestionar} />
                      Requirió reacondicionamiento
                    </label>
                    <label>
                      <span className={styles.label}>Estado (ERP)</span>
                      {renderDropdown('estado_revision', item.estado_revision_id, (v) => handleItemUpdate(item.id, 'estado_revision_id', v), !puedeGestionar)}
                    </label>
                  </div>
                  {renderItemMeta(item, 'revision_usuario_id', 'revision_fecha')}
                </ModalSection>
              ))}
            </div>
          )}

          {/* ═══════════ TAB: Reclamo ML ═══════════ */}
          {activeTab === 'reclamo' && (
            <ModalSection title="Reclamo MercadoLibre">
              <div className={styles.grid3}>
                <label>
                  <span className={styles.label}>Estado del reclamo</span>
                  {renderDropdown('estado_reclamo_ml', casoData.estado_reclamo_ml_id, (v) => setCasoData({ ...casoData, estado_reclamo_ml_id: v }), !puedeGestionar)}
                </label>
                <label>
                  <span className={styles.label}>ML cubrió el producto</span>
                  {renderDropdown('cobertura_ml', casoData.cobertura_ml_id, (v) => setCasoData({ ...casoData, cobertura_ml_id: v }), !puedeGestionar)}
                </label>
                <label>
                  <span className={styles.label}>Monto cubierto</span>
                  <input className={styles.input} type="number" step="0.01" value={casoData.monto_cubierto || ''} onChange={(e) => setCasoData({ ...casoData, monto_cubierto: e.target.value ? Number(e.target.value) : null })} disabled={!puedeGestionar} />
                </label>
              </div>
            </ModalSection>
          )}

          {/* ═══════════ TAB: Proveedor ═══════════ */}
          {activeTab === 'proveedor' && (
            <div>
              {(casoData.items || []).map((item) => (
                <ModalSection key={item.id} title={item.producto_desc || `Item #${item.id}`}>
                  <div className={styles.grid2}>
                    <label>
                      <span className={styles.label}>Proveedor</span>
                      <input className={styles.input} value={item.proveedor_nombre || ''} onChange={(e) => handleItemUpdate(item.id, 'proveedor_nombre', e.target.value)} disabled={!puedeGestionar} />
                    </label>
                    <label>
                      <span className={styles.label}>Estado proveedor</span>
                      {renderDropdown('estado_proveedor', item.estado_proveedor_id, (v) => handleItemUpdate(item.id, 'estado_proveedor_id', v), !puedeGestionar)}
                    </label>
                    <label className={styles.checkLabel}>
                      <input type="checkbox" checked={item.enviado_proveedor || false} onChange={(e) => handleItemUpdate(item.id, 'enviado_proveedor', e.target.checked)} disabled={!puedeGestionar} />
                      Enviado a proveedor
                    </label>
                    <label>
                      <span className={styles.label}>NC Proveedor</span>
                      <input className={styles.input} value={item.nc_proveedor || ''} onChange={(e) => handleItemUpdate(item.id, 'nc_proveedor', e.target.value)} disabled={!puedeGestionar} />
                    </label>
                    <label>
                      <span className={styles.label}>Monto NC Proveedor</span>
                      <input className={styles.input} type="number" step="0.01" value={item.monto_nc_proveedor || ''} onChange={(e) => handleItemUpdate(item.id, 'monto_nc_proveedor', e.target.value ? Number(e.target.value) : null)} disabled={!puedeGestionar} />
                    </label>
                    <label>
                      <span className={styles.label}>Fecha envío</span>
                      <input className={styles.input} type="date" value={item.fecha_envio_proveedor ? item.fecha_envio_proveedor.split('T')[0] : ''} onChange={(e) => handleItemUpdate(item.id, 'fecha_envio_proveedor', e.target.value || null)} disabled={!puedeGestionar} />
                    </label>
                    <label>
                      <span className={styles.label}>Fecha respuesta</span>
                      <input className={styles.input} type="date" value={item.fecha_respuesta_proveedor ? item.fecha_respuesta_proveedor.split('T')[0] : ''} onChange={(e) => handleItemUpdate(item.id, 'fecha_respuesta_proveedor', e.target.value || null)} disabled={!puedeGestionar} />
                    </label>
                  </div>
                </ModalSection>
              ))}
            </div>
          )}

          {/* ═══════════ TAB: Proceso ═══════════ */}
          {activeTab === 'proceso' && (
            <div>
              {(casoData.items || []).map((item) => (
                <ModalSection key={item.id} title={item.producto_desc || `Item #${item.id}`}>
                  <div className={styles.grid3}>
                    <label>
                      <span className={styles.label}>Estado proceso</span>
                      {renderDropdown('estado_proceso', item.estado_proceso_id, (v) => handleItemUpdate(item.id, 'estado_proceso_id', v), !puedeGestionar)}
                    </label>
                    <label>
                      <span className={styles.label}>Depósito destino</span>
                      {renderDropdown('deposito_destino', item.deposito_destino_id, (v) => handleItemUpdate(item.id, 'deposito_destino_id', v), !puedeGestionar)}
                    </label>
                    <label className={styles.checkLabel}>
                      <input type="checkbox" checked={item.enviado_fisicamente_deposito || false} onChange={(e) => handleItemUpdate(item.id, 'enviado_fisicamente_deposito', e.target.checked)} disabled={!puedeGestionar} />
                      Enviado físicamente
                    </label>
                  </div>
                  <div className={styles.grid3}>
                    <label className={styles.checkLabel}>
                      <input type="checkbox" checked={item.corroborar_nc || false} onChange={(e) => handleItemUpdate(item.id, 'corroborar_nc', e.target.checked)} disabled={!puedeGestionar} />
                      Corroborar NC
                    </label>
                    <label className={styles.checkLabel}>
                      <input type="checkbox" checked={item.requirio_rma_interno || false} onChange={(e) => handleItemUpdate(item.id, 'requirio_rma_interno', e.target.checked)} disabled={!puedeGestionar} />
                      Requirió RMA Interno
                    </label>
                    <label className={styles.checkLabel}>
                      <input type="checkbox" checked={item.requiere_nota_credito || false} onChange={(e) => handleItemUpdate(item.id, 'requiere_nota_credito', e.target.checked)} disabled={!puedeGestionar} />
                      Requiere nota de crédito
                    </label>
                  </div>
                  <div className={styles.grid2}>
                    <label className={styles.checkLabel}>
                      <input type="checkbox" checked={item.debe_facturarse || false} onChange={(e) => handleItemUpdate(item.id, 'debe_facturarse', e.target.checked)} disabled={!puedeGestionar} />
                      Otros items deben facturarse
                    </label>
                    <label>
                      <span className={styles.label}>Observaciones</span>
                      <textarea
                        className={styles.textarea}
                        rows={2}
                        value={item.observaciones || ''}
                        onChange={(e) => handleItemUpdate(item.id, 'observaciones', e.target.value)}
                        placeholder="Observaciones del artículo..."
                        disabled={!puedeGestionar}
                      />
                    </label>
                  </div>
                </ModalSection>
              ))}
            </div>
          )}

          {/* ═══════════ TAB: Historial ═══════════ */}
          {activeTab === 'historial' && (
            <div>
              {historial.length === 0 ? (
                <p className={styles.historialEmpty}>Sin cambios registrados</p>
              ) : (
                <div className={styles.historialList}>
                  {historial.map((h) => (
                    <div key={h.id} className={styles.historialRow}>
                      <Clock size={12} className={styles.historialIcon} />
                      <span className={styles.historialFecha}>
                        {h.created_at ? new Date(h.created_at).toLocaleString('es-AR') : '—'}
                      </span>
                      <strong className={styles.historialUsuario}>{h.usuario_nombre || `#${h.usuario_id}`}</strong>
                      <span className={styles.historialCampo}>{h.campo}:</span>
                      {h.valor_anterior && <span className={styles.historialViejo}>{h.valor_anterior}</span>}
                      <span className={styles.historialNuevo}>{h.valor_nuevo}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </ModalTesla>

      {/* ── Sub-modal: Mensajes del reclamo ML ── */}
      <ModalTesla
        isOpen={claimMsgsOpen}
        onClose={() => setClaimMsgsOpen(false)}
        title={`Mensajes — Reclamo #${claimMsgsClaimId || ''}`}
        size="md"
        closeOnOverlay
      >
        {claimMsgsLoading ? (
          <ModalLoading message="Cargando mensajes..." />
        ) : (orderMsgs.length === 0 && claimMsgs.length === 0) ? (
          <p className={styles.claimMsgsEmpty}>Sin mensajes</p>
        ) : (
          <div className={styles.claimMsgsList}>
            {/* Mensajes de la venta (conversación posventa) */}
            {orderMsgs.length > 0 && (
              <>
                <div className={styles.claimMsgsSectionHeader}>
                  <MessageSquare size={12} />
                  Conversación de la venta ({orderMsgs.length})
                </div>
                {[...orderMsgs].reverse().map((msg) => (
                  <div
                    key={msg.message_id}
                    className={`${styles.claimMsgBubble} ${msg.is_seller ? styles.claimMsgSeller : ''}`}
                  >
                    <div className={styles.claimMsgHeader}>
                      <span className={styles.claimMsgRole}>
                        {msg.is_seller ? 'Vendedor' : 'Comprador'}
                      </span>
                      {msg.date_created && (
                        <span className={styles.claimMsgDate}>
                          {new Date(msg.date_created).toLocaleString('es-AR', {
                            day: '2-digit', month: '2-digit', year: 'numeric',
                            hour: '2-digit', minute: '2-digit',
                          })}
                        </span>
                      )}
                    </div>
                    {msg.text && (
                      <div
                        className={styles.claimMsgText}
                        dangerouslySetInnerHTML={{ __html: sanitizeMessageHtml(msg.text) }}
                      />
                    )}
                    {msg.attachments && msg.attachments.length > 0 && (
                      <div className={styles.claimMsgAttachments}>
                        {msg.attachments.map((att, i) => {
                          const key = typeof att === 'string' ? att : att?.id || att?.filename || '';
                          if (isImageAttachment(key)) {
                            return (
                              <button
                                key={i}
                                type="button"
                                className={styles.claimMsgImgThumb}
                                onClick={() => setLightboxUrl(attachmentProxyUrl(key))}
                                aria-label="Ver imagen adjunta"
                              >
                                <img
                                  src={attachmentProxyUrl(key)}
                                  alt="Adjunto"
                                  loading="lazy"
                                />
                              </button>
                            );
                          }
                          return (
                            <a
                              key={i}
                              href={attachmentProxyUrl(key)}
                              target="_blank"
                              rel="noopener noreferrer"
                              className={styles.claimMsgAttachment}
                            >
                              <Package size={10} /> {key.split('_').pop() || 'Adjunto'}
                            </a>
                          );
                        })}
                      </div>
                    )}
                  </div>
                ))}
              </>
            )}

            {/* Mensajes del reclamo */}
            {claimMsgs.length > 0 && (
              <>
                <div className={styles.claimMsgsSectionHeader}>
                  <AlertTriangle size={12} />
                  Mensajes del reclamo ({claimMsgs.length})
                </div>
                {claimMsgs.map((msg) => {
                  const isSeller = msg.sender_role === 'respondent';
                  const isMediator = msg.sender_role === 'mediator';
                  return (
                    <div
                      key={msg.id}
                      className={`${styles.claimMsgBubble} ${isSeller ? styles.claimMsgSeller : ''} ${isMediator ? styles.claimMsgMediator : ''}`}
                    >
                      <div className={styles.claimMsgHeader}>
                        <span className={styles.claimMsgRole}>
                          {PLAYER_ROLE_ES[msg.sender_role] || msg.sender_role}
                        </span>
                        {msg.ml_date_created && (
                          <span className={styles.claimMsgDate}>
                            {new Date(msg.ml_date_created).toLocaleString('es-AR', {
                              day: '2-digit', month: '2-digit', year: 'numeric',
                              hour: '2-digit', minute: '2-digit',
                            })}
                          </span>
                        )}
                      </div>
                      <div
                        className={styles.claimMsgText}
                        dangerouslySetInnerHTML={{ __html: sanitizeMessageHtml(msg.message) || '(sin texto)' }}
                      />
                      {msg.attachments && msg.attachments.length > 0 && (
                        <div className={styles.claimMsgAttachments}>
                          {msg.attachments.map((att, i) => (
                            <span key={i} className={styles.claimMsgAttachment}>
                              <Package size={10} /> {att.original_filename || att.filename}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </>
            )}
          </div>
        )}
      </ModalTesla>

      {/* ── Lightbox: imagen adjunta ampliada ── */}
      {lightboxUrl && (
        <div
          className={styles.lightboxOverlay}
          onClick={() => setLightboxUrl(null)}
          role="dialog"
          aria-label="Imagen adjunta ampliada"
        >
          <button
            type="button"
            className={styles.lightboxClose}
            onClick={() => setLightboxUrl(null)}
            aria-label="Cerrar imagen"
          >
            &times;
          </button>
          <img
            src={lightboxUrl}
            alt="Adjunto ampliado"
            className={styles.lightboxImg}
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}
    </>
  );
}
