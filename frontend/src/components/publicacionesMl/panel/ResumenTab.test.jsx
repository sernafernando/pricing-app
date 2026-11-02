/**
 * Resumen tab (publicaciones-ml-vista P13a.T2): every field of the publication,
 * the price with its source, the stock by place, and -- for `ver_ganancia`
 * only -- how the markup is made up. A value the backend does not have is "—",
 * never 0 and never blank.
 */
import { describe, it, expect } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import ResumenTab from './ResumenTab';
import { readDetail } from './detailModel';
import {
  DETAIL_RESPONSE,
  DETAIL_RESPONSE_MARGIN,
  EXTRA_FIELDS,
  ITEMS,
  ITEM_COLUMNS,
  makeDetail,
  makeItem,
} from '../../../test/visual/publicacionesMlFixtures';

const renderTab = (raw = DETAIL_RESPONSE, { canSeeMargin = false } = {}) => {
  const detail = readDetail(raw, { canSeeMargin });
  return render(<ResumenTab detail={detail} itemId={detail.itemId} canSeeMargin={canSeeMargin} />);
};
const section = (name) => screen.getByRole('region', { name });
/** The value cell next to the label `label` inside a section. */
const valueOf = (name, label) => {
  const term = within(section(name)).getByText(label, { selector: 'dt' });
  return term.nextElementSibling;
};
const DASH = '—';

const DATOS = 'Datos de la publicación';
const attention = () => screen.queryByRole('region', { name: 'Atención' });
const attentionItems = () => within(attention()).getAllByRole('listitem').map((li) => li.textContent);

describe('the order of the Resumen (S4)', () => {
  it('reads attention, Rentabilidad, Stock beside Producto vinculado, then the quiet data', () => {
    renderTab(makeDetail({ ...DETAIL_RESPONSE_MARGIN, sub_status: ['out_of_stock'] }), { canSeeMargin: true });
    const titles = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
    expect(titles.slice(0, 5)).toEqual(['Atención', 'Rentabilidad', 'Stock', 'Producto vinculado', DATOS]);
    // Stock and Producto vinculado share one row.
    expect(section('Stock').parentElement).toBe(section('Producto vinculado').parentElement);
  });

  it('without ver_ganancia there is no Rentabilidad: the price stays in the header, not here', () => {
    renderTab(DETAIL_RESPONSE_MARGIN, { canSeeMargin: false });
    expect(screen.queryByRole('region', { name: 'Rentabilidad' })).not.toBeInTheDocument();
    expect(screen.queryByText('Precio limpio')).not.toBeInTheDocument();
    expect(screen.queryByText('98.500,50')).not.toBeInTheDocument();
  });

  it('does not repeat the header: no status, no price amount, no total stock in the body', () => {
    renderTab();
    expect(within(section(DATOS)).queryByText('Estado', { selector: 'dt' })).not.toBeInTheDocument();
    expect(within(section(DATOS)).queryByText('Subestado', { selector: 'dt' })).not.toBeInTheDocument();
    expect(within(section('Stock')).queryByText('Disponible', { selector: 'dt' })).not.toBeInTheDocument();
    expect(screen.queryByText('98.500,50')).not.toBeInTheDocument();
  });
});

describe('the attention row (real signals only)', () => {
  it('is not there when nothing needs attention', () => {
    renderTab();
    expect(attention()).not.toBeInTheDocument();
  });

  it("lists ML's sub-status, its last error and a publication that vanished from ML, with the date", () => {
    renderTab(
      makeDetail({
        row: makeItem({ ...ITEMS[3] }),
        sub_status: ['out_of_stock'],
        item: { ...ITEM_COLUMNS, last_error: 'HTTP 500' },
      }),
    );
    const items = attentionItems();
    expect(items.some((text) => /Eliminada de Mercado Libre el \d{2}\/\d{2}\/\d{4}/.test(text))).toBe(true);
    expect(items).toContain('Subestado de Mercado Libre: out_of_stock');
    expect(items).toContain('Último error de Mercado Libre: HTTP 500');
  });

  it('flags a link in conflict and a publication without a product', () => {
    renderTab(makeDetail({ row: makeItem({ ...ITEMS[0], link: { ...ITEMS[0].link, state: 'conflicto' } }) }));
    expect(attentionItems()).toEqual(['El vínculo con el producto está en conflicto']);
    cleanup();
    renderTab(makeDetail({ row: ITEMS[3] }));
    expect(attentionItems()).toContain('Sin producto vinculado');
  });

  it('an unknown link is not a signal: only a link ML says has no product is', () => {
    renderTab(makeDetail({ row: makeItem({ ...ITEMS[0], link: null }) }));
    expect(attention()).not.toBeInTheDocument();
    expect(valueOf('Producto vinculado', 'Estado')).toHaveTextContent(DASH);
  });

  it('flags a negative markup only to who may see it', () => {
    const row = makeItem({ ...ITEMS[0], markup: { min: -3, max: -3, worst: -3, any_negative: true, reason: 'ok', partial: 0 } });
    renderTab(makeDetail({ row }), { canSeeMargin: true });
    expect(attentionItems()).toEqual(['Markup negativo']);
    cleanup();
    renderTab(makeDetail({ row }), { canSeeMargin: false });
    expect(attention()).not.toBeInTheDocument();
  });
});

