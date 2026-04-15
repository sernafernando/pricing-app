/**
 * Registry de transformadores de datos por contexto.
 * Cada mapper recibe la entidad cruda de la página y retorna
 * un objeto plano { key: stringValue } compatible con pdfme inputs.
 *
 * Las keys deben coincidir con los nombres de variables del backend
 * (GET /api/document-templates/variables/{contexto}).
 */

const formatDate = (val) => {
  if (!val) return '';
  try {
    return new Date(val).toLocaleDateString('es-AR');
  } catch {
    return String(val);
  }
};

const formatNumber = (val) => {
  if (val === null || val === undefined) return '';
  return Number(val).toLocaleString('es-AR', { minimumFractionDigits: 2 });
};

const safe = (val) => (val === null || val === undefined ? '' : String(val));

// =============================================================================
// MAPPERS POR CONTEXTO
// =============================================================================

const pedidosMapper = (entity) => ({
  pedido_id: safe(entity.soh_id ?? entity.id),
  fecha_pedido: formatDate(entity.soh_cd ?? entity.fecha),
  fecha_entrega: formatDate(entity.soh_deliverydate ?? entity.fecha_entrega),
  observacion: safe(entity.soh_observation1 ?? entity.observacion),
  total: formatNumber(entity.soh_total ?? entity.total),
  cliente_nombre: safe(entity.cliente_nombre ?? entity.cust_name),
  cliente_cuit: safe(entity.cliente_cuit ?? entity.cust_taxnumber),
  cliente_direccion: safe(entity.cliente_direccion ?? entity.cust_address),
  cliente_ciudad: safe(entity.cliente_ciudad ?? entity.cust_city),
  cliente_cp: safe(entity.cliente_cp ?? entity.cust_zip),
  cliente_telefono: safe(entity.cliente_telefono ?? entity.cust_phone1),
  cliente_email: safe(entity.cliente_email ?? entity.cust_email),
  ml_id: safe(entity.soh_mlid ?? entity.ml_id),
  ml_guia: safe(entity.soh_mlguia ?? entity.ml_guia),
  direccion_envio: safe(entity.soh_deliveryaddress ?? entity.override_shipping_address ?? entity.direccion_envio),
  destinatario: safe(entity.override_shipping_recipient ?? entity.destinatario),
  bultos: safe(entity.override_num_bultos ?? entity.bultos),
});

const rrhhMapper = (entity) => ({
  legajo: safe(entity.legajo),
  nombre: safe(entity.nombre),
  apellido: safe(entity.apellido),
  nombre_completo: safe(entity.apellido && entity.nombre ? `${entity.apellido}, ${entity.nombre}` : entity.nombre_completo),
  dni: safe(entity.dni),
  cuil: safe(entity.cuil),
  fecha_nacimiento: formatDate(entity.fecha_nacimiento),
  domicilio: safe(entity.domicilio ?? [entity.calle, entity.numero, entity.localidad, entity.provincia].filter(Boolean).join(', ')),
  telefono: safe(entity.telefono),
  email_personal: safe(entity.email_personal),
  contacto_emergencia: safe(entity.contacto_emergencia),
  contacto_emergencia_tel: safe(entity.contacto_emergencia_tel),
  fecha_ingreso: formatDate(entity.fecha_ingreso),
  fecha_egreso: formatDate(entity.fecha_egreso),
  puesto: safe(entity.puesto),
  area: safe(entity.area),
  estado: safe(entity.estado),
  observaciones: safe(entity.observaciones),
});

/**
 * Mapper de remito flex (envíos pistoleados).
 * entity debe tener la forma:
 * {
 *   fecha_envio: "2026-03-15",
 *   logistica: "Andreani",  (o logistica_nombre)
 *   transporte: "OCA",      (o transporte_nombre)
 *   transporte_direccion: "...",
 *   transporte_telefono: "...",
 *   envios: [ { cordon, total_bultos, ... } ]
 * }
 * El remito es una hoja simple: totales + cordones + firma.
 * Sin tabla de detalle (200 envíos no los mira nadie).
 */
const enviosMapper = (entity) => {
  const envios = entity.envios || [];
  const totalBultos = envios.reduce((sum, e) => sum + (Number(e.total_bultos) || 1), 0);

  // Resumen por cordón
  const cordones = {};
  for (const e of envios) {
    const cordon = e.cordon || 'Sin asignar';
    cordones[cordon] = (cordones[cordon] || 0) + 1;
  }
  const resumenCordones = Object.entries(cordones)
    .map(([k, v]) => `${k}: ${v}`)
    .join(' | ');

  return {
    fecha_envio: formatDate(entity.fecha_envio),
    logistica: safe(entity.logistica_nombre ?? entity.logistica),
    transporte: safe(entity.transporte_nombre ?? entity.transporte),
    transporte_direccion: safe(entity.transporte_direccion),
    transporte_telefono: safe(entity.transporte_telefono),
    total_envios: String(envios.length),
    total_bultos: String(totalBultos),
    resumen_cordones: resumenCordones || 'Sin datos de cordón',
  };
};

const productosMapper = (entity) => ({
  codigo: safe(entity.codigo),
  descripcion: safe(entity.descripcion),
  marca: safe(entity.marca),
  categoria: safe(entity.categoria),
  costo: formatNumber(entity.costo),
  moneda_costo: safe(entity.moneda_costo),
  stock: safe(entity.stock),
  precio_lista_ml: formatNumber(entity.precio_lista_ml),
  precio_pvp: formatNumber(entity.precio_pvp),
  precio_web_transferencia: formatNumber(entity.precio_web_transferencia),
});

