/**
 * Resumen tab (S4, laid out in S5): what needs attention, the Rentabilidad waterfall (ver_ganancia only), the stock
 * card beside the linked product, the Ficha in three groups, then Mercado Libre's own data collapsed. Each datum once,
 * none lost; in the Ficha a value the backend does not have is "—", never 0 and never blank; inside the collapsed ML
 * block an empty field is left out.
 */
import { describe, it, expect } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
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

const renderTab = (raw = DETAIL_RESPONSE, { canSeeMargin = false, canViewPromos = false } = {}) => {
  const detail = readDetail(raw, { canSeeMargin });
  return render(<ResumenTab detail={detail} itemId={detail.itemId} canSeeMargin={canSeeMargin} canViewPromos={canViewPromos} />);
};
const section = (name) => screen.getByRole('region', { name });
/** The value cell next to the label `label` inside a section. */
const valueOf = (name, label) => {
  const term = within(section(name)).getByText(label, { selector: 'dt' });
  return term.nextElementSibling;
};
const DASH = '—';
/** A whole Rentabilidad step: its label with its aside (the %, the shipping source), and its amount. */
const stepOf = (label) => valueOf('Rentabilidad', label).parentElement;

const DATOS = 'Ficha de la publicación';
const MORE_ML = 'Más datos de Mercado Libre';
/** Opens the collapsed ML block (closed by default, S5). */
const openMoreMl = () => fireEvent.click(screen.getByRole('button', { name: /Más datos de Mercado Libre/ }));
/** The sell in parts of the Rentabilidad: the cost line after Costo, the markup line after Markup. */
const sellInCost = () => within(valueOf('Rentabilidad', 'Costo')).getByText(/c\/ sell in/);
const sellInOutMarkup = () => within(valueOf('Rentabilidad', 'Markup')).getByText('c/ sell in/out').parentElement;
const attention = () => screen.queryByRole('region', { name: 'Atención' });
const attentionItems = () => within(attention()).getAllByRole('listitem').map((li) => li.textContent);

describe('the order of the Resumen (S4)', () => {
  it('reads attention, Rentabilidad, Stock beside Producto vinculado, the Ficha, then the ML data (S5)', () => {
    renderTab(makeDetail({ ...DETAIL_RESPONSE_MARGIN, sub_status: ['out_of_stock'] }), { canSeeMargin: true });
    const titles = screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent);
    expect(titles).toEqual(['Atención', 'Rentabilidad', 'Stock', 'Producto vinculado', DATOS]);
    // Stock and Producto vinculado share one row.
    expect(section('Stock').parentElement).toBe(section('Producto vinculado').parentElement);
    const regions = screen.getAllByRole('region').map((region) => region.getAttribute('aria-labelledby') && region.textContent);
    expect(regions.at(-1)).toMatch(/^Más datos de Mercado Libre/);
  });

  it('the Ficha groups its lines under Publicación, Precio and Fechas, the tags as chips (S5)', () => {
    renderTab();
    const groups = within(section(DATOS)).getAllByRole('heading', { level: 4 }).map((h) => h.textContent);
    expect(groups).toEqual(['Publicación', 'Precio', 'Fechas']);
    const tags = within(section(DATOS)).getByRole('group', { name: 'Etiquetas' });
    expect(within(tags).getByText('good_quality_picture')).toBeInTheDocument();
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
    cleanup();
    renderTab(makeDetail({ row: makeItem({ ...ITEMS[3], gone_at: null }) }));
    expect(attentionItems()).toContain('Eliminada de Mercado Libre');
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
    expect(within(section('Producto vinculado')).getByText('Sin producto')).toBeInTheDocument();
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
    const tags = within(section(DATOS)).getByRole('group', { name: 'Etiquetas' });
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
    expect(valueOf(DATOS, 'Origen')).toHaveTextContent('Precio de oferta');
    expect(valueOf(DATOS, 'Regular')).toHaveTextContent('112.000,00');
    expect(valueOf(DATOS, 'Promoción')).toHaveTextContent('DEAL');
    expect(valueOf(DATOS, 'Promoción')).toHaveTextContent('Hot Sale');
  });

  it('leaves the promotion to the Promos tab for whoever has it, keeping the rest of the price data', () => {
    renderTab(DETAIL_RESPONSE, { canViewPromos: true });
    expect(within(section(DATOS)).queryByText('Promoción')).not.toBeInTheDocument();
    expect(valueOf(DATOS, 'Origen')).toHaveTextContent('Precio de oferta');
    expect(valueOf(DATOS, 'Regular')).toHaveTextContent('112.000,00');
  });

  it('labels the price that comes from Productos as such', () => {
    renderTab(makeDetail({ row: ITEMS[1] }));
    expect(valueOf(DATOS, 'Origen')).toHaveTextContent('Precio de Productos');
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
    for (const label of ['Condición', 'Tienda', 'Marca', 'Familia', 'Producto de usuario', 'Salud', 'Creada', 'Modificada en ML', 'Sincronizada', 'Origen', 'Promoción']) {
      expect(valueOf(DATOS, label)).toHaveTextContent(DASH);
    }
    expect(within(section(DATOS)).getByRole('group', { name: 'Etiquetas' })).toHaveTextContent(DASH);
    // The regular price is only there when it is not the price (S5).
    expect(within(section(DATOS)).queryByText('Regular', { selector: 'dt' })).not.toBeInTheDocument();
    expect(within(section(DATOS)).queryByText('0')).not.toBeInTheDocument();
  });
});