describe('the data of the publication', () => {
  it('says what it is: condition, type, catalog, logistics', () => {
    renderTab();
    expect(valueOf(DATOS, 'Condición')).toHaveTextContent('Nueva');
    expect(valueOf(DATOS, 'Tipo')).toHaveTextContent('Premium');
    expect(valueOf(DATOS, 'Catálogo')).toHaveTextContent('No');
    expect(valueOf(DATOS, 'Logística')).toHaveTextContent('Full');
  });

  it('names the store, brand, family and user product', () => {
    renderTab(makeDetail({ row: makeItem({ ...ITEMS[0], user_product_id: 'MLAU100001' }) }));
    expect(valueOf(DATOS, 'Tienda')).toHaveTextContent('TP-Link');
    expect(valueOf(DATOS, 'Marca')).toHaveTextContent('TP-Link');
    expect(valueOf(DATOS, 'Familia')).toHaveTextContent('Archer AX55');
    expect(valueOf(DATOS, 'Producto de usuario')).toHaveTextContent('MLAU100001');
  });

  it('shows health as a percentage, the tags, and the three dates', () => {
    renderTab();
    expect(valueOf(DATOS, 'Salud')).toHaveTextContent('87,0%');
    const tags = valueOf(DATOS, 'Etiquetas');
    expect(within(tags).getByText('good_quality_picture')).toBeInTheDocument();
    expect(within(tags).getByText('immediate_payment')).toBeInTheDocument();
    for (const label of ['Creada', 'Modificada en ML', 'Sincronizada']) {
      expect(valueOf(DATOS, label).textContent).toMatch(/\d{2}\/\d{2}\/\d{4}/);
    }
  });

  it('counts the variations', () => {
    renderTab(makeDetail({ row: makeItem({ ...ITEMS[0], variations_count: 3 }) }));
    expect(valueOf(DATOS, 'Variaciones')).toHaveTextContent('3');
  });

  it('shows where the price comes from, the regular price and the promotion', () => {
    renderTab();
    expect(valueOf(DATOS, 'Origen del precio')).toHaveTextContent('Precio de oferta');
    expect(valueOf(DATOS, 'Precio regular')).toHaveTextContent('112.000,00');
    expect(valueOf(DATOS, 'Promoción')).toHaveTextContent('DEAL');
    expect(valueOf(DATOS, 'Promoción')).toHaveTextContent('Hot Sale');
  });

  it('labels the price that comes from Productos as such', () => {
    renderTab(makeDetail({ row: ITEMS[1] }));
    expect(valueOf(DATOS, 'Origen del precio')).toHaveTextContent('Precio de Productos');
    expect(valueOf(DATOS, 'Promoción')).toHaveTextContent(DASH);
  });

  it('every field the backend does not have reads "—", never 0 or blank (S4.1)', () => {
    renderTab(
      makeDetail({
        row: ITEMS[2],
        tags: [],
        health: null,
        condition: null,
        date_created: null,
        ml_last_updated: null,
        fetched_at: null,
        stock_locations: null,
        stock_as_of: null,
        replenishment: null,
      }),
    );
    for (const label of ['Condición', 'Tienda', 'Marca', 'Familia', 'Producto de usuario', 'Salud', 'Etiquetas', 'Creada', 'Modificada en ML', 'Sincronizada', 'Origen del precio', 'Precio regular', 'Promoción']) {
      expect(valueOf(DATOS, label)).toHaveTextContent(DASH);
    }
    expect(within(section(DATOS)).queryByText('0')).not.toBeInTheDocument();
  });
});

