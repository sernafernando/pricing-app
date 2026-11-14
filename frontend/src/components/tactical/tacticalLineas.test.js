/**
 * The lines of Nuevo tactical as pure state: what each can charge at most, what stops a save, and the body of
 * `POST /tacticals` (handoffs/tactical-tarea.md, "Contrato final").
 */
import { describe, it, expect } from 'vitest';
import {
  alternarFactura,
  conAlcance,
  conLineaDeLaPantalla,
  copiarLinea,
  cuerpoDe,
  dinero,
  lineasPara,
  maximoACobrar,
  modosDe,
  maximoTotal,
  modosNoDisponibles,
  nuevaLinea,
  numeroDe,
  porFactura,
  problemaDe,
  puedeCompartir,
  unidadesDelTope,
} from './tacticalLineas';
import { CATALOGO, OPERACIONES } from './tacticalFixtures';

const producto = (id) => CATALOGO.find((p) => p.item_id === id);
const linea = (cambios) => ({ ...nuevaLinea(), ...cambios });
const FORM = {
  tipo: 'sell_out',
  nombre: ' Tacticals BPS ',
  marcas: ['HP'],
  referencia: '',
  fechaDesde: '2026-11-01',
  fechaHasta: '2026-11-30',
  moneda: 'USD',
  tcModo: 'al_cobro',
  tipoCambio: '',
  incluyeIva: false,
  acumulable: true,
  nota: '',
};

describe('numeroDe reads an amount as typed in Argentina', () => {
  it.each([
    ['3,6', 3.6],
    ['1.500', 1500],
    ['3000,5', 3000.5],
    [' 850000 ', 850000],
  ])('%s -> %s', (texto, n) => expect(numeroDe(texto)).toBe(n));

  it.each(['', '  ', 'abc', '300u', '1,500,000', '-5'])('%j -> null', (texto) => expect(numeroDe(texto)).toBeNull());
});

describe('what a line can charge at most', () => {
  const tres = [201, 202, 203].map(producto);

  it('a total amount is itself; a percentage only its money cap', () => {
    expect(maximoACobrar(linea({ alcance: 'factura', modo: 'monto_total', monto: '850.000' }))).toBe(850000);
    expect(maximoACobrar(linea({ modo: 'porcentaje', monto: '3,6', topeMonto: '5000' }))).toBe(5000);
  });

  it('a cap that applies per store multiplies by its counters, a total never does', () => {
    expect(maximoACobrar(linea({ modo: 'porcentaje', monto: '3,6', topeMonto: '5000' }), 3)).toBe(15000);
    expect(maximoACobrar(linea({ alcance: 'factura', modo: 'monto_total', monto: '850.000' }), 3)).toBe(850000);
    expect(maximoTotal([linea({ modo: 'porcentaje', monto: '3,6', topeMonto: '5000' })], 2)).toBe(10000);
    expect(maximoACobrar(linea({ modo: 'porcentaje', monto: '3,6' }))).toBeNull();
  });

  it('per unit: amount x unit cap, per product unless shared, never above the money cap', () => {
    const porProducto = linea({ productos: tres, monto: '12', topeUnidades: '300' });
    expect(maximoACobrar(porProducto)).toBe(10800);
    expect(unidadesDelTope(porProducto)).toBe(900);
    const compartida = { ...porProducto, compartido: true };
    expect(maximoACobrar(compartida)).toBe(3600);
    expect(unidadesDelTope(compartida)).toBe(300);
    expect(maximoACobrar({ ...compartida, topeMonto: '3000' })).toBe(3000);
    expect(maximoTotal([porProducto, { ...compartida, topeMonto: '3000' }])).toBe(13800);
  });

  it('only several products can share a cap', () => {
    expect(puedeCompartir(linea({ productos: [producto(101)] }))).toBe(false);
    expect(puedeCompartir(linea({ productos: tres }))).toBe(true);
    expect(puedeCompartir(linea({ alcance: 'marca', productos: tres }))).toBe(false);
  });

  it('writes money as the design does', () => {
    expect(dinero('USD', 19800)).toBe('USD 19.800');
    expect(dinero('ARS', 850000.4)).toBe('$ 850.000');
  });
});