describe('the stock (the breakdown; the total is in the header)', () => {
  it('shows ERP and Full, as the table, and when they were read; nothing of the published quantity (S7)', () => {
    renderTab(makeDetail({ row: makeItem({ ...ITEMS[0], erp_stock: { quantity: 18 } }) }));
    const stockSection = section('Stock');
    const labels = within(stockSection)
      .getAllByRole('term')
      .map((term) => term.textContent);
    expect(labels).toEqual(['ERP', 'Full']);
    expect(valueOf('Stock', 'ERP')).toHaveTextContent('18');
    expect(valueOf('Stock', 'Full')).toHaveTextContent('20');
    expect(within(stockSection).getByText(/^Actualizado \d{2}\/\d{2}\/\d{4}/)).toBeInTheDocument();
  });

  it('a real 0 is shown as 0; an unknown figure is "—"', () => {
    renderTab(makeDetail({ row: makeItem({ ...ITEMS[0], stock: { available: 0, full: 0, own: 0, as_of: null } }), stock_locations: null }));
    expect(valueOf('Stock', 'Full')).toHaveTextContent('0');
    expect(valueOf('Stock', 'ERP')).toHaveTextContent(DASH);
  });
});

describe('the linked product', () => {
  it('shows the state as a chip and the product it points to', () => {
    renderTab();
    const card = within(section('Producto vinculado'));
    expect(card.getByText('Automático')).toHaveAttribute('data-tone', 'success');
    expect(card.getByText('ARCHER-AX55')).toBeInTheDocument();
    expect(card.getByText('Router Archer AX55')).toBeInTheDocument();
  });

  it('an unlinked publication says so', () => {
    renderTab(makeDetail({ row: ITEMS[3] }));
    const card = within(section('Producto vinculado'));
    expect(card.getAllByText('Sin producto')[0]).toHaveAttribute('data-tone', 'warning');
    expect(card.queryByText('ARCHER-AX55')).not.toBeInTheDocument();
  });
});

