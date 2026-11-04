/** Sell-out API shapes (backend `app/schemas/sell_out.py`) for the sell-out UI tests. */

const RESUMEN_BASE = {
  lineas: 12,
  unidades: 30,
  monto: '1080.00',
  monto_ars: '1512000.00',
  ars_estimado: false,
  tope_unidades_restantes: null,
  tope_monto_restante: null,
  pendientes_base: 0,
  por_canal: [
    { canal: 'ml', lineas: 8, unidades: 20, monto: '720.00' },
    { canal: 'fuera', lineas: 4, unidades: 10, monto: '360.00' },
  ],
  recalculo: { estado: 'al_dia', intentos: 0, error: null, detenida: false, encolada_en: null },
};

export const CAMPANA_MIGRADA = {
  id: 55,
  nombre: 'RB 8180',
  descripcion: null,
  fecha_desde: '2026-01-01',
  fecha_hasta: '2026-12-31',
  tipo: 'por_unidad',
  monto_unit: '36.00',
  porcentaje: null,
  base_porcentaje: 'costo',
  moneda: 'USD',
  tc_modo: 'al_cobro',
  tipo_cambio: null,
  tc_definido_en: null,
  tope_unidades: null,
  tope_monto: null,
  acumulable: true,
  monto_incluye_iva: false,
  estado: 'activa',
  usuario_id: 2,
  offset_origen_id: 48,
  created_at: '2026-10-22T15:10:00Z',
  updated_at: '2026-10-22T15:10:00Z',
  grupos: [{ id: 301, nombre: 'Offset #48: RB 8180' }],
  items: [],
  programa_id: null,
  programa: null,
  resumen: RESUMEN_BASE,
};

export const CAMPANA_PORCENTAJE_ANULADA = {
  ...CAMPANA_MIGRADA,
  id: 60,
  nombre: 'TP-Link 2% noviembre',
  descripcion: 'Acuerdo con la marca',
  tipo: 'porcentaje',
  monto_unit: null,
  porcentaje: '2.0000',
  base_porcentaje: 'precio_neto',
  moneda: 'ARS',
  tc_modo: null,
  tope_unidades: 500,
  tope_monto: '1000000.00',
  monto_incluye_iva: true,
  acumulable: false,
  estado: 'anulada',
  offset_origen_id: null,
  grupos: [{ id: 1, nombre: 'TP-Link redes' }],
  resumen: {
    ...RESUMEN_BASE,
    tope_unidades_restantes: 470,
    tope_monto_restante: '998920.00',
    por_canal: [],
    recalculo: { estado: 'fallida', intentos: 3, error: 'Falta el tipo de cambio', detenida: true, encolada_en: null },
  },
};

export const CAMPANAS_LISTA = { items: [CAMPANA_MIGRADA, CAMPANA_PORCENTAJE_ANULADA], total: 2, page: 1, page_size: 10 };

export const CONSUMOS_USD = {
  moneda: 'USD',
  ars_estimado: true,
  items: [
    {
      id: 1,
      canal: 'ml',
      venta_ref: 9001,
      fecha_venta: '2026-10-20',
      item_id: 4172,
      codigo: 'C13T00R120',
      descripcion: 'Epson EcoTank L8180',
      unidades: 2,
      monto: '72.00',
      tc_venta: '1415.500000',
      monto_ars: '101916.00',
    },
    {
      id: 2,
      canal: 'fuera',
      venta_ref: 552,
      fecha_venta: '2026-10-18',
      item_id: 4172,
      codigo: null,
      descripcion: null,
      unidades: -1,
      monto: '-36.00',
      tc_venta: '1410.000000',
      monto_ars: '-50760.00',
    },
  ],
  total: 30,
  page: 1,
  page_size: 25,
};