describe('scopes and amount kinds', () => {
  it('an invoice is charged as a total amount; leaving it goes back to per unit', () => {
    const factura = conAlcance(linea({ modo: 'porcentaje' }), 'factura');
    expect(factura.modo).toBe('monto_total');
    expect(conAlcance(factura, 'marca').modo).toBe('por_unidad');
  });

  it('on sell in a total amount over products, a brand or a category is ARS, or USD with a fixed rate (S4)', () => {
    expect(modosNoDisponibles('sell_in', 'productos', 'ARS')).toEqual([]);
    expect(modosNoDisponibles('sell_in', 'marca', 'USD', 'fijo')).toEqual([]);
    expect(modosNoDisponibles('sell_in', 'categoria', 'USD', 'al_cobro')).toEqual(['monto_total']);
    expect(modosNoDisponibles('sell_in', 'productos', 'USD', 'dia_venta')).toEqual(['monto_total']);
    // The invoice total line stays as it was: always a total, whatever the currency.
    expect(modosNoDisponibles('sell_in', 'factura', 'USD', 'al_cobro')).toEqual([]);
    expect(modosNoDisponibles('sell_out', 'productos', 'USD', 'al_cobro')).toEqual([]);
  });

  it('switching to sell out turns invoice lines into empty product lines and keeps a total amount of products', () => {
    const [a, b] = lineasPara('sell_out', [
      linea({ alcance: 'factura', modo: 'monto_total', facturas: [OPERACIONES[0]] }),
      linea({ alcance: 'marca', modo: 'monto_total', reparto: 'costo' }),
    ]);
    expect(a).toEqual(expect.objectContaining({ alcance: 'productos', modo: 'por_unidad', facturas: [] }));
    expect(b).toEqual(expect.objectContaining({ modo: 'monto_total', reparto: 'costo' }));
  });

  it('sell out offers a total amount on every scope, in any currency', () => {
    expect(modosDe('sell_out')).toEqual(['por_unidad', 'porcentaje', 'monto_total']);
    expect(modosNoDisponibles('sell_out', 'marca', 'ARS')).toEqual([]);
  });

  it('switching to sell in keeps a total amount of products with its split (S4)', () => {
    const [a, b] = lineasPara('sell_in', [
      linea({ alcance: 'productos', modo: 'monto_total', reparto: 'unidades' }),
      linea({ alcance: 'factura', modo: 'monto_total', facturas: [OPERACIONES[0]] }),
    ]);
    expect(a).toEqual(expect.objectContaining({ modo: 'monto_total', reparto: 'unidades' }));
    expect(b.modo).toBe('monto_total');
  });

  it('a sell out total amount keeps its kind across products, brand and category', () => {
    const total = linea({ modo: 'monto_total', reparto: 'iguales' });
    expect(conAlcance(total, 'marca')).toEqual(expect.objectContaining({ modo: 'monto_total', reparto: 'iguales' }));
    expect(conAlcance(conAlcance(total, 'marca'), 'categoria').modo).toBe('monto_total');
  });

  it('a copy is its own line with its own lists', () => {
    const original = linea({ productos: [producto(101)] });
    const copia = copiarLinea(original);
    expect(copia.id).not.toBe(original.id);
    copia.productos.push(producto(102));
    expect(original.productos).toHaveLength(1);
  });
});