describe('the stock (the breakdown; the total is in the header)', () => {
  it('shows Full and Propio, the places they come from, the ERP stock and when it was read', () => {
    renderTab(makeDetail({ row: makeItem({ ...ITEMS[0], erp_stock: { quantity: 18 } }) }));
    expect(valueOf('Stock', 'Full')).toHaveTextContent('20');
    expect(valueOf('Stock', 'Propio')).toHaveTextContent('14');
    expect(valueOf('Stock', 'Depósito de Mercado Libre')).toHaveTextContent('20');
    expect(valueOf('Stock', 'Dirección del vendedor')).toHaveTextContent('14');
    expect(valueOf('Stock', 'Stock ERP')).toHaveTextContent('18');
    expect(valueOf('Stock', 'Actualizado').textContent).toMatch(/\d{2}\/\d{2}\/\d{4}/);
  });

  it('a place type the screen does not know keeps its own name', () => {
    renderTab(makeDetail({ stock_locations: [{ type: 'warehouse_x', quantity: 3 }] }));
    expect(valueOf('Stock', 'warehouse_x')).toHaveTextContent('3');
  });

  it('a real 0 is shown as 0; an unknown figure is "—"', () => {
    renderTab(makeDetail({ row: makeItem({ ...ITEMS[0], stock: { available: 0, full: null, own: 0, as_of: null } }), stock_locations: null }));
    expect(valueOf('Stock', 'Full')).toHaveTextContent(DASH);
    expect(valueOf('Stock', 'Propio')).toHaveTextContent('0');
    expect(valueOf('Stock', 'Stock ERP')).toHaveTextContent(DASH);
    expect(within(section('Stock')).queryByText('Depósito de Mercado Libre')).not.toBeInTheDocument();
  });
});

describe('the linked product', () => {
  it('shows the state and the product it points to', () => {
    renderTab();
    expect(valueOf('Producto vinculado', 'Estado')).toHaveTextContent('Automático');
    expect(valueOf('Producto vinculado', 'Código')).toHaveTextContent('ARCHER-AX55');
    expect(valueOf('Producto vinculado', 'Producto')).toHaveTextContent('Router Archer AX55');
  });

  it('an unlinked publication says so', () => {
    renderTab(makeDetail({ row: ITEMS[3] }));
    expect(valueOf('Producto vinculado', 'Estado')).toHaveTextContent('Sin producto');
    expect(valueOf('Producto vinculado', 'Código')).toHaveTextContent(DASH);
  });
});

describe('Rentabilidad (ver_ganancia only): from the price down to the markup', () => {
  it('reads as a sum, Precio first and Markup last, then what it was computed on', () => {
    renderTab(DETAIL_RESPONSE_MARGIN, { canSeeMargin: true });
    const terms = [...section('Rentabilidad').querySelectorAll('dl')[0].querySelectorAll('dt')].map((dt) => dt.textContent);
    expect(terms).toEqual(['Precio', 'Comisión', 'Costo de envío', 'Precio limpio', 'Costo', 'Markup']);
    expect(valueOf('Rentabilidad', 'Precio')).toHaveTextContent('98.500,50');
    expect(valueOf('Rentabilidad', 'Comisión')).toHaveTextContent('13.297,57');
    expect(valueOf('Rentabilidad', 'Comisión')).toHaveTextContent('13,5%');
    expect(valueOf('Rentabilidad', 'Costo de envío')).toHaveTextContent('4.200,00');
    expect(valueOf('Rentabilidad', 'Costo de envío')).toHaveTextContent('ERP');
    expect(valueOf('Rentabilidad', 'Precio limpio')).toHaveTextContent('81.002,93');
    expect(valueOf('Rentabilidad', 'Costo')).toHaveTextContent('64.000,00');
    expect(valueOf('Rentabilidad', 'Markup')).toHaveTextContent('26,5%');
    expect(valueOf('Rentabilidad', 'Unidad calculada')).toHaveTextContent('La publicación');
    expect(valueOf('Rentabilidad', 'Cuotas')).toHaveTextContent('6');
    expect(valueOf('Rentabilidad', 'Lista de precios')).toHaveTextContent('12');
  });

  it('names where the computed price comes from when it is not the publication price shown in the data', () => {
    renderTab(makeDetail({ markup_breakdown: { ...DETAIL_RESPONSE_MARGIN.markup_breakdown, price_source: 'item_price', variation_id: 77 } }), {
      canSeeMargin: true,
    });
    expect(valueOf('Rentabilidad', 'Precio')).toHaveTextContent('Precio de la publicación');
    cleanup();
    renderTab(DETAIL_RESPONSE_MARGIN, { canSeeMargin: true });
    expect(valueOf('Rentabilidad', 'Precio')).not.toHaveTextContent('Precio de oferta');
  });

  it('a partial breakdown keeps the percentage and the shipping source it has', () => {
    renderTab(
      makeDetail({ markup_breakdown: { ...DETAIL_RESPONSE_MARGIN.markup_breakdown, comision_total: null, costo_envio: null } }),
      { canSeeMargin: true },
    );
    expect(valueOf('Rentabilidad', 'Comisión')).toHaveTextContent('13,5%');
    expect(valueOf('Rentabilidad', 'Costo de envío')).toHaveTextContent('ERP');
  });

  it('a breakdown figure with neither its amount nor its aside reads "—"', () => {
    renderTab(
      makeDetail({
        markup_breakdown: { ...DETAIL_RESPONSE_MARGIN.markup_breakdown, comision_total: null, comision_pct: null, costo_envio: null, envio_source: null, price: null },
      }),
      { canSeeMargin: true },
    );
    for (const name of ['Precio', 'Comisión', 'Costo de envío']) expect(valueOf('Rentabilidad', name)).toHaveTextContent(DASH);
  });

  it('a negative markup is flagged', () => {
    renderTab(makeDetail({ markup_breakdown: { ...DETAIL_RESPONSE_MARGIN.markup_breakdown, markup: -3.2 } }), { canSeeMargin: true });
    expect(valueOf('Rentabilidad', 'Markup')).toHaveTextContent('-3,2%');
    expect(valueOf('Rentabilidad', 'Markup').querySelector('[data-negative]')).not.toBeNull();
  });

  it('with the permission but no breakdown (not linked, no cost) it says there is none', () => {
    renderTab(makeDetail(), { canSeeMargin: true });
    expect(within(section('Rentabilidad')).getByText(/No se pudo calcular el markup/)).toBeInTheDocument();
  });
});