describe('Rentabilidad (ver_ganancia only): from the price down to the markup', () => {
  it('reads as a waterfall, Precio first and the Markup band last, then what it was computed on (S5)', () => {
    renderTab(DETAIL_RESPONSE_MARGIN, { canSeeMargin: true });
    const steps = [...section('Rentabilidad').querySelectorAll('dl')[0].querySelectorAll('dt')];
    // The label is the step's first text; its aside (the %, the source) follows it.
    expect(steps.map((dt) => dt.firstChild.textContent)).toEqual(['Precio', 'Comisión', 'Costo de envío', 'Precio limpio', 'Costo']);
    // The sign of each step sits outside the label: "− Comisión", "− Costo de envío", "= Precio limpio".
    expect(steps.map((dt) => dt.parentElement.dataset.op ?? '')).toEqual(['', '−', '−', '=', '']);
    expect([...section('Rentabilidad').querySelectorAll('dl')[1].querySelectorAll('dt')].map((dt) => dt.textContent)).toEqual(['Markup']);
    expect(valueOf('Rentabilidad', 'Precio')).toHaveTextContent('98.500,50');
    expect(valueOf('Rentabilidad', 'Comisión')).toHaveTextContent('13.297,57');
    expect(stepOf('Comisión')).toHaveTextContent('13,5%');
    expect(valueOf('Rentabilidad', 'Costo de envío')).toHaveTextContent('4.200,00');
    expect(stepOf('Costo de envío')).toHaveTextContent('ERP');
    expect(valueOf('Rentabilidad', 'Precio limpio')).toHaveTextContent('81.002,93');
    expect(valueOf('Rentabilidad', 'Costo')).toHaveTextContent('64.000,00');
    expect(valueOf('Rentabilidad', 'Markup')).toHaveTextContent('26,5%');
    expect(within(section('Rentabilidad')).getByText('Calculado sobre la publicación · 6 cuotas · lista de precios 12')).toBeInTheDocument();
  });

  it('names where the computed price comes from when it is not the publication price shown in the data', () => {
    renderTab(makeDetail({ markup_breakdown: { ...DETAIL_RESPONSE_MARGIN.markup_breakdown, price_source: 'item_price', variation_id: 77 } }), {
      canSeeMargin: true,
    });
    expect(stepOf('Precio')).toHaveTextContent('Precio de la publicación');
    cleanup();
    renderTab(DETAIL_RESPONSE_MARGIN, { canSeeMargin: true });
    expect(stepOf('Precio')).not.toHaveTextContent('Precio de oferta');
  });

  it('a partial breakdown keeps the percentage and the shipping source it has', () => {
    renderTab(
      makeDetail({ markup_breakdown: { ...DETAIL_RESPONSE_MARGIN.markup_breakdown, comision_total: null, costo_envio: null } }),
      { canSeeMargin: true },
    );
    expect(stepOf('Comisión')).toHaveTextContent('13,5%');
    expect(stepOf('Costo de envío')).toHaveTextContent('ERP');
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
    const costo = sellInCost();
    expect(costo).toHaveTextContent('62.500,00');
    const tooltip = costo.querySelector('[title]').getAttribute('title');
    expect(tooltip).toContain('1.500,00');
    expect(tooltip).toContain('12');
    const markup = sellInOutMarkup();
    expect(markup).toHaveTextContent('29,6%');
    expect(markup.querySelector('[title]').getAttribute('title')).toBe('Con sell in');
  });

  it('S10: a USD cost reads in USD with the pesos small beside it, and its cost with sell in in USD', () => {
    // 40 USD at 1600 = the breakdown's 64.000 ARS; the backend's sell in in USD at that same rate.
    const sellInUsd = { ...SELL_IN, moneda_costo: 'USD', costo_moneda: 39.0625, descuento_unit_moneda: 0.9375 };
    renderTab(
      makeDetail({
        markup_breakdown: { ...DETAIL_RESPONSE_MARGIN.markup_breakdown, costo: 40, moneda_costo: 'USD' },
        sell_in_out: { sell_in: sellInUsd, sell_out: null, markups_sell_in: { publicacion: 29.6 }, markups_sell_in_out: {} },
      }),
      { canSeeMargin: true },
    );
    const costo = valueOf('Rentabilidad', 'Costo');
    expect(within(costo).getByText('USD 40,00')).toBeInTheDocument();
    expect(within(costo).getByText('$ 64.000,00')).toBeInTheDocument(); // the pesos the markup divides by, small
    expect(sellInCost()).toHaveTextContent('USD 39,06');
    expect(sellInCost().querySelector('[title]').getAttribute('title')).toBe(
      'Descuento por unidad: USD 0,94 ($ 1.500,00)\nc/ sell in en pesos: $ 62.500,00\nUnidades restantes del lote: 12',
    );
  });

  it('S10: a USD cost without a rate today shows no pesos figure, it says there is no rate', () => {
    const sellInSinTasa = { ...SELL_IN, costo: 38.5, moneda_costo: 'USD', costo_moneda: null, descuento_unit_moneda: null };
    renderTab(
      makeDetail({
        markup_breakdown: { ...DETAIL_RESPONSE_MARGIN.markup_breakdown, costo_ars: 40, costo: 40, moneda_costo: 'USD', tipo_cambio: null },
        sell_in_out: { sell_in: sellInSinTasa, sell_out: null, markups_sell_in: {}, markups_sell_in_out: {} },
      }),
      { canSeeMargin: true },
    );
    const costo = valueOf('Rentabilidad', 'Costo');
    expect(within(costo).getByText('USD 40,00')).toBeInTheDocument();
    expect(within(costo).queryByText('$ 40,00')).not.toBeInTheDocument();
    expect(within(costo).getAllByText('Sin tipo de cambio')).toHaveLength(2); // the pesos and the cost with sell in
  });

  it('names the % of cost bonus in the tooltip when the sell in has no lot (T25c)', () => {
    const bono = { ...SELL_IN, compra_item_id: null, bono_id: 4, unidades_restantes: null };
    renderTab(withSellInOut({ sell_in: bono, sell_out: null, markups_sell_in: {}, markups_sell_in_out: {} }), { canSeeMargin: true });
    const tooltip = sellInCost().querySelector('[title]').getAttribute('title');
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
    const markup = sellInOutMarkup();
    expect(markup).toHaveTextContent('-2,4%');
    expect(markup.querySelector('[data-negative]')).not.toBeNull();
    expect(markup.querySelector('[title]').getAttribute('title')).toContain('Con sell in y sell out');
  });

  it('an unknown amount reads "Pendiente", never a number', () => {
    renderTab(
      withSellInOut({ sell_in: null, sell_out: { monto_unit: null, campana_ids: [3] }, markups_sell_in: {}, markups_sell_in_out: {} }),
      { canSeeMargin: true },
    );
    expect(sellInOutMarkup()).toHaveTextContent('Pendiente');
    expect(sellInOutMarkup()).not.toHaveTextContent('%');
  });

  it('a lot without a cost in pesos says "Sin tipo de cambio" and its markup is pending', () => {
    renderTab(
      withSellInOut({ sell_in: { ...SELL_IN, costo: null }, sell_out: null, markups_sell_in: {}, markups_sell_in_out: {} }),
      { canSeeMargin: true },
    );
    expect(sellInCost()).toHaveTextContent('Sin tipo de cambio');
    expect(sellInOutMarkup()).toHaveTextContent('Pendiente');
  });

  it('without sell in nor sell out nothing new is shown', () => {
    renderTab(withSellInOut(null), { canSeeMargin: true });
    expect(screen.queryByText(/c\/ sell in/)).not.toBeInTheDocument();
  });

  it('without the permission it is not shown, even if the payload carried it', () => {
    renderTab(withSellInOut({ sell_in: SELL_IN, sell_out: null, markups_sell_in: { publicacion: 29.6 }, markups_sell_in_out: {} }));
    expect(screen.queryByText(/c\/ sell in/)).not.toBeInTheDocument();
  });
});

