/**
 * Registry de transformadores de datos por contexto.
 * Cada mapper recibe la entidad cruda de la página y retorna
 * un objeto plano { key: stringValue } compatible con pdfme inputs.
 *
 * Las keys deben coincidir con los nombres de variables del backend
 * (GET /api/document-templates/variables/{contexto}).
 */

/** Fecha ISO sin hora, como la serializa una columna `Date` del backend. */
const SOLO_FECHA = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Parsea un valor de fecha a `Date`, corrigiendo el corrimiento de zona horaria.
 *
 * Un `YYYY-MM-DD` pelado lo parsea el motor como medianoche UTC, así que en
 * Argentina (UTC-3) `new Date('2026-08-03')` cae el 2 de agosto y el documento
 * imprime el día ANTERIOR. Anclar al mediodía LOCAL deja el día correcto en
 * cualquier huso realista (UTC-11 a UTC+12).
 *
 * Los valores que ya traen hora se parsean tal cual: ahí no hay corrimiento,
 * porque un ISO con hora se interpreta en la zona local.
 *
 * @returns {Date|null} `null` si el valor no es una fecha parseable.
 */
const parseFecha = (val) => {
  const raw = typeof val === 'string' && SOLO_FECHA.test(val.trim()) ? `${val.trim()}T12:00:00` : val;
  const d = new Date(raw);
  return Number.isNaN(d.getTime()) ? null : d;
};

/**
 * Formatea una fecha como `d/m/aaaa`.
 *
 * Un valor no parseable devuelve el original. El `try/catch` anterior era
 * codigo muerto: `new Date()` no tira, devuelve `Invalid Date`, así que una
 * fecha rota terminaba impresa como el texto "Invalid Date".
 */
const formatDate = (val) => {
  if (!val) return '';
  const d = parseFecha(val);
  return d ? d.toLocaleDateString('es-AR') : String(val);
};

/** Igual que `formatDate` pero con día y mes de dos dígitos: `dd/mm/aaaa`. */
const formatDateOnly = (val) => {
  if (!val) return '';
  const d = parseFecha(val);
  return d ? d.toLocaleDateString('es-AR', { day: '2-digit', month: '2-digit', year: 'numeric' }) : String(val);
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

/**
 * Mapper del registro de horarios (contexto `horarios_empleado`).
 *
 * Recibe UN empleado del array `empleados[]` que devuelve
 * `GET /api/rrhh/reportes/horarios-documento`, con el rango y la preferencia
 * de columnas mergeados encima por el caller:
 * {
 *   legajo, nombre_completo, dni, cuil, puesto, area,
 *   dias: [{ fecha_label, dia_semana, entrada, salida, horas_hhmm,
 *            estado, sin_fichadas, incompleto }],
 *   total_horas_hhmm, total_dias,
 *   fecha_desde, fecha_hasta, incluir_horas
 * }
 *
 * TODOS los días van a UNA sola tabla. No se parten en dos: pdfme modela la
 * página como un único flujo vertical, así que dos tablas en el mismo `y`
 * terminan una encima de la otra (ver el comentario de `TABLE_H` en
 * `backend/app/scripts/seed_horarios_template.py`). Un rango largo lo pagina
 * pdfme solo.
 */
const horariosEmpleadoMapper = (entity) => {
  const dias = Array.isArray(entity.dias) ? entity.dias : [];
  // Ausente por omisión sería mentir por defecto: la columna va salvo que el
  // caller pida explícitamente sacarla.
  const incluirHoras = entity.incluir_horas !== false;

  const filas = dias.map((dia) => {
    const etiquetaDia = [dia.dia_semana, dia.fecha_label].filter(Boolean).join(' ');

    // Un renglón en blanco no dice NADA: el documento respalda una
    // liquidación, así que un día sin fichadas tiene que declarar por qué
    // (AUSENTE / VACACIONES / ART / LICENCIA...) en la columna Entrada.
    let entrada = safe(dia.entrada);
    let salida = safe(dia.salida);
    let horas = safe(dia.horas_hhmm);

    if (dia.sin_fichadas) {
      entrada = safe(dia.estado).toUpperCase();
      salida = '';
      horas = '';
    } else if (dia.incompleto) {
      // Fichada única: hay entrada, no hay salida y las horas no se pueden
      // calcular. Mostrar 00:00 haría parecer que trabajó cero.
      salida = '';
      horas = '';
    }

    return incluirHoras ? [etiquetaDia, entrada, salida, horas] : [etiquetaDia, entrada, salida];
  });

  return {
    legajo: safe(entity.legajo),
    nombre_completo: safe(entity.nombre_completo),
    dni: safe(entity.dni),
    cuil: safe(entity.cuil),
    puesto: safe(entity.puesto),
    area: safe(entity.area),
    periodo: `${formatDateOnly(entity.fecha_desde)} - ${formatDateOnly(entity.fecha_hasta)}`,
    fecha_emision: new Date().toLocaleDateString('es-AR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    }),
    total_horas: safe(entity.total_horas_hhmm),
    total_dias: safe(entity.total_dias),
    tabla_dias: JSON.stringify(filas),
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
  horarios_empleado: horariosEmpleadoMapper,
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