describe('the markup with sell in / sell out (ver_ganancia only)', () => {
  const SELL_IN = { compra_item_id: 7, descuento_unit: 1500, costo: 62500, unidades_restantes: 12 };
  const withSellInOut = (sellInOut) => makeDetail({ markup_breakdown: DETAIL_RESPONSE_MARGIN.markup_breakdown, sell_in_out: sellInOut });

  it('shows the cost with sell in, its discount and lot in the tooltip, and the markup with sell in', () => {
    renderTab(withSellInOut({ sell_in: SELL_IN, sell_out: null, markups_sell_in: { publicacion: 29.6 }, markups_sell_in_out: {} }), { canSeeMargin: true });
    expect(valueOf('Rentabilidad', 'Costo')).toHaveTextContent('64.000,00');
    expect(valueOf('Rentabilidad', 'Markup')).toHaveTextContent('26,5%');
    const costo = valueOf('Rentabilidad', 'Costo c/ sell in');
    expect(costo).toHaveTextContent('62.500,00');
    const tooltip = costo.querySelector('[title]').getAttribute('title');
    expect(tooltip).toContain('1.500,00');
    expect(tooltip).toContain('12');
    const markup = valueOf('Rentabilidad', 'Markup c/ sell in/out');
    expect(markup).toHaveTextContent('29,6%');
    expect(markup.querySelector('[title]').getAttribute('title')).toBe('Con sell in');
  });

  it('names the % of cost bonus in the tooltip when the sell in has no lot (T25c)', () => {
    const bono = { ...SELL_IN, compra_item_id: null, bono_id: 4, unidades_restantes: null };
    renderTab(withSellInOut({ sell_in: bono, sell_out: null, markups_sell_in: {}, markups_sell_in_out: {} }), { canSeeMargin: true });
    const tooltip = valueOf('Rentabilidad', 'Costo c/ sell in').querySelector('[title]').getAttribute('title');
    expect(tooltip).toBe('Descuento por unidad: $ 1.500,00\nBono #4 sobre el costo');
  });

  it('with sell out the markup is the one with sell in and sell out', () => {
    renderTab(
      withSellInOut({
        sell_in: SELL_IN,
        sell_out: { monto_unit: 2000, campana_ids: [3] },
        markups_sell_in: { publicacion: 29.6 },
        markups_sell_in_out: { publicacion: -2.4 },
      }),
      { canSeeMargin: true },
    );
    const markup = valueOf('Rentabilidad', 'Markup c/ sell in/out');
    expect(markup).toHaveTextContent('-2,4%');
    expect(markup.querySelector('[data-negative]')).not.toBeNull();
    expect(markup.querySelector('[title]').getAttribute('title')).toContain('Con sell in y sell out');
  });

  it('an unknown amount reads "Pendiente", never a number', () => {
    renderTab(
      withSellInOut({ sell_in: null, sell_out: { monto_unit: null, campana_ids: [3] }, markups_sell_in: {}, markups_sell_in_out: {} }),
      { canSeeMargin: true },
    );
    expect(valueOf('Rentabilidad', 'Markup c/ sell in/out')).toHaveTextContent('Pendiente');
    expect(valueOf('Rentabilidad', 'Markup c/ sell in/out')).not.toHaveTextContent('%');
  });

  it('a lot without a cost in pesos says "Sin tipo de cambio" and its markup is pending', () => {
    renderTab(
      withSellInOut({ sell_in: { ...SELL_IN, costo: null }, sell_out: null, markups_sell_in: {}, markups_sell_in_out: {} }),
      { canSeeMargin: true },
    );
    expect(valueOf('Rentabilidad', 'Costo c/ sell in')).toHaveTextContent('Sin tipo de cambio');
    expect(valueOf('Rentabilidad', 'Markup c/ sell in/out')).toHaveTextContent('Pendiente');
  });

  it('without sell in nor sell out nothing new is shown', () => {
    renderTab(withSellInOut(null), { canSeeMargin: true });
    expect(screen.queryByText('Costo c/ sell in')).not.toBeInTheDocument();
    expect(screen.queryByText('Markup c/ sell in/out')).not.toBeInTheDocument();
  });

  it('without the permission it is not shown, even if the payload carried it', () => {
    renderTab(withSellInOut({ sell_in: SELL_IN, sell_out: null, markups_sell_in: { publicacion: 29.6 }, markups_sell_in_out: {} }));
    expect(screen.queryByText('Costo c/ sell in')).not.toBeInTheDocument();
  });
});

