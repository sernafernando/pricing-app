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
