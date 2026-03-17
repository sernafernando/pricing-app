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
 * Mapper de colecta de envíos.
 * entity debe tener la forma:
 * {
 *   fecha_colecta: "2026-03-15",
 *   logistica: "Andreani",
 *   transporte: "OCA",
 *   transporte_direccion: "...",
 *   transporte_telefono: "...",
 *   envios: [ { shipping_id, destinatario, direccion, cp, ciudad, bultos }, ... ]
 * }
 */
const enviosMapper = (entity) => {
  const envios = entity.envios || [];

  // Construir tabla: array de arrays de strings (filas) para pdfme table plugin
  const tablaRows = envios.map((e) => [
    safe(e.shipping_id),
    safe(e.manual_receiver_name ?? e.mlreceiver_name ?? e.destinatario),
    safe(e.direccion_completa ?? [e.manual_street_name ?? e.mlstreet_name, e.manual_street_number ?? e.mlstreet_number].filter(Boolean).join(' ')),
    safe(e.manual_zip_code ?? e.mlzip_code ?? e.cp),
    safe(e.manual_city_name ?? e.mlcity_name ?? e.ciudad),
    safe(e.total_bultos ?? '1'),
  ]);

  const totalBultos = envios.reduce((sum, e) => sum + (Number(e.total_bultos) || 1), 0);

  return {
    fecha_colecta: formatDate(entity.fecha_colecta ?? entity.fecha_envio),
    logistica: safe(entity.logistica_nombre ?? entity.logistica),
    transporte: safe(entity.transporte_nombre ?? entity.transporte),
    transporte_direccion: safe(entity.transporte_direccion),
    transporte_telefono: safe(entity.transporte_telefono),
    total_envios: String(envios.length),
    total_bultos: String(totalBultos),
    tabla_envios: JSON.stringify(tablaRows),
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
