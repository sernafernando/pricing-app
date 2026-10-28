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
});