const ventasMapper = (entity) => ({
  id_venta: safe(entity.id_venta ?? entity.id),
  id_operacion: safe(entity.id_operacion),
  fecha: formatDate(entity.fecha),
  marca: safe(entity.marca),
  categoria: safe(entity.categoria),
  codigo_item: safe(entity.codigo_item ?? entity.codigo),
  descripcion: safe(entity.descripcion),
  cantidad: safe(entity.cantidad),
  monto_unitario: formatNumber(entity.monto_unitario),
  monto_total: formatNumber(entity.monto_total),
});

const rmaMapper = (entity) => ({
  numero_caso: safe(entity.numero_caso),
  cliente_nombre: safe(entity.cliente_nombre),
  cliente_dni: safe(entity.cliente_dni),
  ml_id: safe(entity.ml_id),
  origen: safe(entity.origen),
  estado: safe(entity.estado),
  observaciones: safe(entity.observaciones),
  fecha_caso: formatDate(entity.fecha_caso ?? entity.created_at),
});

/**
 * Mapper de remito manual.
 * entity viene directo del state del ModalRemitoManual:
 * { cliente_nombre, cliente_cuit, ..., items: [{codigo, descripcion, cantidad, precio_unitario}], bultos, valor_declarado, ... }
 */
const sancionesMapper = (entity) => ({
  fecha_sancion: safe(entity.fecha_sancion || entity.fecha),
  empleado_nombre: safe(entity.empleado_nombre),
  empleado_legajo: safe(entity.empleado_legajo || entity.legajo),
  empleado_sector: safe(entity.empleado_sector || entity.sector),
  empleado_dni: safe(entity.empleado_dni || entity.dni),
  empleado_cuil: safe(entity.empleado_cuil || entity.cuil),
  empleado_puesto: safe(entity.empleado_puesto || entity.puesto),
  empleado_fecha_ingreso: formatDate(entity.empleado_fecha_ingreso || entity.fecha_ingreso),
  empleado_domicilio: safe(entity.empleado_domicilio || entity.domicilio),
  empleado_empresa: safe(entity.empleado_empresa || entity.empresa),
  tipo_sancion: safe(entity.tipo_sancion_nombre || entity.tipo_sancion),
  texto_sancion: safe(entity.texto_sancion),
  fecha_suspension_desde: formatDate(entity.fecha_desde),
  fecha_suspension_hasta: formatDate(entity.fecha_hasta),
  dias_suspension: safe(entity.dias_suspension),
  numero_interno: safe(entity.id),
});

const vacacionesMapper = (entity) => ({
  empleado_nombre: safe(entity.empleado_nombre),
  empleado_legajo: safe(entity.empleado_legajo || entity.legajo),
  empleado_dni: safe(entity.empleado_dni || entity.dni),
  empleado_area: safe(entity.empleado_area || entity.area),
  empleado_puesto: safe(entity.empleado_puesto || entity.puesto),
  fecha_desde: formatDate(entity.fecha_desde),
  fecha_hasta: formatDate(entity.fecha_hasta),
  dias_totales: safe(entity.dias_totales || entity.dias),
  anio_periodo: safe(entity.anio_periodo || entity.anio),
  fecha_reincorporacion: formatDate(entity.fecha_reincorporacion),
  texto_notificacion: safe(entity.texto_notificacion),
});

const remitoManualMapper = (entity) => {
  const items = entity.items || [];

  const tablaRows = items.map((item) => [
    safe(item.codigo),
    safe(item.descripcion),
    safe(item.cantidad),
    formatNumber(item.precio_unitario),
    formatNumber((Number(item.cantidad) || 0) * (Number(item.precio_unitario) || 0)),
  ]);

  return {
    cliente_nombre: safe(entity.cliente_nombre),
    cliente_cuit: safe(entity.cliente_cuit),
    cliente_direccion: safe(entity.cliente_direccion),
    cliente_ciudad: safe(entity.cliente_ciudad),
    cliente_cp: safe(entity.cliente_cp),
    cliente_telefono: safe(entity.cliente_telefono),
    fecha_remito: formatDate(entity.fecha_remito),
    shipping_id: safe(entity.shipping_id),
    bultos: safe(entity.bultos),
    valor_declarado: formatNumber(entity.valor_declarado),
    observaciones: safe(entity.observaciones),
    tabla_items: JSON.stringify(tablaRows),
  };
};

// =============================================================================
// REGISTRY
// =============================================================================

/**
 * Mapea un contexto a su función transformadora.
 * Si el contexto no existe, retorna un identity mapper (pass-through).
 */
const contextDataMappers = {
  pedidos: pedidosMapper,
  rrhh: rrhhMapper,
  envios: enviosMapper,
  productos: productosMapper,
  ventas: ventasMapper,
  rma: rmaMapper,
  sanciones: sancionesMapper,
  vacaciones: vacacionesMapper,
  remito_manual: remitoManualMapper,
};

/**
 * Transforma datos de una entidad al formato pdfme inputs.
 * @param {string} contexto - Contexto del template (pedidos, rrhh, etc.)
 * @param {object} entityData - Datos crudos de la entidad
 * @returns {object} Objeto plano { key: stringValue } para pdfme
 */
export const mapEntityToInputs = (contexto, entityData) => {
  const mapper = contextDataMappers[contexto];
  if (!mapper) {
    // Identity mapper: convierte todos los valores a string
    const result = {};
    for (const [key, value] of Object.entries(entityData || {})) {
      result[key] = safe(value);
    }
    return result;
  }
  return mapper(entityData || {});
};

export default contextDataMappers;
