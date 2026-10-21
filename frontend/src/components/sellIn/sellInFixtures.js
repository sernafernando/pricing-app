/**
 * Test fixtures for the sell-in screen, shaped exactly like the backend's
 * Pydantic responses (`backend/app/schemas/sell_in.py`: `SellInCompraOut`,
 * `SellInCompraListOut`, `SellInCompraResumenOut`, `SellInPreviewOut`,
 * `SellInPrefillOut`, `SellInOperacionesOut`).
 * Decimals travel as strings, as Pydantic serialises them.
 *
 * The values come from the backend's own tests
 * (`backend/tests/routers/test_sell_in_compras.py`): products 4512 SW-8 and
 * 4513 SW-16 at cost 100 and 300, a 1000 ARS proportional split (250 / 750,
 * 25 %), the 4514 AP-1 USD product, and the resumen of `tres_compras` plus
 * one USD purchase.
 */

export const COMPRA_ARS = {
  id: 1,
  proveedor_id: 7,
  pedido_compra_id: null,
  pedido_compra_ids: [],
  fecha_compra: '2026-10-01',
  fecha_ingreso: null,
  cuenta_desde: 'compra',
  moneda: 'ARS',
  monto_total: '1000.00',
  tipo_cambio: null,
  formula: 'proporcional',
  estado: 'activa',
  descripcion: 'Bonificación Q4 switches',
  usuario_id: 1,
  created_at: '2026-10-01T12:00:00',
  updated_at: '2026-10-01T12:00:00',
  proveedor_nombre: 'TP-Link',
  aplica: true,
  unidades_total: 20,
  unidades_consumidas: 0,
  unidades_restantes: 20,
  items: [
    {
      id: 11,
      item_id: 4512,
      codigo: 'SW-8',
      descripcion: 'Switch 8 bocas',
      cantidad: 10,
      costo_base_unit: '100',
      monto_asignado: '250.00',
      descuento_unit: '25',
      costo_con_sell_in_unit: '75',
      porcentaje: '25.00',
      unidades_consumidas: 0,
      unidades_restantes: 10,
    },
    {
      id: 12,
      item_id: 4513,
      codigo: 'SW-16',
      descripcion: 'Switch 16 bocas',
      cantidad: 10,
      costo_base_unit: '300',
      monto_asignado: '750.00',
      descuento_unit: '75',
      costo_con_sell_in_unit: '225',
      porcentaje: '25.00',
      unidades_consumidas: 0,
      unidades_restantes: 10,
    },
  ],
};

export const COMPRA_USD_ANULADA = {
  ...COMPRA_ARS,
  id: 2,
  proveedor_id: null,
  proveedor_nombre: null,
  fecha_compra: '2026-09-15',
  moneda: 'USD',
  monto_total: '2.00',
  tipo_cambio: '1250.5',
  estado: 'anulada',
  descripcion: 'Descuento access points',
  aplica: false,
  unidades_total: 2,
  unidades_restantes: 2,
  items: [
    {
      id: 21,
      item_id: 4514,
      codigo: 'AP-1',
      descripcion: 'Access point',
      cantidad: 2,
      costo_base_unit: '10',
      monto_asignado: '2.00',
      descuento_unit: '1',
      costo_con_sell_in_unit: '9',
      porcentaje: '10.00',
      unidades_consumidas: 0,
      unidades_restantes: 2,
    },
  ],
};

export const LISTA = { items: [COMPRA_ARS, COMPRA_USD_ANULADA], total: 2, page: 1, page_size: 50 };

export const RESUMEN = {
  conteo: { si: 3, no: 1, todas: 4 },
  monto_total: { ARS: '3000.00', USD: '5.50' },
  unidades_total: 32,
};

export const PREVIEW = {
  moneda: 'ARS',
  formula: 'proporcional',
  monto_total: '1000.00',
  // `SellInPreviewLinea`: a purchase line without its id and consumption counts.
  lineas: COMPRA_ARS.items.map((item) => {
    const linea = { ...item };
    delete linea.id;
    delete linea.unidades_consumidas;
    delete linea.unidades_restantes;
    return linea;
  }),
  totales: {
    cantidad: 20,
    costo_base_total: '4000',
    monto_asignado_total: '1000.00',
    costo_con_sell_in_total: '3000',
    porcentaje: '25.00',
  },
};

/** `GET /productos` rows (`ProductoResponse`), the fields the picker reads. */
export const PRODUCTOS = [
  { item_id: 4512, codigo: 'SW-8', descripcion: 'Switch 8 bocas', marca: 'TP-Link', moneda_costo: 'ARS', costo: 100 },
  { item_id: 4513, codigo: 'SW-16', descripcion: 'Switch 16 bocas', marca: 'Mercusys', moneda_costo: 'ARS', costo: 300 },
];

/** A purchase linked to two Compras operations (`pedido_compra_id` mirrors the first one). */
export const COMPRA_CON_OPERACIONES = { ...COMPRA_ARS, id: 4, pedido_compra_id: 15, pedido_compra_ids: [15, 16] };

/** `GET /sell-in/compras/prefill` (`SellInPrefillOut`) for operations 15 and 16 of supplier 7. */
export const PREFILL = {
  pedido_compra_ids: [15, 16],
  proveedor_id: 7,
  proveedor_nombre: 'TP-Link',
  moneda: 'USD',
  fecha_ingreso: '2026-10-05',
  items: [
    { item_id: 4512, codigo: 'SW-8', descripcion: 'Switch 8 bocas', cantidad: 12 },
    { item_id: 4513, codigo: 'SW-16', descripcion: 'Switch 16 bocas', cantidad: 4 },
  ],
};