describe('Más datos de Mercado Libre: collapsed by default (S5)', () => {
  /** Renders and opens the block. */
  const renderOpen = (raw = DETAIL_RESPONSE) => {
    renderTab(raw);
    openMoreMl();
  };
  const lineOf = (label) => within(section(MORE_ML)).getByText(label, { selector: 'dt' }).nextElementSibling;
  const absent = (label) => expect(within(section(MORE_ML)).queryByText(label, { selector: 'dt' })).not.toBeInTheDocument();

  it('starts closed and opens with its button, which says so', () => {
    renderTab();
    const toggle = screen.getByRole('button', { name: /Más datos de Mercado Libre/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('MLA1648')).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('MLA1648')).toBeInTheDocument();
    fireEvent.click(toggle);
    expect(screen.queryByText('MLA1648')).not.toBeInTheDocument();
  });

  it('shows the quantities and the currency as tiles', () => {
    renderOpen();
    expect(lineOf('Cantidad inicial')).toHaveTextContent('200');
    expect(lineOf('Vendidas')).toHaveTextContent('120');
    expect(lineOf('Moneda')).toHaveTextContent('ARS');
  });

  it('groups the rest under Categoría y catálogo, Venta, Envío and Fechas en ML', () => {
    renderOpen();
    const groups = within(section(MORE_ML)).getAllByRole('heading', { level: 4 }).map((h) => h.textContent);
    expect(groups.slice(0, 4)).toEqual(['Categoría y catálogo', 'Venta', 'Envío', 'Fechas en ML']);
  });

  it('names the category, domain, seller, catalog product and buying mode', () => {
    renderOpen();
    expect(lineOf('Categoría')).toHaveTextContent('MLA1648');
    expect(lineOf('Dominio')).toHaveTextContent('MLA-ROUTERS');
    expect(lineOf('Vendedor')).toHaveTextContent('123456789');
    expect(lineOf('Producto de catálogo')).toHaveTextContent('MLA19000001');
    expect(lineOf('Modo de compra')).toHaveTextContent('buy_it_now');
  });

  it("ML's base and original prices show only when the panel does not already show that amount", () => {
    // The regular price (Ficha) is 112.000,00, as ML's base price: shown once.
    renderOpen();
    absent('Precio base');
    cleanup();
    renderOpen(makeDetail({ item: { ...ITEM_COLUMNS, base_price: 115000, original_price: 98500.5 } }));
    expect(lineOf('Precio base')).toHaveTextContent('115.000,00');
    // 98.500,50 is the publication's price, in the panel header.
    absent('Precio original');
  });

  it("shows the seller's own codes", () => {
    renderOpen();
    expect(lineOf('SKU del vendedor')).toHaveTextContent('AX55-SKU');
    expect(lineOf('Campo personalizado')).toHaveTextContent('ARCHER-AX55');
    expect(lineOf('Inventario')).toHaveTextContent('ABCD1234');
  });

  it('shows the shipping mode, free shipping and the publication dates; a date ML does not have is left out', () => {
    renderOpen();
    expect(lineOf('Modo de envío')).toHaveTextContent('me2');
    expect(lineOf('Envío gratis')).toHaveTextContent('Sí');
    expect(lineOf('Inicio').textContent).toMatch(/\d{2}\/\d{2}\/\d{4}/);
    absent('Finalizada');
  });

  it('leaves the last error to the attention box', () => {
    renderOpen(makeDetail({ item: { ...ITEM_COLUMNS, last_error: 'HTTP 500' } }));
    absent('Último error');
  });

  it('an empty field is left out, and a real false reads "No", a real 0 "0"', () => {
    renderOpen(makeDetail({ item: { ...ITEM_COLUMNS, category_id: null, seller_sku: null, free_shipping: false, initial_quantity: 0 } }));
    absent('Categoría');
    absent('SKU del vendedor');
    expect(lineOf('Envío gratis')).toHaveTextContent('No');
    expect(lineOf('Cantidad inicial')).toHaveTextContent('0');
    expect(within(section(MORE_ML)).queryByText(DASH)).not.toBeInTheDocument();
  });

  it('tolerates a detail without the item block', () => {
    renderOpen(makeDetail({ item: undefined, extra: undefined }));
    absent('Categoría');
  });

  it('shows the warranty and the yes/no options as chips', () => {
    renderOpen();
    expect(lineOf('Garantía')).toHaveTextContent('Garantía del vendedor: 6 meses');
    const options = within(section(MORE_ML)).getByRole('list', { name: 'Opciones' });
    const chip = (text) => within(options).getByText(text, { exact: false }).closest('[data-tone], span');
    expect(chip('Acepta Mercado Pago')).toHaveAttribute('data-tone', 'success');
    expect(within(chip('Acepta Mercado Pago')).getByLabelText('Sí')).toBeInTheDocument();
    expect(within(chip('Republicación automática')).getByLabelText('No')).toBeInTheDocument();
    // "none" is a no: no international delivery.
    expect(within(chip('Entrega internacional')).getByLabelText('No')).toBeInTheDocument();
  });

  it('lists the channels, the offers and the shipping tags', () => {
    renderOpen();
    const channels = within(section(MORE_ML)).getByRole('group', { name: 'Canales' });
    expect(channels).toHaveTextContent('marketplace');
    expect(channels).toHaveTextContent('mshops');
    expect(lineOf('Ofertas')).toHaveTextContent('MLA12345');
    expect(within(section(MORE_ML)).getByRole('group', { name: 'Etiquetas de envío' })).toHaveTextContent('self_service_in');
  });

  it('shows the shipping, not the seller address (the seller is the company itself)', () => {
    renderOpen();
    expect(lineOf('Retiro en persona')).toHaveTextContent('No');
    expect(lineOf('Retiro en tienda')).toHaveTextContent('No');
    expect(within(section(MORE_ML)).queryByText('Ciudad')).not.toBeInTheDocument();
    expect(within(section(MORE_ML)).queryByText('Provincia')).not.toBeInTheDocument();
  });

  it('lists the sale terms and the item relations, and the attributes as a table', () => {
    renderOpen();
    expect(lineOf('Condiciones de venta')).toHaveTextContent('Tiempo de garantía: 6 meses');
    expect(lineOf('Condiciones de venta')).toHaveTextContent('Cuotas: 6x_campaign');
    expect(lineOf('Relaciones')).toHaveTextContent('MLA1100000009');
    expect(lineOf('Marca')).toHaveTextContent('TP-Link');
    expect(lineOf('Modelo')).toHaveTextContent('Archer AX55');
  });

  it('shows every picture as a thumbnail linking to it, and only over https', () => {
    renderOpen(
      makeDetail({
        extra: { ...EXTRA_FIELDS, pictures: [...EXTRA_FIELDS.pictures, { id: '3-MLA', secure_url: 'javascript:alert(1)', size: null, max_size: null }] },
      }),
    );
    const links = within(section(MORE_ML)).getAllByRole('link');
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAttribute('href', 'https://http2.mlstatic.com/D_111-O.jpg');
    expect(links[0]).toHaveAttribute('rel', expect.stringContaining('noopener'));
    expect(within(links[0]).getByRole('img', { name: 'Imagen 1' })).toHaveAttribute('src', 'https://http2.mlstatic.com/D_111-O.jpg');
    expect(within(section(MORE_ML)).getByText('2 imágenes (1 sin enlace)')).toBeInTheDocument();
  });

  it('a body the store does not have leaves its fields out, no "—" anywhere', () => {
    const empty = Object.fromEntries(Object.keys(EXTRA_FIELDS).map((key) => [key, null]));
    renderOpen(makeDetail({ extra: empty }));
    for (const label of ['Garantía', 'Ofertas', 'Retiro en persona', 'Condiciones de venta', 'Relaciones']) absent(label);
    expect(within(section(MORE_ML)).queryByRole('list', { name: 'Opciones' })).not.toBeInTheDocument();
    expect(within(section(MORE_ML)).queryByText('Atributos')).not.toBeInTheDocument();
    expect(within(section(MORE_ML)).queryByText('Imágenes')).not.toBeInTheDocument();
    expect(within(section(MORE_ML)).queryByText(DASH)).not.toBeInTheDocument();
  });

  it('an attribute without its value is left out, as any empty field', () => {
    renderOpen(makeDetail({ extra: { ...EXTRA_FIELDS, attributes: [...EXTRA_FIELDS.attributes, { id: 'COLOR', name: 'Color', value_name: null }] } }));
    expect(lineOf('Modelo')).toHaveTextContent('Archer AX55');
    absent('Color');
  });

  it('an empty list is left out too', () => {
    renderOpen(makeDetail({ extra: { ...EXTRA_FIELDS, channels: [], attributes: [] } }));
    expect(within(section(MORE_ML)).queryByRole('group', { name: 'Canales' })).not.toBeInTheDocument();
    expect(within(section(MORE_ML)).queryByText('Atributos')).not.toBeInTheDocument();
  });

  it('differential pricing is shown as what it is, whatever its shape', () => {
    renderOpen(makeDetail({ extra: { ...EXTRA_FIELDS, differential_pricing: { id: 7 } } }));
    expect(within(section(MORE_ML)).getByText(/Precio diferencial: \{"id":7\}/)).toBeInTheDocument();
  });
});