describe('what stops a save, first thing only', () => {
  const lista = linea({ productos: [producto(101)], monto: '220' });

  it.each([
    [{ nombre: ' ' }, [lista], 'Poné un nombre para el tactical antes de crearlo.'],
    [{ marcas: [] }, [lista], 'Elegí la marca del tactical.'],
    [{ fechaHasta: '' }, [lista], 'Completá la vigencia del tactical.'],
    [{ fechaDesde: '2026-12-01' }, [lista], 'La fecha desde no puede ser posterior a la fecha hasta.'],
    [{ tcModo: 'fijo' }, [lista], 'Completá el tipo de cambio fijo.'],
    [{}, [], 'Agregá al menos una línea antes de crear el tactical.'],
    [{}, [linea({ monto: '1' }), linea({ monto: '1' })], 'Hay 2 líneas sin productos. Completalas o eliminalas.'],
    [{}, [linea({ alcance: 'marca', monto: '1' })], 'Hay 1 línea sin marca. Completala o eliminala.'],
    [{}, [{ ...lista, monto: '' }], 'Hay 1 línea sin monto. Completala o eliminala.'],
    [{}, [{ ...lista, modo: 'porcentaje', monto: '360' }], 'Hay 1 línea con un porcentaje mayor a 100. Corregila.'],
    [{}, [{ ...lista, topeMonto: '1,500,000' }], 'Hay 1 línea con un tope que no es un número. Corregila o borrá el tope.'],
    [{}, [{ ...lista, topeUnidades: '1,5' }], 'Hay 1 línea con un tope de unidades que no es entero. Corregila.'],
    [{}, [{ ...lista, modo: 'monto_total', monto: '1200' }], 'Hay 1 línea sin reparto del monto total. Completala o eliminala.'],
  ])('%j with %#', (cambios, lineas, mensaje) => expect(problemaDe({ ...FORM, ...cambios }, lineas)).toBe(mensaje));

  it('a sell in total over products in USD needs a fixed rate, as the backend says (S4)', () => {
    const total = { ...lista, modo: 'monto_total', monto: '1200', reparto: 'iguales' };
    const sellIn = { ...FORM, tipo: 'sell_in', moneda: 'USD' };
    expect(problemaDe({ ...sellIn, tcModo: 'al_cobro' }, [total])).toBe(
      'Hay 1 línea con un monto total en USD sin tipo de cambio fijo. Corregila o elegí tipo de cambio fijo.',
    );
    expect(problemaDe({ ...sellIn, tcModo: 'fijo', tipoCambio: '1000,5' }, [total])).toBeNull();
    expect(problemaDe({ ...sellIn, moneda: 'ARS' }, [total])).toBeNull();
  });

  it('nothing when it can be sent', () => {
    expect(problemaDe(FORM, [lista])).toBeNull();
    expect(problemaDe(FORM, [{ ...lista, modo: 'monto_total', monto: '1200', reparto: 'costo' }])).toBeNull();
  });
});