/**
 * `GET /sell-in/compras/operaciones` (`SellInOperacionesOut`) items, newest first: operations 15 and 16 of
 * TP-Link (7) in USD, the ones `PREFILL` reads, and 20 of Mercusys (9) in ARS. Shaped like the backend's
 * `test_each_option_carries_what_identifies_the_operation`.
 */
export const OPERACIONES = [
  {
    id: 20,
    numero: 'P-00020',
    proveedor_id: 9,
    proveedor_nombre: 'Mercusys',
    fecha: '2026-10-08',
    moneda: 'ARS',
    monto: '850000.00',
    estado: 'pagado',
    numero_factura: null,
  },
  {
    id: 16,
    numero: 'P-00016',
    proveedor_id: 7,
    proveedor_nombre: 'TP-Link',
    fecha: '2026-10-03',
    moneda: 'USD',
    monto: '5000.50',
    estado: 'recibido',
    numero_factura: 'A-0001-00001234',
  },
  {
    id: 15,
    numero: 'P-00015',
    proveedor_id: 7,
    proveedor_nombre: 'TP-Link',
    fecha: '2026-10-02',
    moneda: 'USD',
    monto: '12000.00',
    estado: 'aprobado',
    numero_factura: null,
  },
];

/**
 * A fake of `GET /operaciones` over `OPERACIONES` with the backend's rules: text matches the id exactly or
 * the number, supplier or invoice in part; filters by supplier, currency and the linked ones. Any other
 * all-digit text is an operation of TP-Link in USD with that id, so a test can link as many as it needs.
 */
export function operacionesFake(params = {}) {
  const q = (params.q ?? '').trim().toLowerCase();
  const conocida = OPERACIONES.some((o) => String(o.id) === q);
  const todas = /^\d+$/.test(q) && !conocida ? [{ ...OPERACIONES[2], id: Number(q), numero: `P-${q.padStart(5, '0')}` }] : OPERACIONES;
  const items = todas.filter(
    (o) =>
      (!q ||
        String(o.id) === q ||
        [o.numero, o.proveedor_nombre, o.numero_factura].some((campo) => (campo ?? '').toLowerCase().includes(q))) &&
      (params.proveedor_id == null || o.proveedor_id === params.proveedor_id) &&
      (params.moneda == null || o.moneda === params.moneda) &&
      !(params.excluir ?? []).includes(o.id),
  );
  return Promise.resolve({ data: { items } });
}

/** `GET /sell-in/compras/operaciones/{id}/productos` (`SellInOperacionProductosOut`) of operation 16. */
export const PRODUCTOS_OPERACION = {
  items: [
    { item_id: 4512, codigo: 'SW-8', descripcion: 'Switch 8 bocas', pedida: 12, recibida: 10 },
    { item_id: 4513, codigo: 'SW-16', descripcion: 'Switch 16 bocas', pedida: 4, recibida: 0 },
  ],
};

/* Brand bonus (`backend/app/schemas/sell_in_bonos.py`: `SellInBonoOut`, `SellInBonoListOut`, `SellInBonoAlcanceOut`). */
export const BONO = {
  id: 3,
  marca: 'TP-LINK',
  monto_unit: '3.00',
  moneda: 'USD',
  fecha_desde: '2026-09-01',
  fecha_hasta: '2026-11-30',
  descripcion: 'Bono TP-Link USD 3/u',
  estado: 'activa',
  usuario_id: 1,
  created_at: '2026-08-28T12:00:00-03:00',
  updated_at: '2026-08-28T12:00:00',
  compras_activas: 18,
  unidades: 1040,
  monto_generado: '3120.00',
};

export const BONO_ANULADO = { ...BONO, id: 4, estado: 'anulada', descripcion: 'Bono anulado', compras_activas: 0, unidades: 0, monto_generado: '0.00' };

export const BONOS_LISTA = { items: [BONO, BONO_ANULADO], total: 2, page: 1, page_size: 10 };

export const ALCANCE = {
  limite: 20,
  alcanzadas: {
    total: 18,
    items: [
      {
        compra_id: 41,
        pedido_id: 1722,
        numero: 'OC-2026-01722',
        proveedor_nombre: 'Distribuidora Mayorista',
        numero_factura: 'A-0003-00045871',
        fecha_factura: '2026-09-02',
        unidades: 80,
        monto: '240.00',
        moneda: 'USD',
      },
    ],
  },
  pendientes: {
    total: 1,
    items: [
      { pedido_id: 1890, numero: 'OC-2026-01890', proveedor_nombre: 'Global Tech', numero_factura: 'A-0007-00012233', fecha_factura: null, unidades: 120 },
    ],
  },
  fuera_de_rango: {
    total: 1,
    items: [
      { pedido_id: 1650, numero: 'OC-2026-01650', proveedor_nombre: 'TP-Link Argentina', numero_factura: null, fecha_factura: '2026-08-28', unidades: 15 },
    ],
  },
};

export const ALCANCE_VACIO = {
  limite: 20,
  alcanzadas: { total: 0, items: [] },
  pendientes: { total: 0, items: [] },
  fuera_de_rango: { total: 0, items: [] },
};

/** A sell in the worker generated for `BONO` (only the bonus changes or voids it). */
export const COMPRA_BONO = {
  ...COMPRA_ARS,
  id: 41,
  descripcion: 'Bono de marca TP-LINK (bono 3)',
  moneda: 'USD',
  tipo_cambio: '1450.000000',
  formula: 'por_unidad',
  origen: 'bono_marca',
  bono_id: 3,
};
