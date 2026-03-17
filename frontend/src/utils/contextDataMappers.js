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

const enviosMapper = (entity) => ({
  shipping_id: safe(entity.shipping_id ?? entity.id),
  fecha_envio: formatDate(entity.fecha_envio),
  logistica: safe(entity.logistica_nombre ?? entity.logistica),
  transporte: safe(entity.transporte_nombre ?? entity.transporte),
  destinatario: safe(entity.manual_receiver_name ?? entity.mlreceiver_name ?? entity.destinatario),
  calle: safe(entity.manual_street_name ?? entity.mlstreet_name ?? entity.calle),
  numero: safe(entity.manual_street_number ?? entity.mlstreet_number ?? entity.numero),
  cp: safe(entity.manual_zip_code ?? entity.mlzip_code ?? entity.cp),
  ciudad: safe(entity.manual_city_name ?? entity.mlcity_name ?? entity.ciudad),
  telefono: safe(entity.manual_phone ?? entity.mlreceiver_phone ?? entity.telefono),
  observaciones: safe(entity.manual_comment ?? entity.direccion_comentario ?? entity.observaciones),
  total_bultos: safe(entity.total_bultos),
  transporte_direccion: safe(entity.transporte_direccion),
  transporte_telefono: safe(entity.transporte_telefono),
});

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