describe('the data of Mercado Libre (every ml_items column worth reading)', () => {
  const NAME = 'Datos de Mercado Libre';

  it('names the category, domain, seller, catalog product and currency', () => {
    renderTab();
    expect(valueOf(NAME, 'Categoría')).toHaveTextContent('MLA1648');
    expect(valueOf(NAME, 'Dominio')).toHaveTextContent('MLA-ROUTERS');
    expect(valueOf(NAME, 'Vendedor')).toHaveTextContent('123456789');
    expect(valueOf(NAME, 'Producto de catálogo')).toHaveTextContent('MLA19000001');
    expect(valueOf(NAME, 'Modo de compra')).toHaveTextContent('buy_it_now');
    expect(valueOf(NAME, 'Moneda')).toHaveTextContent('ARS');
  });

  it('shows the seller\'s own codes, the base price and the quantities', () => {
    renderTab();
    expect(valueOf(NAME, 'SKU del vendedor')).toHaveTextContent('AX55-SKU');
    expect(valueOf(NAME, 'Campo personalizado')).toHaveTextContent('ARCHER-AX55');
    expect(valueOf(NAME, 'Precio base')).toHaveTextContent('112.000,00');
    expect(valueOf(NAME, 'Cantidad inicial')).toHaveTextContent('200');
    expect(valueOf(NAME, 'Vendidas')).toHaveTextContent('120');
    expect(valueOf(NAME, 'Inventario')).toHaveTextContent('ABCD1234');
  });

  it('shows the shipping mode, free shipping and the publication dates', () => {
    renderTab();
    expect(valueOf(NAME, 'Modo de envío')).toHaveTextContent('me2');
    expect(valueOf(NAME, 'Envío gratis')).toHaveTextContent('Sí');
    expect(valueOf(NAME, 'Inicio').textContent).toMatch(/\d{2}\/\d{2}\/\d{4}/);
    expect(valueOf(NAME, 'Finalizada')).toHaveTextContent('—');
  });

  it('leaves the last error to the attention row', () => {
    renderTab(makeDetail({ item: { ...ITEM_COLUMNS, last_error: 'HTTP 500' } }));
    expect(within(section(NAME)).queryByText('Último error', { selector: 'dt' })).not.toBeInTheDocument();
  });

  it('a column the store does not have reads "—", and a real false reads "No", never blank', () => {
    renderTab(makeDetail({ item: { ...ITEM_COLUMNS, category_id: null, seller_sku: null, free_shipping: false, initial_quantity: 0 } }));
    expect(valueOf(NAME, 'Categoría')).toHaveTextContent('—');
    expect(valueOf(NAME, 'SKU del vendedor')).toHaveTextContent('—');
    expect(valueOf(NAME, 'Envío gratis')).toHaveTextContent('No');
    expect(valueOf(NAME, 'Cantidad inicial')).toHaveTextContent('0');
  });

  it('tolerates a detail without the item block', () => {
    renderTab(makeDetail({ item: undefined, extra: undefined }));
    expect(valueOf(NAME, 'Categoría')).toHaveTextContent('—');
  });
});