/** A `monto_total` campaign (T26c): one ARS amount split by hand, a % share and a fixed share. */
export const CAMPANA_MONTO_TOTAL = {
  ...CAMPANA_MIGRADA,
  id: 70,
  nombre: 'TP-Link bono Q4',
  tipo: 'monto_total',
  monto_unit: null,
  monto_total: '2000000.00',
  moneda: 'ARS',
  tc_modo: null,
  offset_origen_id: null,
  grupos: [{ id: 1, nombre: 'TP-Link redes' }],
  items: [
    { item_id: 4172, codigo: 'C13T00R120', descripcion: 'Epson EcoTank L8180', monto_unit: null, reparto_porcentaje: '60.0000', reparto_monto: null },
    { item_id: 4173, codigo: 'C11CJ21301', descripcion: 'Epson EcoTank L3250', monto_unit: null, reparto_porcentaje: null, reparto_monto: '500000.00' },
  ],
  resumen: {
    ...RESUMEN_BASE,
    reparto: { asignado: '1700000.00', asignado_sin_ventas: '500000.00', sin_asignar: '300000.00', motivo: null },
  },
};

/** A negative `monto_total` campaign (S35, offset 50): a deduction, nothing split yet. */
export const CAMPANA_MONTO_TOTAL_NEGATIVA = {
  ...CAMPANA_MONTO_TOTAL,
  id: 71,
  nombre: 'LENOVO cta y orden',
  monto_total: '-13662075.00',
  grupos: [{ id: 2, nombre: 'LENOVO' }],
  items: [],
  resumen: {
    ...RESUMEN_BASE,
    por_canal: [],
    reparto: { asignado: '0.00', asignado_sin_ventas: '0.00', sin_asignar: '-13662075.00', motivo: null },
  },
};

/** `GET /{id}/renovacion` of CAMPANA_MIGRADA (`SellOutCampanaIn`): a model name, so it stays; the next quarter. */
export const RENOVACION_MIGRADA = {
  nombre: 'RB 8180',
  descripcion: 'Acuerdo con Epson',
  fecha_desde: '2027-01-01',
  fecha_hasta: '2027-03-31',
  tipo: 'por_unidad',
  monto_unit: '36.00',
  monto_total: null,
  porcentaje: null,
  base_porcentaje: 'costo',
  moneda: 'USD',
  tc_modo: 'fijo',
  tipo_cambio: '1400.000000',
  tope_unidades: 500,
  tope_monto: null,
  acumulable: false,
  monto_incluye_iva: true,
  grupo_ids: [301],
  items: [{ item_id: 4172, monto_unit: '30.00', reparto_porcentaje: null, reparto_monto: null }],
  programa_id: 12,
  renovada_de_id: 55, // the campaign it renews (CAMPANA_MIGRADA)
};

/** `GET /{id}/renovacion` of CAMPANA_MONTO_TOTAL: its total and its two shares. */
export const RENOVACION_MONTO_TOTAL = {
  ...RENOVACION_MIGRADA,
  nombre: 'TP-Link bono Q4',
  descripcion: null,
  tipo: 'monto_total',
  monto_unit: null,
  monto_total: '2000000.00',
  moneda: 'ARS',
  tc_modo: null,
  tipo_cambio: null,
  tope_unidades: null,
  acumulable: true,
  monto_incluye_iva: false,
  grupo_ids: [1],
  items: [
    { item_id: 4172, monto_unit: null, reparto_porcentaje: '60.0000', reparto_monto: null },
    { item_id: 4173, monto_unit: null, reparto_porcentaje: null, reparto_monto: '500000.00' },
  ],
  programa_id: null,
  renovada_de_id: 70, // CAMPANA_MONTO_TOTAL
};

// ── Programs (campanas-sistema slice E): `app/schemas/sell_out.py` SellOutPrograma*, SellOutGrupoPrograma*,
// SellOutSugerencia*.

export const PROGRAMA_MARCA = {
  id: 7,
  nombre: 'MARCA PROG',
  descripcion: null,
  estado: 'activo',
  campanas: 3,
  activas: 2,
  desde: '2026-08-01',
  hasta: '2026-10-31',
  nombres: 2,
};

export const PROGRAMA_ARCHIVADO = {
  ...PROGRAMA_MARCA,
  id: 8,
  nombre: 'Modelos SP',
  estado: 'archivado',
  campanas: 1,
  activas: 1,
  nombres: 1,
  desde: '2025-11-01',
};