describe('the body of POST /tacticals (Contrato final)', () => {
  it('sends the store scope only once the engines honour it', () => {
    const lineas = [linea({ productos: [producto(101)], monto: '220' })];
    const form = { ...FORM, todasTiendas: false, topeCompartido: true, tiendaKeys: ['57997', 'fuera'] };

    expect(cuerpoDe(form, lineas, [], false).body).not.toHaveProperty('todas_tiendas');
    expect(cuerpoDe(form, lineas, [], false).body).not.toHaveProperty('tiendas');
    expect(cuerpoDe(form, lineas).body).toMatchObject({
      todas_tiendas: false,
      tope_compartido: true,
      tiendas: [
        { tipo: 'oficial', store_id: 57997 },
        { tipo: 'fuera', store_id: null },
      ],
    });
  });

  it('USD keeps tc_modo, and tipo_cambio only with a fixed rate', () => {
    const lineas = [linea({ productos: [producto(101)], monto: '220', topeUnidades: '90' })];
    const { body } = cuerpoDe(FORM, lineas);
    expect(body).toEqual({
      tipo: 'sell_out',
      nombre: 'Tacticals BPS',
      marcas: ['HP'],
      referencia: null,
      fecha_desde: '2026-11-01',
      fecha_hasta: '2026-11-30',
      moneda: 'USD',
      tc_modo: 'al_cobro',
      incluye_iva: false,
      acumulable: true,
      todas_tiendas: true,
      tope_compartido: false,
      tiendas: [],
      nota: null,
      lineas: [
        {
          alcance: 'productos',
          item_ids: [101],
          modo_monto: 'por_unidad',
          valor: 220,
          tope_unidades: 90,
          tope_monto: null,
          tope_por_producto: true,
        },
      ],
    });
    const fijo = cuerpoDe({ ...FORM, tcModo: 'fijo', tipoCambio: '1.450,5' }, lineas).body;
    expect(fijo).toEqual(expect.objectContaining({ tc_modo: 'fijo', tipo_cambio: 1450.5 }));
  });

  it('ARS sends no exchange-rate field; tope_por_producto only on products lines; one line per invoice', () => {
    const form = { ...FORM, tipo: 'sell_in', moneda: 'ARS' };
    const { body, origen } = cuerpoDe(form, [
      linea({ alcance: 'marca', marca: 'TP-Link', modo: 'porcentaje', monto: '3,6' }),
      linea({ alcance: 'factura', modo: 'monto_total', monto: '850000', facturas: OPERACIONES.slice(0, 2) }),
    ]);
    expect(body).not.toHaveProperty('tc_modo');
    expect(body).not.toHaveProperty('tipo_cambio');
    const sinTope = { tope_unidades: null, tope_monto: null };
    expect(body.lineas).toEqual([
      { alcance: 'marca', marca: 'TP-Link', modo_monto: 'porcentaje', valor: 3.6, ...sinTope },
      { alcance: 'factura', pedido_compra_id: 9001, modo_monto: 'monto_total', valor: 850000, ...sinTope },
      { alcance: 'factura', pedido_compra_id: 9002, modo_monto: 'monto_total', valor: 850000, ...sinTope },
    ]);
    expect(origen).toEqual([1, 2, 2]);
    expect(conLineaDeLaPantalla('Línea 3: la factura 9002 ya tiene un sell in.', origen)).toBe(
      'Línea 2: la factura 9002 ya tiene un sell in.',
    );
    expect(conLineaDeLaPantalla('La marca no existe.', origen)).toBe('La marca no existe.');
  });
});

describe('an invoice line on an operation with several invoices (varias facturas S3)', () => {
  const SELL_IN = { ...FORM, tipo: 'sell_in', moneda: 'ARS' };
  const sinTope = { tope_unidades: null, tope_monto: null };
  const [conDos, otra] = OPERACIONES;

  it('applies to every invoice by default: the body line sends no facturas_ct', () => {
    const factura = linea({ alcance: 'factura', modo: 'monto_total', monto: '850000', facturas: [conDos] });
    const [cuerpo] = cuerpoDe(SELL_IN, [factura]).body.lineas;
    expect(cuerpo).toEqual({ alcance: 'factura', pedido_compra_id: 9001, modo_monto: 'monto_total', valor: 850000, ...sinTope });
    expect(cuerpo).not.toHaveProperty('facturas_ct');
  });

  it("picking one invoice sends facturas_ct on that operation's body line only", () => {
    const elegida = { ...conDos, facturasCt: [70002] };
    const factura = linea({ alcance: 'factura', modo: 'porcentaje', monto: '5', facturas: [elegida, otra] });
    expect(cuerpoDe(SELL_IN, [factura]).body.lineas).toEqual([
      { alcance: 'factura', pedido_compra_id: 9001, facturas_ct: [70002], modo_monto: 'porcentaje', valor: 5, ...sinTope },
      { alcance: 'factura', pedido_compra_id: 9002, modo_monto: 'porcentaje', valor: 5, ...sinTope },
    ]);
  });

  it('a pick goes back to all invoices when its last invoice is unchecked, never an empty list', () => {
    expect(alternarFactura(null, 70002)).toEqual([70002]);
    expect(alternarFactura([70002], 70001)).toEqual([70002, 70001]);
    expect(alternarFactura([70002, 70001], 70002)).toEqual([70001]);
    expect(alternarFactura([70001], 70001)).toBeNull();
    const vacia = linea({ alcance: 'factura', modo: 'porcentaje', monto: '5', facturas: [{ ...conDos, facturasCt: [] }] });
    expect(cuerpoDe(SELL_IN, [vacia]).body.lineas[0]).not.toHaveProperty('facturas_ct');
  });

  it('a products line body is unchanged', () => {
    const productos = linea({ productos: [producto(201)], monto: '10', topeUnidades: '5' });
    expect(cuerpoDe(SELL_IN, [productos]).body.lineas).toEqual([
      { alcance: 'productos', item_ids: [201], modo_monto: 'por_unidad', valor: 10, tope_unidades: 5, tope_monto: null, tope_por_producto: true },
    ]);
  });
});