describe('the body of the publication (the whitelisted extra)', () => {
  const NAME = 'Características';

  it('shows the warranty, the options and the channels', () => {
    renderTab();
    expect(valueOf(NAME, 'Garantía')).toHaveTextContent('Garantía del vendedor: 6 meses');
    expect(valueOf(NAME, 'Republicación automática')).toHaveTextContent('No');
    expect(valueOf(NAME, 'Acepta Mercado Pago')).toHaveTextContent('Sí');
    expect(valueOf(NAME, 'Entrega internacional')).toHaveTextContent('none');
    expect(valueOf(NAME, 'Canales')).toHaveTextContent('marketplace');
    expect(valueOf(NAME, 'Canales')).toHaveTextContent('mshops');
    expect(valueOf(NAME, 'Ofertas')).toHaveTextContent('MLA12345');
  });

  it('shows the shipping, not the seller address (the seller is the company itself)', () => {
    renderTab();
    expect(valueOf(NAME, 'Retiro en persona')).toHaveTextContent('No');
    expect(valueOf(NAME, 'Retiro en tienda')).toHaveTextContent('No');
    expect(valueOf(NAME, 'Etiquetas de envío')).toHaveTextContent('self_service_in');
    expect(within(section(NAME)).queryByText('Ciudad')).not.toBeInTheDocument();
    expect(within(section(NAME)).queryByText('Provincia')).not.toBeInTheDocument();
  });

  it('lists the sale terms, the attributes and the item relations', () => {
    renderTab();
    expect(valueOf(NAME, 'Condiciones de venta')).toHaveTextContent('Tiempo de garantía: 6 meses');
    expect(valueOf(NAME, 'Condiciones de venta')).toHaveTextContent('Cuotas: 6x_campaign');
    expect(valueOf(NAME, 'Atributos')).toHaveTextContent('Marca: TP-Link');
    expect(valueOf(NAME, 'Atributos')).toHaveTextContent('Modelo: Archer AX55');
    expect(valueOf(NAME, 'Relaciones')).toHaveTextContent('MLA1100000009');
  });

  it('links every picture, and only over https', () => {
    renderTab(
      makeDetail({
        extra: { ...EXTRA_FIELDS, pictures: [...EXTRA_FIELDS.pictures, { id: '3-MLA', secure_url: 'javascript:alert(1)', size: null, max_size: null }] },
      }),
    );
    const pictures = valueOf(NAME, 'Imágenes');
    const links = within(pictures).getAllByRole('link');
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAttribute('href', 'https://http2.mlstatic.com/D_111-O.jpg');
    expect(links[0]).toHaveAttribute('rel', expect.stringContaining('noopener'));
    expect(pictures).toHaveTextContent('2 imágenes (1 sin enlace)');
  });

  it('a body the store does not have reads "—" everywhere', () => {
    const empty = Object.fromEntries(Object.keys(EXTRA_FIELDS).map((key) => [key, null]));
    renderTab(makeDetail({ extra: empty }));
    for (const label of ['Garantía', 'Republicación automática', 'Acepta Mercado Pago', 'Canales', 'Ofertas', 'Retiro en persona', 'Etiquetas de envío', 'Condiciones de venta', 'Atributos', 'Imágenes', 'Relaciones']) {
      expect(valueOf(NAME, label)).toHaveTextContent('—');
    }
  });

  it('an empty list is "—" too, not an empty cell', () => {
    renderTab(makeDetail({ extra: { ...EXTRA_FIELDS, channels: [], attributes: [] } }));
    expect(valueOf(NAME, 'Canales')).toHaveTextContent('—');
    expect(valueOf(NAME, 'Atributos')).toHaveTextContent('—');
  });

  it('differential pricing is shown as what it is, whatever its shape', () => {
    renderTab(makeDetail({ extra: { ...EXTRA_FIELDS, differential_pricing: { id: 7 } } }));
    expect(valueOf(NAME, 'Precio diferencial')).toHaveTextContent('{"id":7}');
  });
});
