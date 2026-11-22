/**
 * GET /api/tacticals answers in the shape of the final contract (handoffs/tactical-tarea.md, "Contrato final", T1
 * 2026-11-05): one line per child, each with its own currency and usage, and `linea`, the POSTed line it comes from.
 * The numbers are the list design's; swap them for a real capture once the endpoint is deployed.
 */

const CABECERA = {
  marca: 'HP',
  referencia: null,
  nota: null,
  fecha_desde: '2026-11-01',
  moneda: 'USD',
  tc_modo: 'al_cobro',
  tipo_cambio: null,
  incluye_iva: false,
  acumulable: true,
  estado: 'activo',
  usuario_id: 3,
  created_at: '2026-11-01T12:00:00Z',
  updated_at: '2026-11-01T12:00:00Z',
};

const LINEA = {
  origen: 'sell_out_campana',
  estado: 'activa',
  alcance: 'productos',
  productos: [],
  marca: null,
  categoria: null,
  pedido_compra_id: null,
  pedido_numero: null,
  modo_monto: 'por_unidad',
  moneda: 'USD',
  tope_monto: null,
  tope_por_producto: false,
};

/** A per-product line: one child per product, with its own unit cap; the children of POSTed line `linea` share it. */
export const lineaDeProducto = (id, itemId, codigo, descripcion, valor, tope, usadas, linea = 1) => ({
  ...LINEA,
  id,
  linea,
  productos: [{ item_id: itemId, codigo, descripcion }],
  valor: String(valor),
  tope_unidades: tope,
  tope_por_producto: true,
  unidades_usadas: usadas,
  monto_usado: String(valor * usadas),
});

export const TACTICAL_BPS = {
  ...CABECERA,
  id: 1,
  tipo: 'sell_out',
  nombre: 'Tacticals BPS Noviembre Q1FY27',
  referencia: 'Q1 FY27 · BPS',
  fecha_hasta: '2026-11-30',
  lineas: [
    lineaDeProducto(11, 101, 'AIO-G2-R5', 'AIO HP G2 R5 16G 512 W11H', 220, 90, 58),
    lineaDeProducto(12, 102, 'NB-250RG10', 'Notebook HP 250RG10 5-120U', 100, 62, 62),
    {
      ...LINEA,
      id: 13,
      linea: 2,
      productos: [
        { item_id: 201, codigo: 'MON-V24I', descripcion: 'Monitor V24i G5' },
        { item_id: 202, codigo: 'MON-V27I', descripcion: 'Monitor V27i G5' },
      ],
      valor: '12',
      tope_unidades: 300,
      tope_monto: '3000',
      unidades_usadas: 132,
      monto_usado: '1584',
    },
  ],
};

export const TACTICAL_REBATE = {
  ...CABECERA,
  id: 3,
  tipo: 'sell_in',
  nombre: 'Rebate HP Q1FY27',
  moneda: 'ARS',
  tc_modo: null,
  fecha_hasta: '2027-01-31',
  lineas: [
    {
      ...LINEA,
      id: 31,
      linea: 1,
      origen: 'sell_in_bono',
      alcance: 'marca',
      marca: 'HP',
      modo_monto: 'porcentaje',
      valor: '3.5',
      moneda: 'ARS',
      tope_unidades: null,
      unidades_usadas: 410,
      monto_usado: '1240000',
    },
  ],
};

export const pagina = (items, total = items.length, page = 1, pageSize = 50) => ({ total, page, page_size: pageSize, items });

/** A collection record as `PUT /api/tacticals/{id}/cobranza` answers it (tactical cobranza, PR #2182 router test). */
export const COBRANZA_FONDO = {
  fecha_cobro: '2026-11-09',
  medio: 'fondo_distribuidor',
  nc_numero: null,
  distribuidor: 'Grupo Núcleo',
  otro_detalle: null,
  observaciones: 'Acreditado en la cuenta corriente de noviembre',
  usuario_id: 3,
  created_at: '2026-11-09T15:20:00Z',
  updated_at: '2026-11-09T15:20:00Z',
};

/** `kpis` of `GET /api/tacticals` (PR #2182): count and money used per currency, ARS first. */
export const KPIS_COBRANZA = {
  pendientes: {
    cantidad: 12,
    sin_tope: 3,
    montos: [
      { moneda: 'ARS', monto: '4380250.00', tope: '6000000.00', tope_parcial: false },
      { moneda: 'USD', monto: '1920.00', tope: '800.00', tope_parcial: true },
    ],
  },
  cobrados: {
    cantidad: 7,
    sin_tope: 0,
    montos: [
      { moneda: 'ARS', monto: '2115000.00', tope: '2500000.00', tope_parcial: false },
      { moneda: 'USD', monto: '640.00', tope: '800.00', tope_parcial: false },
    ],
  },
};

/**
 * `GET /api/tacticals/cargas-pendientes` (tacticals approval S11, `CargaPendienteOut`): the bonuses, purchases and
 * campaigns loaded on their own that wait for approval, newest first.
 */
export const CARGA_CAMPANA = {
  origen: 'sell_out_campana',
  id: 412,
  nombre: 'SP Epson noviembre',
  marca: null,
  moneda: 'USD',
  fecha_desde: '2026-11-01',
  fecha_hasta: '2026-11-30',
  usuario_id: 3,
  usuario_nombre: 'Martina',
  created_at: '2026-11-11T14:05:00Z',
};
export const CARGA_BONO = {
  origen: 'sell_in_bono',
  id: 31,
  nombre: 'Bono TP-Link',
  marca: 'TP-Link',
  moneda: 'ARS',
  fecha_desde: '2026-10-01',
  fecha_hasta: '2026-12-31',
  usuario_id: 3,
  usuario_nombre: 'Martina',
  created_at: '2026-11-10T09:30:00Z',
};
export const CARGA_COMPRA = {
  origen: 'sell_in_compra',
  id: 87,
  nombre: 'NC Lenovo octubre',
  marca: null,
  moneda: 'ARS',
  fecha_desde: '2026-10-28',
  fecha_hasta: '2026-10-28',
  usuario_id: null,
  usuario_nombre: null,
  created_at: '2026-11-09T18:00:00Z',
};
/** A legacy profit offset loaded from Offsets (tacticals approval S10): approved from the inbox itself. */
export const CARGA_OFFSET = {
  origen: 'offset_ganancia',
  id: 905,
  nombre: 'Offset Epson',
  marca: 'Epson',
  moneda: 'ARS',
  fecha_desde: '2026-11-01',
  fecha_hasta: null,
  usuario_id: 3,
  usuario_nombre: 'Martina',
  created_at: '2026-11-08T11:00:00Z',
};
export const CARGAS_PENDIENTES = [CARGA_CAMPANA, CARGA_BONO, CARGA_COMPRA, CARGA_OFFSET];