describe('a sell out total amount split among the line\'s products (S1)', () => {
  const notebooks = [103, 104].map(producto);

  it.each(['iguales', 'unidades', 'costo'])('%s: the total, its split criterion, and no caps', (reparto) => {
    const lineas = [
      linea({ productos: notebooks, modo: 'monto_total', monto: '1.200', reparto, topeUnidades: '90', topeMonto: '5000' }),
      linea({ alcance: 'marca', marca: 'HP', modo: 'monto_total', monto: '300', reparto }),
    ];
    expect(cuerpoDe(FORM, lineas).body.lineas).toEqual([
      { alcance: 'productos', item_ids: [103, 104], modo_monto: 'monto_total', valor: 1200, tope_unidades: null, tope_monto: null, reparto_criterio: reparto },
      { alcance: 'marca', marca: 'HP', modo_monto: 'monto_total', valor: 300, tope_unidades: null, tope_monto: null, reparto_criterio: reparto },
    ]);
    expect(maximoACobrar(lineas[0])).toBe(1200);
    expect(unidadesDelTope(lineas[0])).toBe(0);
  });

  it('per unit and % lines send no split criterion, as before', () => {
    const { body } = cuerpoDe(FORM, [
      linea({ productos: notebooks, monto: '12', topeUnidades: '300', reparto: 'costo' }),
      linea({ alcance: 'categoria', categoria: 'Notebooks', modo: 'porcentaje', monto: '3,5', topeMonto: '5000' }),
    ]);
    expect(body.lineas).toEqual([
      { alcance: 'productos', item_ids: [103, 104], modo_monto: 'por_unidad', valor: 12, tope_unidades: 300, tope_monto: null, tope_por_producto: true },
      { alcance: 'categoria', categoria: 'Notebooks', modo_monto: 'porcentaje', valor: 3.5, tope_unidades: null, tope_monto: 5000 },
    ]);
  });
});

describe('a sell in total amount split among the line\'s products (S4)', () => {
  const notebooks = [103, 104].map(producto);
  const SELL_IN = { ...FORM, tipo: 'sell_in', moneda: 'ARS' };

  it.each(['iguales', 'unidades', 'costo'])('%s: products, brand and category send the total and its criterion, no caps', (reparto) => {
    const total = { modo: 'monto_total', reparto };
    const lineas = [
      linea({ productos: notebooks, monto: '1.200.000', topeUnidades: '90', ...total }),
      linea({ alcance: 'marca', marca: 'HP', monto: '300000', ...total }),
      linea({ alcance: 'categoria', categoria: 'Notebooks', monto: '50000', ...total }),
    ];
    const sinTope = { modo_monto: 'monto_total', tope_unidades: null, tope_monto: null, reparto_criterio: reparto };
    expect(cuerpoDe(SELL_IN, lineas).body.lineas).toEqual([
      { alcance: 'productos', item_ids: [103, 104], valor: 1200000, ...sinTope },
      { alcance: 'marca', marca: 'HP', valor: 300000, ...sinTope },
      { alcance: 'categoria', categoria: 'Notebooks', valor: 50000, ...sinTope },
    ]);
  });

  it('the invoice total line sends no criterion, as before', () => {
    const factura = linea({ alcance: 'factura', modo: 'monto_total', monto: '850000', facturas: OPERACIONES.slice(0, 1), reparto: 'costo' });
    expect(cuerpoDe(SELL_IN, [factura]).body.lineas).toEqual([
      { alcance: 'factura', pedido_compra_id: 9001, modo_monto: 'monto_total', valor: 850000, tope_unidades: null, tope_monto: null },
    ]);
    expect(problemaDe(SELL_IN, [{ ...factura, reparto: '' }])).toBeNull();
  });
});

