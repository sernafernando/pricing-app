/**
 * priceColumns (S11): Productos' price columns in Publicaciones ML, one set per mode (Normal / Cuotas / PVP), with
 * Productos' headers and its own display rules, read from `useListPrices`.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { priceColumns } from './priceColumns';

const PRODUCT = {
  item_id: 7,
  precio_lista_ml: 1000,
  markup: 25,
  participa_rebate: true,
  precio_rebate: 1040,
  markup_rebate: 22.5,
  mejor_oferta_precio: null,
  participa_web_transferencia: false,
  precio_web_transferencia: 950,
  markup_web_real: 10,
  precio_3_cuotas: 1100,
  markup_3_cuotas: 20,
  precio_pvp: 1500,
  markup_pvp: 40,
};
const prices = (byId = new Map([[7, PRODUCT]]), loading = false) => ({ byId, loading, error: false });
const item = (productId = 7) => ({ item_id: 'MLA1', link: { producto_item_id: productId } });
// The text a column draws for a row (each render in its own container, unmounted at once).
const textOf = (node) => {
  const { container, unmount } = render(<div>{node}</div>);
  const text = container.textContent;
  unmount();
  return text;
};
const cell = (column, row = item()) => textOf(column.render(row));

describe('priceColumns', () => {
  it("has Productos' headers per mode, under one group", () => {
    const headers = (mode) => priceColumns(mode, { prices: prices() }).map((column) => column.header);
    expect(headers('normal')).toEqual(['Precio Clásica', 'Precio Rebate', 'Mejor Oferta', 'Web Transf.']);
    expect(headers('cuotas')).toEqual(['Precio Clásica', '3 Cuotas', '6 Cuotas', '9 Cuotas', '12 Cuotas']);
    expect(headers('pvp')).toEqual(['Precio PVP', 'PVP 3 Cuotas', 'PVP 6 Cuotas', 'PVP 9 Cuotas', 'PVP 12 Cuotas']);
    expect(new Set(priceColumns('cuotas', { prices: prices() }).map((column) => column.group))).toEqual(new Set(['Precios de Productos']));
  });

  it("shows the price of the publication's product, and its markup only with the margin permission", () => {
    const [clasica] = priceColumns('normal', { prices: prices(), canSeeMargin: true });
    expect(cell(clasica)).toContain('1.000,00');
    expect(cell(clasica)).toContain('25,0%');
  });

  it("reads the best offer's markup as Productos does: the listing sends it as a fraction", () => {
    const product = { ...PRODUCT, mejor_oferta_precio: 990, mejor_oferta_markup: 0.1234 };
    const [, , oferta] = priceColumns('normal', { prices: prices(new Map([[7, product]])), canSeeMargin: true });
    expect(cell(oferta)).toContain('12,3%');
    const [, rebate] = priceColumns('normal', { prices: prices(), canSeeMargin: true });
    expect(cell(rebate)).toContain('22,5%');
  });

  it("shows the best offer's details under its price, in Productos' order: contribution %, rebate, end date, seller PVP (S2)", () => {
    const product = {
      ...PRODUCT,
      mejor_oferta_precio: 990,
      mejor_oferta_markup: 0.1,
      mejor_oferta_porcentaje_rebate: 12.5,
      mejor_oferta_monto_rebate: 1500,
      mejor_oferta_fecha_hasta: '2026-11-30',
      mejor_oferta_pvp_seller: 1200,
    };
    const [, , oferta] = priceColumns('normal', { prices: prices(new Map([[7, product]])) });
    const { container, unmount } = render(<div>{oferta.render(item())}</div>);
    const lines = [...container.querySelectorAll('[data-price-detail]')].map((line) => line.textContent);
    expect(lines).toEqual(['Aporte 12,50%', 'Rebate $ 1.500,00', 'Hasta 30/11', 'PVP $ 1.200,00']);
    unmount();
    // Only the details it has; none without an offer.
    const partial = { ...PRODUCT, mejor_oferta_precio: 990, mejor_oferta_fecha_hasta: '2026-11-30' };
    const [, , onlyDate] = priceColumns('normal', { prices: prices(new Map([[7, partial]])) });
    expect(cell(onlyDate)).toContain('Hasta 30/11');
    expect(cell(onlyDate)).not.toContain('Aporte');
    const [, , none] = priceColumns('normal', { prices: prices(new Map([[7, { ...PRODUCT, mejor_oferta_fecha_hasta: '2026-11-30' }]])) });
    expect(cell(none)).toBe('—');
    // The other columns have no details.
    const [clasica] = priceColumns('normal', { prices: prices(new Map([[7, product]])) });
    expect(cell(clasica)).not.toContain('Hasta');
    // They are not margin: shown with the markup and without it; prices on their way read "…", no details.
    const [, , withMargin] = priceColumns('normal', { prices: prices(new Map([[7, product]])), canSeeMargin: true });
    expect(cell(withMargin)).toContain('10,0%');
    expect(cell(withMargin)).toContain('PVP $ 1.200,00');
    const [, , loading] = priceColumns('normal', { prices: prices(new Map(), true) });
    expect(cell(loading)).toBe('…');
  });

  it("shows the web transfer's % over the clásica under its price, and a lock when it is kept in bulk changes, as Productos", () => {
    const web = (fields) => priceColumns('normal', { prices: prices(new Map([[7, { ...PRODUCT, participa_web_transferencia: true, ...fields }]])) })[3];
    const draw = (fields) => render(<div>{web(fields).render(item())}</div>);
    const kept = draw({ porcentaje_markup_web: 6.5, preservar_porcentaje_web: true });
    expect([...kept.container.querySelectorAll('[data-price-detail]')].map((line) => line.textContent)).toEqual(['(+6,5%)']);
    expect(screen.getByRole('img', { name: '% conservado en cambios masivos' })).toBeInTheDocument();
    kept.unmount();
    // Not kept: the % without the lock; no % stored: nothing under the price; not taking part: '—' alone.
    const free = draw({ porcentaje_markup_web: 6, preservar_porcentaje_web: false });
    expect(free.container).toHaveTextContent('(+6%)');
    expect(screen.queryByRole('img')).toBeNull();
    free.unmount();
    // A web transfer under the clásica carries its own sign; 0 reads as +0.
    expect(cell(web({ porcentaje_markup_web: -3 }))).toContain('(-3%)');
    expect(cell(web({ porcentaje_markup_web: 0 }))).toContain('(+0%)');
    const bare = draw({ porcentaje_markup_web: null, preservar_porcentaje_web: true });
    expect(bare.container).toHaveTextContent(/^950,00$/);
    expect(screen.queryByRole('img')).toBeNull();
    bare.unmount();
    expect(cell(web({ participa_web_transferencia: false, porcentaje_markup_web: 6 }))).toBe('—');
  });

  describe("Tienda Nube's price in Web Transf. (S3), as Productos", () => {
    const tn = (fields, tnCardPercent = 25) => {
      const product = { ...PRODUCT, ...fields };
      const [, , , web] = priceColumns('normal', { prices: prices(new Map([[7, product]])), tnCardPercent });
      return web;
    };

    it('shows the TN price with its transfer price (the card surcharge taken off), above the web transfer', () => {
      const web = tn({ tn_price: 1000, participa_web_transferencia: true });
      render(<div>{web.render(item())}</div>);
      const line = screen.getByText('$ 1.000,00').closest('[data-tn-price]');
      expect(line).toHaveTextContent('$800,00 transf.');
      // The web transfer's own price follows.
      expect(screen.getByText('950,00')).toBeInTheDocument();
    });

    it('a TN promotion shows the promotional price with its hint and the regular one struck through', () => {
      const web = tn({ tn_price: 1000, tn_promotional_price: 900, tn_has_promotion: true });
      const { container } = render(<div>{web.render(item())}</div>);
      expect(container.querySelector('[data-tn-price]')).toHaveTextContent('$ 900,00$720,00 transf.');
      expect(container.querySelector('s')).toHaveTextContent('$ 1.000,00');
      // Not taking part in the web transfer: its own figure still reads "—".
      expect(container).toHaveTextContent('—');
    });

    it('a promotion with no regular price (0 or missing) shows no struck line and no stray figure', () => {
      for (const tn_price of [0, null]) {
        const web = tn({ tn_price, tn_promotional_price: 900, tn_has_promotion: true });
        const { container, unmount } = render(<div>{web.render(item())}</div>);
        expect(container.querySelector('s')).toBeNull();
        expect(container.querySelector('[data-tn-price]')).toHaveTextContent(/^\$ 900,00\$720,00 transf\.$/);
        unmount();
      }
    });

    it('without the surcharge (not loaded, or failed) the TN price shows alone, never a wrong transfer price', () => {
      // Not read yet or failed (null), and an unusable config value (0, not a number) alike.
      for (const percent of [null, 0, 'abc']) {
        const web = tn({ tn_price: 1000 }, percent);
        expect(cell(web)).toContain('$ 1.000,00');
        expect(cell(web)).not.toContain('transf.');
      }
    });

    it('no TN price: the cell is as before; the other columns never show it', () => {
      expect(cell(tn({}))).toBe('—');
      const [clasica] = priceColumns('normal', { prices: prices(new Map([[7, { ...PRODUCT, tn_price: 1000 }]])), tnCardPercent: 25 });
      expect(cell(clasica)).not.toContain('transf.');
    });
  });

  it('never shows a markup without the margin permission', () => {
    const [clasica] = priceColumns('normal', { prices: prices(), canSeeMargin: false });
    expect(cell(clasica)).toContain('1.000,00');
    expect(cell(clasica)).not.toContain('%');
  });

  it('like Productos: the rebate and the web transfer only when the product takes part, no offer is "—"', () => {
    const [, rebate, oferta, web] = priceColumns('normal', { prices: prices() });
    expect(cell(rebate)).toContain('1.040,00');
    expect(cell(oferta)).toBe('—');
    expect(cell(web)).toBe('—');
  });

  it('a publication with no product, a product not priced and a request on its way read "—", never 0', () => {
    const [clasica] = priceColumns('normal', { prices: prices() });
    expect(cell(clasica, item(null))).toBe('—');
    const [cuota12] = priceColumns('cuotas', { prices: prices() }).slice(-1);
    expect(cell(cuota12)).toBe('—');
    const [pending] = priceColumns('normal', { prices: prices(new Map(), true) });
    expect(cell(pending)).toBe('…');
    expect(cell(pending, item(null))).toBe('—');
  });

  it('a failed request says so, never "—" as if there were no price', () => {
    const [clasica] = priceColumns('normal', { prices: { byId: new Map(), loading: false, error: true } });
    const { container, unmount } = render(<div>{clasica.render(item())}</div>);
    expect(container.textContent).not.toBe('—');
    expect(container.querySelector('[title="No se pudieron cargar los precios de Productos"]')).not.toBeNull();
    unmount();
    // A publication with no product has no price to fail.
    expect(cell(clasica, item(null))).toBe('—');
  });

  it("sorts by the markup the Clásica, Rebate, Mejor Oferta and Web Transf. headers, like Productos, with the margin permission", () => {
    const sortable = (mode, canSeeMargin) =>
      priceColumns(mode, { prices: prices(), canSeeMargin })
        .filter((column) => column.sortable)
        .map((column) => column.key);
    expect(sortable('normal', true)).toEqual(['lista_clasica', 'lista_rebate', 'lista_oferta', 'lista_web']);
    expect(sortable('cuotas', true)).toEqual(['lista_clasica']); // the cuotas headers do not sort in Productos
    expect(sortable('pvp', true)).toEqual([]);
    expect(sortable('normal', false)).toEqual([]);
  });

  it("draws a product row from the product's own id", () => {
    const [pvp] = priceColumns('pvp', { prices: prices() });
    expect(textOf(pvp.renderProduct(7))).toContain('1.500,00');
  });

  describe('editing (S11c)', () => {
    const ALL = { canEditClasica: true, canEditMlCuotas: true, canEditPvp: true };
    const edit = (permissions = ALL) => ({ permissions, onSave: vi.fn().mockResolvedValue(true), saving: false });
    const mount = (node) => render(<div>{node}</div>);

    it("each list's price is edited in place, saved as Productos' list of that column", async () => {
      const options = edit();
      const [clasica] = priceColumns('normal', { prices: prices(), edit: options });
      mount(clasica.render(item()));
      await userEvent.click(screen.getByRole('button', { name: /^Editar Precio Clásica/ }));
      await userEvent.type(screen.getByRole('textbox', { name: 'Precio Clásica' }), '{Control>}a{/Control}1500{Enter}');
      expect(options.onSave).toHaveBeenCalledWith(expect.objectContaining({ id: 'ml-clasica' }), PRODUCT, '1500');
    });

    it('maps every cuota and PVP column to its list', () => {
      const lists = (mode) => priceColumns(mode, { prices: prices(), edit: edit() }).map((column) => column.list);
      expect(lists('cuotas')).toEqual(['ml-clasica', 'ml-3', 'ml-6', 'ml-9', 'ml-12']);
      expect(lists('pvp')).toEqual(['pvp-clasica', 'pvp-3', 'pvp-6', 'pvp-9', 'pvp-12']);
      // Rebate, best offer and web transfer are not prices of a list Productos edits from its grid.
      expect(lists('normal')).toEqual(['ml-clasica', undefined, undefined, undefined]);
    });

    it('only with the permission of that list', () => {
      const [clasica, cuota3] = priceColumns('cuotas', { prices: prices(), edit: edit({ canEditClasica: false, canEditMlCuotas: true }) });
      mount(clasica.render(item()));
      expect(screen.queryByRole('button')).not.toBeInTheDocument();
      mount(cuota3.render(item()));
      expect(screen.getByRole('button', { name: /^Editar 3 Cuotas/ })).toBeInTheDocument();
    });

    it('never with no product, a request on its way or a failed one', () => {
      const [clasica] = priceColumns('normal', { prices: prices(), edit: edit() });
      mount(clasica.render(item(null)));
      const [pending] = priceColumns('normal', { prices: prices(new Map(), true), edit: edit() });
      mount(pending.render(item()));
      const [failed] = priceColumns('normal', { prices: { byId: new Map(), loading: false, error: true }, edit: edit() });
      mount(failed.render(item()));
      expect(screen.queryByRole('button')).not.toBeInTheDocument();
    });
  });

  describe("the rebate and web transfer edited in the row (S1), as Productos' row and the panel's ProductToggles", () => {
    const TOGGLES = { canToggleRebate: true, canToggleWebTransf: true };
    const edit = (permissions = TOGGLES) => ({ permissions, onSave: vi.fn(), onToggle: vi.fn().mockResolvedValue(true), saving: false });
    const PRICED = { ...PRODUCT, porcentaje_rebate: 4.5, porcentaje_markup_web: 7, preservar_porcentaje_web: true };
    const columnsWith = (options, product = PRICED) => priceColumns('normal', { prices: prices(new Map([[7, product]])), edit: options });

    it('the rebate opens Productos\' editor (takes part and its %) and saves what was typed', async () => {
      const options = edit();
      const [, rebate] = columnsWith(options);
      render(<div>{rebate.render(item())}</div>);
      await userEvent.click(screen.getByRole('button', { name: /^Editar Precio Rebate/ }));
      const editor = screen.getByRole('group', { name: 'Rebate' });
      expect(editor).toBeInTheDocument();
      expect(screen.getByRole('checkbox', { name: 'Participa' })).toBeChecked();
      const percent = screen.getByRole('textbox', { name: '% de rebate' });
      expect(percent).toHaveValue('4,5');
      await userEvent.clear(percent);
      await userEvent.type(percent, '5,2{Enter}');
      expect(options.onToggle).toHaveBeenCalledWith('rebate', PRICED, { participa: true, porcentaje: '5,2' });
      // Saved: the cell is back.
      expect(await screen.findByRole('button', { name: /^Editar Precio Rebate/ })).toBeInTheDocument();
    });

    it("a product with no rebate opens with Productos' default and can be turned on from its '—'", async () => {
      const options = edit();
      const [, rebate] = columnsWith(options, { ...PRODUCT, participa_rebate: false, porcentaje_rebate: null });
      render(<div>{rebate.render(item())}</div>);
      await userEvent.click(screen.getByRole('button', { name: /^Editar Precio Rebate/ }));
      expect(screen.getByRole('checkbox', { name: 'Participa' })).not.toBeChecked();
      await userEvent.click(screen.getByRole('checkbox', { name: 'Participa' }));
      expect(screen.getByRole('textbox', { name: '% de rebate' })).toHaveValue('3,8');
    });

    it('the web transfer opens with its %, "preservar porcentaje" included, and saves all three', async () => {
      const options = edit();
      const [, , , web] = columnsWith(options);
      render(<div>{web.render(item())}</div>);
      await userEvent.click(screen.getByRole('button', { name: /^Editar Web Transf\./ }));
      expect(screen.getByRole('group', { name: 'Web transferencia' })).toBeInTheDocument();
      expect(screen.getByRole('textbox', { name: '% sobre la clásica' })).toHaveValue('7');
      const preservar = screen.getByRole('checkbox', { name: 'Conservar el % en cambios masivos' });
      expect(preservar).toBeChecked();
      await userEvent.click(preservar);
      await userEvent.click(screen.getByRole('button', { name: 'Guardar' }));
      expect(options.onToggle).toHaveBeenCalledWith('web', PRICED, { participa: false, porcentaje: '7', preservar: false });
    });

    it('Cancelar or Escape closes it without saving; a failed save keeps it open', async () => {
      const options = edit();
      options.onToggle.mockResolvedValue(false);
      const [, rebate] = columnsWith(options);
      render(<div>{rebate.render(item())}</div>);
      await userEvent.click(screen.getByRole('button', { name: /^Editar Precio Rebate/ }));
      await userEvent.click(screen.getByRole('button', { name: 'Cancelar' }));
      expect(screen.queryByRole('group', { name: 'Rebate' })).not.toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: /^Editar Precio Rebate/ }));
      await userEvent.keyboard('{Escape}');
      expect(screen.queryByRole('group', { name: 'Rebate' })).not.toBeInTheDocument();
      expect(options.onToggle).not.toHaveBeenCalled();
      await userEvent.click(screen.getByRole('button', { name: /^Editar Precio Rebate/ }));
      await userEvent.click(screen.getByRole('button', { name: 'Guardar' }));
      expect(options.onToggle).toHaveBeenCalledTimes(1);
      expect(screen.getByRole('group', { name: 'Rebate' })).toBeInTheDocument();
    });

    it("the editor's keys and clicks stay in it: the row and its shortcuts never see them", async () => {
      const row = { onKeyDown: vi.fn(), onClick: vi.fn() };
      const [, rebate] = columnsWith(edit());
      render(<div {...row}>{rebate.render(item())}</div>);
      // The click that opens it is a button's: TableShell's row ignores those (as with PriceEditCell).
      await userEvent.click(screen.getByRole('button', { name: /^Editar Precio Rebate/ }));
      row.onClick.mockClear();
      await userEvent.type(screen.getByRole('textbox', { name: '% de rebate' }), 'rw');
      await userEvent.click(screen.getByRole('group', { name: 'Rebate' }));
      expect(row.onKeyDown).not.toHaveBeenCalled();
      expect(row.onClick).not.toHaveBeenCalled();
    });

    it('only with the permission of each: toggle_rebate and toggle_web_transf', () => {
      const [, rebate, , web] = columnsWith(edit({ canToggleRebate: false, canToggleWebTransf: true }));
      render(<div>{rebate.render(item())}</div>);
      expect(screen.queryByRole('button')).not.toBeInTheDocument();
      render(<div>{web.render(item())}</div>);
      expect(screen.getByRole('button', { name: /^Editar Web Transf\./ })).toBeInTheDocument();
    });

    it('never with no product, a request on its way or a failed one; the best offer never', () => {
      const [, rebate] = columnsWith(edit());
      render(<div>{rebate.render(item(null))}</div>);
      const [, pending] = priceColumns('normal', { prices: prices(new Map(), true), edit: edit() });
      render(<div>{pending.render(item())}</div>);
      const [, failed] = priceColumns('normal', { prices: { byId: new Map(), loading: false, error: true }, edit: edit() });
      render(<div>{failed.render(item())}</div>);
      const [, , oferta] = columnsWith(edit());
      render(<div>{oferta.render(item())}</div>);
      expect(screen.queryByRole('button')).not.toBeInTheDocument();
    });
  });

  describe("Productos' pricing modal (P3c)", () => {
    it("closes the group with a Calcular column whose button hands over the row's product", async () => {
      const onCalculate = vi.fn();
      const columns = priceColumns('cuotas', { prices: prices(), onCalculate });
      const last = columns.at(-1);
      expect(last).toMatchObject({ header: 'Calcular', group: 'Precios de Productos' });
      render(<div>{last.render(item())}</div>);
      await userEvent.click(screen.getByRole('button', { name: 'Calcular el precio del producto 7' }));
      expect(onCalculate).toHaveBeenCalledWith(PRODUCT);
    });

    it('a product row opens it too; no product or a price on its way has no button', () => {
      const onCalculate = vi.fn();
      const [last] = priceColumns('normal', { prices: prices(), onCalculate }).slice(-1);
      render(<div>{last.renderProduct(7)}</div>);
      expect(screen.getByRole('button', { name: 'Calcular el precio del producto 7' })).toBeInTheDocument();
      const { container } = render(<div>{last.render(item(null))}</div>);
      expect(container.querySelector('button')).toBeNull();
      const [pending] = priceColumns('normal', { prices: prices(new Map(), true), onCalculate }).slice(-1);
      const other = render(<div>{pending.render(item())}</div>);
      expect(other.container.querySelector('button')).toBeNull();
    });

    it('without onCalculate (no price edit permission) there is no such column', () => {
      expect(priceColumns('normal', { prices: prices() }).map((column) => column.header)).not.toContain('Calcular');
    });
  });
  describe("Productos' markup con offsets (the clásica markup over the cost the offsets discount)", () => {
    const TP = { ...PRODUCT, costo: 800, moneda_costo: 'ARS', marca: 'TP-LINK' };
    const tenPercent = { id: 1, tipo_offset: 'porcentaje_costo', porcentaje: 10, marca: 'TP-LINK' };
    const offsets = (list = [tenPercent], tipoCambio = null) => ({ offsets: list, grupoFiltros: {}, canal: 'ml', tipoCambio });
    const clasicaOf = (product, options = {}) =>
      priceColumns(options.mode ?? 'normal', { prices: prices(new Map([[7, product]])), canSeeMargin: true, offsets: offsets(), ...options })[0];

    it('adds "→ x%" under the clásica markup, as Productos does: the same net price over the discounted cost', () => {
      // cost 800 less 10 % = 720; the price at 25 % over 800 is 1000, which is 38,89 % over 720
      render(<div>{clasicaOf(TP).render(item())}</div>);
      expect(screen.getByTitle('Markup con offsets aplicados')).toHaveTextContent('→ 38,9%');
      expect(cell(clasicaOf(TP, { mode: 'cuotas' }))).toContain('→ 38,9%');
    });

    it('a markup still negative after the offsets takes the danger tone, a positive one does not', () => {
      // -50 % over 800 is 400, which is -44,44 % over 720
      const { unmount } = render(<div>{clasicaOf({ ...TP, markup: -50 }).render(item())}</div>);
      const negative = screen.getByTitle('Markup con offsets aplicados');
      expect(negative).toHaveTextContent('→ -44,4%');
      expect(negative).toHaveAttribute('data-negative');
      unmount();
      render(<div>{clasicaOf(TP).render(item())}</div>);
      expect(screen.getByTitle('Markup con offsets aplicados')).not.toHaveAttribute('data-negative');
    });

    it('only on the clásica price: not on the other lists nor in the PVP mode', () => {
      const columns = priceColumns('normal', { prices: prices(new Map([[7, TP]])), canSeeMargin: true, offsets: offsets() });
      columns.slice(1).forEach((column) => expect(cell(column)).not.toContain('→'));
      expect(cell(clasicaOf(TP, { mode: 'pvp' }))).not.toContain('→');
    });

    it('none without the margin permission, without offsets that reach the product, or while they load', () => {
      expect(cell(clasicaOf(TP, { canSeeMargin: false }))).not.toContain('→');
      expect(cell(clasicaOf({ ...TP, marca: 'OTRA' }))).not.toContain('→');
      expect(cell(clasicaOf(TP, { offsets: null }))).not.toContain('→');
    });

    it('like the Precios tab: an offset that does not apply to Mercado Libre is left out', () => {
      expect(cell(clasicaOf(TP, { offsets: offsets([{ ...tenPercent, aplica_ml: false }]) }))).not.toContain('→');
    });

    it('a USD cost needs the USD rate: none without it, never an assumed one', () => {
      const usd = { ...TP, costo: 1, moneda_costo: 'USD' };
      expect(cell(clasicaOf(usd))).not.toContain('→');
      expect(cell(clasicaOf(usd, { offsets: offsets([tenPercent], 800) }))).toContain('→ 38,9%');
    });
  });
});