export const PROGRAMAS_LISTA = { items: [PROGRAMA_MARCA, PROGRAMA_ARCHIVADO], total: 2, page: 1, page_size: 200 };
export const PROGRAMAS_VACIO = { items: [], total: 0, page: 1, page_size: 200 };

/** `GET /sell-out/campanas/por-programa`: only MARCA PROG has campaigns under the filters; one has no program. */
export const GRUPOS_POR_PROGRAMA = {
  items: [{ programa_id: 7, nombre: 'MARCA PROG', campanas: 3, activas: 2, nombres: 2, desde: '2026-08-01', hasta: '2026-10-31' }],
  total: 1,
  page: 1,
  page_size: 50,
  sin_programa: { programa_id: null, nombre: null, campanas: 1, activas: 1, nombres: 1, desde: '2026-01-01', hasta: '2026-12-31' },
};

const DEL_PROGRAMA = { programa_id: 7, programa: { id: 7, nombre: 'MARCA PROG' }, offset_origen_id: null };

export const CAMPANAS_DEL_PROGRAMA = {
  items: [
    { ...CAMPANA_MIGRADA, ...DEL_PROGRAMA, id: 71, nombre: 'MARCA PROG 3.0', fecha_desde: '2026-08-01', fecha_hasta: '2026-10-31' },
    { ...CAMPANA_MIGRADA, ...DEL_PROGRAMA, id: 72, nombre: 'MARCA PROGRAM1', fecha_desde: '2026-08-01', fecha_hasta: '2026-10-31' },
  ],
  total: 2,
  page: 1,
  page_size: 200,
};

const sugerida = (id, nombre, desde, hasta, estado = 'activa') => ({ id, nombre, fecha_desde: desde, fecha_hasta: hasta, estado });

/** `GET /sell-out/programas/sugerencias`: card 1 shares a prefix, card 2 does not (its `base` is the date range). */
export const SUGERENCIAS = {
  items: [
    {
      base: 'MARCA',
      fecha_desde: '2026-08-01',
      fecha_hasta: '2026-10-31',
      nombres: 2,
      campanas: [
        sugerida(81, 'MARCA PROGRAM1', '2026-08-01', '2026-10-31'),
        sugerida(82, 'MARCA PROGRAM1', '2026-08-01', '2026-10-31'),
        sugerida(83, 'MARCA PROG 3.0', '2026-08-01', '2026-10-31', 'anulada'),
      ],
    },
    {
      base: 'Del 01/11/2025 al 31/10/2026',
      fecha_desde: '2025-11-01',
      fecha_hasta: '2026-10-31',
      nombres: 2,
      campanas: [sugerida(91, 'M20 / M80 SP', '2025-11-01', '2026-10-31'), sugerida(92, 'MODELO 8180', '2025-11-01', '2026-10-31')],
    },
  ],
  total: 2,
  page: 1,
  page_size: 200,
};
export const SUGERENCIAS_VACIO = { items: [], total: 0, page: 1, page_size: 200 };

/** `GET /sell-out/programas/7/renovacion`: Oct–Dic 2026 into Ene–Mar 2027, two to copy, one voided, one already
 * renewed, and one of the next quarter left for a later pass. */
export const RENOVACION_MARCA = {
  programa_id: 7,
  programa: 'MARCA PROG',
  periodo_desde: '2026-10-01',
  periodo_hasta: '2026-12-31',
  fecha_desde: '2027-01-01',
  fecha_hasta: '2027-03-31',
  renovar: [
    { campana_id: 11, nombre: 'Modelo A Q4 2026', nombre_nuevo: 'Modelo A Q1 2027' },
    { campana_id: 12, nombre: 'Modelo B Q4 2026', nombre_nuevo: 'Modelo B Q1 2027' },
  ],
  omitidas: [
    { campana_id: 13, nombre: 'Modelo C Q4 2026', motivo: 'anulada, no se renueva' },
    { campana_id: 14, nombre: 'Modelo D Q4 2026', motivo: 'ya renovada en la campaña 812 (Modelo D Q1 2027)' },
  ],
  quedan_afuera: [{ campana_id: 15, nombre: 'Modelo E Q1 2027', fecha_hasta: '2027-03-31' }],
};