describe('a tactical whose lines are all invoice lines (factura sin fecha S2c)', () => {
  const SELL_IN = { ...FORM, tipo: 'sell_in', moneda: 'ARS', fechaDesde: '', fechaHasta: '' };
  const factura = linea({ alcance: 'factura', modo: 'porcentaje', monto: '5', facturas: [OPERACIONES[0]] });
  const marca = linea({ alcance: 'marca', marca: 'HP', modo: 'porcentaje', monto: '3' });

  it('is por factura only on sell in with every line by invoice', () => {
    expect(porFactura(SELL_IN, [factura])).toBe(true);
    expect(porFactura(SELL_IN, [factura, marca])).toBe(false);
    expect(porFactura(SELL_IN, [])).toBe(false);
    expect(porFactura({ ...SELL_IN, tipo: 'sell_out' }, [factura])).toBe(false);
  });

  it('asks no dates and sends none; a mixed one still needs them', () => {
    expect(problemaDe(SELL_IN, [factura])).toBeNull();
    expect(cuerpoDe(SELL_IN, [factura]).body).toMatchObject({ fecha_desde: null, fecha_hasta: null });
    expect(cuerpoDe({ ...SELL_IN, fechaDesde: '2026-11-01', fechaHasta: '2026-11-30' }, [factura]).body).toMatchObject({
      fecha_desde: null,
      fecha_hasta: null,
    });
    expect(problemaDe(SELL_IN, [factura, marca])).toBe('Completá la vigencia del tactical.');
  });
});

describe('a brand line narrowed to one category (SISO S3: "los routers solo de tp-link")', () => {
  const sinTope = { tope_unidades: null, tope_monto: null };

  it('sends the category with the brand, and none when it is empty', () => {
    const { body } = cuerpoDe({ ...FORM, tipo: 'sell_in', moneda: 'ARS' }, [
      linea({ alcance: 'marca', marca: 'TP-Link', categoria: 'Routers', modo: 'porcentaje', monto: '3' }),
      linea({ alcance: 'marca', marca: 'HP', categoria: 'Routers', modo: 'monto_total', monto: '300', reparto: 'iguales' }),
      linea({ alcance: 'marca', marca: 'HP', modo: 'porcentaje', monto: '3' }),
    ]);
    expect(body.lineas).toEqual([
      { alcance: 'marca', marca: 'TP-Link', categoria: 'Routers', modo_monto: 'porcentaje', valor: 3, ...sinTope },
      { alcance: 'marca', marca: 'HP', categoria: 'Routers', modo_monto: 'monto_total', valor: 300, ...sinTope,
        reparto_criterio: 'iguales' },
      { alcance: 'marca', marca: 'HP', modo_monto: 'porcentaje', valor: 3, ...sinTope },
    ]);
  });

  it('switching to or from a brand line clears the category', () => {
    expect(conAlcance(linea({ alcance: 'categoria', categoria: 'Routers' }), 'marca').categoria).toBe('');
    expect(conAlcance(linea({ alcance: 'marca', marca: 'HP', categoria: 'Routers' }), 'categoria').categoria).toBe('');
    expect(conAlcance(linea({ alcance: 'marca', categoria: 'Routers' }), 'marca').categoria).toBe('Routers');
  });
});
