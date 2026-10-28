/**
 * The Producto view of Publicaciones ML: the product rows of `/view/products` (Métricas ML's product rows over the
 * selected publications), each opening into its publications from `/view/items` with the row's params, cached, with
 * "Ver más". Layout is the visual suite's job.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useState } from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProductoTable from './ProductoTable';
import useProductRows from './useProductRows';
import { buildColumns } from './columns';
import { publicacionesMlAPI } from '../../services/api';
import { COST_LINES, PRODUCT_ROWS, makeItem, makeProductRow, productsResponse } from '../../test/visual/publicacionesMlFixtures';

vi.mock('../../services/api', () => ({
  publicacionesMlAPI: { items: vi.fn(), products: vi.fn(), variations: vi.fn() },
}));

const FILTERS = {
  q: '',
  familia: '',
  evento_desde: '',
  estado: ['active'],
  estado_excluir: [],
  tiendas: [],
  marcas: [],
  categorias: [],
  subcategorias: [],
  pms: [],
  tipo: [],
  vinculo: [],
  stock: [],
  evento: [],
  markup_neg: '1',
  markup_min: '',
  markup_max: '',
  orden: '',
  dir: '',
  pagina: 1,
  limite: 50,
  sel: '',
};

const itemsPage = (count, total = count, prefix = 'MLA') => ({
  items: Array.from({ length: count }, (_, i) => makeItem({ item_id: `${prefix}${i + 1}`, title: `Publicación ${prefix}${i + 1}` })),
  total,
  limit: 100,
  offset: 0,
  can_see_margin: true,
  events_enabled: false,
  data_state: {},
});

const productCalls = () => publicacionesMlAPI.products.mock.calls.map(([params]) => params);
const itemCalls = () => publicacionesMlAPI.items.mock.calls.map(([params]) => params);

function Harness({
  filters = FILTERS,
  canSeeSales = true,
  canSeeMargin = true,
  onSelectItem = () => {},
  onSelectProduct = () => {},
  onSort = () => {},
  selection,
  prices,
  prearmadasStats,
}) {
  const [expandedIds] = useState(() => new Set());
  const tree = useProductRows({ filters, pageSize: 50, canSeeSales, canSeeMargin });
  const columns = buildColumns({ eventsEnabled: false, canSeeMargin, canSeeSales, expandedIds, producto: true, prices });
  return (
    <>
      <span data-testid="total">{tree.total}</span>
      <ProductoTable
        tree={tree}
        columns={columns}
        canSeeMargin={canSeeMargin}
        expandedIds={expandedIds}
        onSelectItem={onSelectItem}
        onSelectProduct={onSelectProduct}
        selectedKey={filters.sel || undefined}
        selectedProductKey={filters.prod || undefined}
        prearmadasStats={prearmadasStats}
        listingById={prices?.byId}
        sort={tree.sort}
        onSort={onSort}
        selection={selection}
      />
    </>
  );
}

const rowOf = (text) => screen.getByText(text).closest('tr');
// Métricas ML's figures (`ml_metricas.ver`) and, among them, the margin ones (`ml_metricas.ver_ganancia`).
const FIGURE_HEADERS = ['7D', '30D', 'Facturado 30D', 'Total Gauss 30D', 'Real 30D', 'Última venta', 'Ageing'];
const MARGIN_HEADERS = ['Total Gauss 30D', 'Real 30D', 'Actual'];

beforeEach(() => {
  publicacionesMlAPI.products.mockReset();
  publicacionesMlAPI.items.mockReset();
  publicacionesMlAPI.products.mockResolvedValue({ data: productsResponse() });
  publicacionesMlAPI.items.mockResolvedValue({ data: itemsPage(3) });
});

describe('the product rows', () => {
  it("carry Productos' prearmadas and wholesale (PxQ) badges beside the product's name", async () => {
    publicacionesMlAPI.products.mockResolvedValue({
      data: productsResponse([makeProductRow({ pxq_tramos: 3, pxq_precio_desde: 37800 }), ...PRODUCT_ROWS.slice(1)]),
    });
    render(<Harness prearmadasStats={{ 4101: { exact: 2, upgrade: 0 }, 4102: { exact: 0, upgrade: 0 } }} />);
    const row = (await screen.findByText('Router Archer AX55')).closest('tr');
    expect(within(row).getByText('3 tramos · desde $37.800')).toBeInTheDocument();
    expect(within(row).getByText('2 listas')).toBeInTheDocument();
    const none = rowOf('Sin producto');
    expect(within(none).queryByText(/tramo/)).not.toBeInTheDocument(); // no tiers, no stats: no badges
    expect(within(none).queryByText(/lista/)).not.toBeInTheDocument();
  });

  it("carry Productos' catalog-competition badge beside the name, from the product's own listing (S4)", async () => {
    const prices = {
      byId: new Map([[4101, { item_id: 4101, has_catalog: true, catalog_status: 'competing', catalog_price_to_win: 870.1 }]]),
      loading: false,
      error: false,
    };
    render(<Harness prices={prices} />);
    const row = (await screen.findByText('Router Archer AX55')).closest('tr');
    expect(within(row).getByRole('img', { name: /^Catálogo: compitiendo/ })).toHaveAttribute('title', 'Precio para ganar: $870.10');
    // A product the listing has no catalog for (or no listing at all) has none.
    expect(within(rowOf('Sin producto')).queryByRole('img', { name: /^Catálogo/ })).not.toBeInTheDocument();
  });

  it('finds the listing of a product whose id arrives as text (the listing is keyed by number)', async () => {
    publicacionesMlAPI.products.mockResolvedValue({
      data: productsResponse([makeProductRow({ product_item_id: '4101' })]),
    });
    const prices = {
      byId: new Map([[4101, { item_id: 4101, has_catalog: true, catalog_status: 'winning', catalog_winner_price: 900 }]]),
      loading: false,
      error: false,
    };
    render(<Harness prices={prices} />);
    const row = (await screen.findByText('Router Archer AX55')).closest('tr');
    expect(within(row).getByRole('img', { name: /^Catálogo: ganando/ })).toBeInTheDocument();
  });

  it('asks /products once with the filters, the sort and the page -- never the markup filters', async () => {
    render(<Harness />);
    await screen.findByText('Router Archer AX55');
    expect(productCalls()).toEqual([{ estado: 'active', orden: 'facturado_30d', dir: 'desc', limit: 50, offset: 0 }]);
    expect(screen.getByTestId('total')).toHaveTextContent('3');
  });

  it('shows each product with its code, its publication count and its Métricas figures', async () => {
    render(<Harness />);
    const row = (await screen.findByText('Router Archer AX55')).closest('tr');
    expect(within(row).getAllByText(/ARCHER-AX55/).length).toBeGreaterThan(0); // the title cell, and the Código column
    expect(within(row).getByText('3')).toBeInTheDocument();
    expect(within(row).getByText('12.345')).toBeInTheDocument(); // units 30d
    expect(screen.getByText('Sin producto')).toBeInTheDocument();
  });

  it("fills the product's brand, ERP stock and cost columns, as Productos' rows carry them", async () => {
    render(<Harness />);
    const row = (await screen.findByText('Router Archer AX55')).closest('tr');
    expect(within(row).getByText('TP-LINK')).toBeInTheDocument();
    expect(within(row).getByText('12')).toBeInTheDocument(); // ERP stock
    expect(within(row).getByText('USD 45,50')).toBeInTheDocument();
    const none = rowOf('Sin producto');
    expect(within(none).queryByText('TP-LINK')).not.toBeInTheDocument();
    expect(within(none).queryByText(/USD/)).not.toBeInTheDocument();
  });

  it("shows the product's PPP and cost with sell in under its cost", async () => {
    publicacionesMlAPI.products.mockResolvedValue({ data: productsResponse([{ ...PRODUCT_ROWS[0], ...COST_LINES }, PRODUCT_ROWS[2]]) });
    render(<Harness />);
    const row = (await screen.findByText('Router Archer AX55')).closest('tr');
    expect(within(row).getByText(/^ppp: USD \$41\.20/)).toBeInTheDocument();
    expect(within(row).getByText('c/ sell in: ARS $63000.00')).toBeInTheDocument();
  });

  it('has no cost on a product row without ver_ganancia', async () => {
    render(<Harness canSeeMargin={false} />);
    const row = (await screen.findByText('Router Archer AX55')).closest('tr');
    expect(within(row).queryByText(/USD/)).not.toBeInTheDocument();
    expect(within(row).queryByText(/PPP|ppp|sell in/)).not.toBeInTheDocument();
    expect(within(row).getByText('TP-LINK')).toBeInTheDocument();
  });

  it('a product with no figures reads "—", never a made-up 0', async () => {
    publicacionesMlAPI.products.mockResolvedValue({ data: productsResponse([{ ...PRODUCT_ROWS[0], metrics: null }]) });
    render(<Harness />);
    const row = (await screen.findByText('Router Archer AX55')).closest('tr');
    expect(within(row).getAllByText('—').length).toBeGreaterThan(0);
    expect(within(row).queryByText('0')).not.toBeInTheDocument();
  });

  it('is sortable by the figures the products have, and not by the publication-only ones', async () => {
    const onSort = vi.fn();
    render(<Harness onSort={onSort} />);
    await screen.findByText('Router Archer AX55');
    await userEvent.click(screen.getByRole('button', { name: /^30D/ }));
    expect(onSort).toHaveBeenCalledWith('unidades_30d', expect.anything());
    expect(screen.queryByRole('button', { name: /^Precio/ })).not.toBeInTheDocument();
  });

  it("does not sort by Productos' price markups: /products has no such sort (the publications list does)", async () => {
    const prices = { byId: new Map([[4101, { item_id: 4101, precio_lista_ml: 2500, markup: 10 }]]), loading: false, error: false };
    render(<Harness prices={prices} canSeeMargin />);
    expect(await screen.findByRole('columnheader', { name: /Precio Clásica/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Precio Clásica/ })).not.toBeInTheDocument();
  });
});

describe("Productos' prices (S11)", () => {
  it("draws a product row with its own product's prices, and the \"Sin producto\" row with none", async () => {
    const prices = { byId: new Map([[4101, { item_id: 4101, precio_lista_ml: 2500 }]]), loading: false, error: false };
    render(<Harness prices={prices} />);
    const row = (await screen.findByText('Router Archer AX55')).closest('tr');
    expect(within(row).getByText('2.500,00')).toBeInTheDocument();
    expect(within(rowOf(/Sistema Mesh Deco X20/)).queryByText('2.500,00')).not.toBeInTheDocument();
    expect(within(rowOf('Sin producto')).queryByText('2.500,00')).not.toBeInTheDocument();
  });
});

describe('opening a product', () => {
  it('loads its publications from /items with its params over the filters, 100 at a time', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(await screen.findByRole('button', { name: /Abrir Router Archer AX55/ }));
    await screen.findByText('Publicación MLA1');
    expect(itemCalls()).toEqual([{ estado: 'active', producto: '4101', limit: 100, offset: 0 }]);
  });

  it('opens the "Sin producto" bucket with sin_producto', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(await screen.findByRole('button', { name: /Abrir Sin producto/ }));
    await waitFor(() => expect(itemCalls()).toEqual([{ estado: 'active', sin_producto: 'true', limit: 100, offset: 0 }]));
  });

  it('keeps what it loaded: closing and opening again asks for nothing', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const toggle = await screen.findByRole('button', { name: /Abrir Router Archer AX55/ });
    await user.click(toggle);
    await screen.findByText('Publicación MLA1');
    await user.click(screen.getByRole('button', { name: /Cerrar Router Archer AX55/ }));
    expect(screen.queryByText('Publicación MLA1')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Abrir Router Archer AX55/ }));
    expect(await screen.findByText('Publicación MLA1')).toBeInTheDocument();
    expect(itemCalls()).toHaveLength(1);
  });

  it('pages its publications with "Ver más"', async () => {
    publicacionesMlAPI.items.mockResolvedValueOnce({ data: itemsPage(100, 130) });
    publicacionesMlAPI.items.mockResolvedValueOnce({ data: itemsPage(30, 130, 'MLB') });
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(await screen.findByRole('button', { name: /Abrir Router Archer AX55/ }));
    await user.click(await screen.findByRole('button', { name: 'Ver más (30)' }));
    await screen.findByText('Publicación MLB30');
    expect(itemCalls()[1]).toMatchObject({ producto: '4101', offset: 100 });
    expect(screen.queryByRole('button', { name: /Ver más/ })).not.toBeInTheDocument();
  });

  it('a click on a publication selects it', async () => {
    const onSelectItem = vi.fn();
    const user = userEvent.setup();
    render(<Harness onSelectItem={onSelectItem} />);
    await user.click(await screen.findByRole('button', { name: /Abrir Router Archer AX55/ }));
    await user.click(await screen.findByText('Publicación MLA2'));
    expect(onSelectItem).toHaveBeenCalledWith(expect.objectContaining({ item_id: 'MLA2' }), expect.anything());
  });

  it('a click on a product opens its panel; the chevron expands it', async () => {
    const onSelectProduct = vi.fn();
    const user = userEvent.setup();
    render(<Harness onSelectProduct={onSelectProduct} />);
    await user.click(await screen.findByText('Router Archer AX55'));
    expect(onSelectProduct).toHaveBeenCalledWith('4101');
    expect(itemCalls()).toHaveLength(0);
    expect(screen.getByRole('button', { name: /Abrir Router Archer AX55/ })).toHaveAttribute('aria-expanded', 'false');

    await user.click(screen.getByRole('button', { name: /Abrir Router Archer AX55/ }));
    expect(await screen.findByText('Publicación MLA1')).toBeInTheDocument();
    expect(onSelectProduct).toHaveBeenCalledTimes(1);
  });

  it('Enter or Space on a focused product row opens its panel', async () => {
    const onSelectProduct = vi.fn();
    const user = userEvent.setup();
    render(<Harness onSelectProduct={onSelectProduct} />);
    await screen.findByText('Sin producto');
    rowOf('Sin producto').focus();
    await user.keyboard('{Enter}');
    expect(onSelectProduct).toHaveBeenLastCalledWith('0');
    rowOf('Router Archer AX55').focus();
    await user.keyboard(' ');
    expect(onSelectProduct).toHaveBeenLastCalledWith('4101');
    expect(itemCalls()).toHaveLength(0);
  });

  it('highlights the product whose panel is open, unless a publication is selected', async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Harness filters={{ ...FILTERS, prod: '4101' }} />);
    await screen.findByText('Router Archer AX55');
    expect(rowOf('Router Archer AX55')).toHaveAttribute('aria-current', 'true');
    expect(rowOf('Sin producto')).not.toHaveAttribute('aria-current');

    rerender(<Harness filters={{ ...FILTERS, prod: '4101', sel: 'MLA2' }} />);
    await user.click(screen.getByRole('button', { name: /Abrir Router Archer AX55/ }));
    await screen.findByText('Publicación MLA2');
    expect(rowOf('Router Archer AX55')).not.toHaveAttribute('aria-current');
    expect(rowOf('Publicación MLA2')).toHaveAttribute('aria-current', 'true');
  });

  it('a failed load says so and retries', async () => {
    publicacionesMlAPI.items.mockRejectedValueOnce(Object.assign(new Error('boom'), { response: { status: 503 } }));
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(await screen.findByRole('button', { name: /Abrir Router Archer AX55/ }));
    expect(await screen.findByText(/La consulta tardó demasiado/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Reintentar' }));
    expect(await screen.findByText('Publicación MLA1')).toBeInTheDocument();
  });
});

describe('a new product list', () => {
  it('starts collapsed when the filters change', async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Harness />);
    await user.click(await screen.findByRole('button', { name: /Abrir Router Archer AX55/ }));
    await screen.findByText('Publicación MLA1');
    rerender(<Harness filters={{ ...FILTERS, estado: ['paused'] }} />);
    await waitFor(() => expect(productCalls()).toHaveLength(2));
    await screen.findByText('Router Archer AX55');
    expect(screen.queryByText('Publicación MLA1')).not.toBeInTheDocument();
    expect(rowOf('Router Archer AX55')).toBeInTheDocument();
  });

  it('without ml_metricas.ver asks by name and shows no figures', async () => {
    publicacionesMlAPI.products.mockResolvedValue({ data: productsResponse(PRODUCT_ROWS.map((row) => ({ ...row, metrics: undefined }))) });
    render(<Harness canSeeSales={false} canSeeMargin={false} />);
    await screen.findByText('Router Archer AX55');
    expect(productCalls()[0]).toMatchObject({ orden: 'titulo', dir: 'asc' });
    const headers = screen.getAllByRole('columnheader').map((th) => th.textContent);
    for (const figure of FIGURE_HEADERS) expect(headers.some((text) => text.includes(figure)), figure).toBe(false);
    expect(screen.getByRole('columnheader', { name: /Publicaciones/ })).toBeInTheDocument();
    const row = rowOf('Router Archer AX55');
    expect(within(row).queryByText('12.345')).not.toBeInTheDocument(); // the fixture's units 30d
  });

  it('with ml_metricas.ver but without ver_ganancia shows the sales and no margin', async () => {
    render(<Harness canSeeSales canSeeMargin={false} />);
    await screen.findByText('Router Archer AX55');
    const headers = screen.getAllByRole('columnheader').map((th) => th.textContent);
    expect(headers.some((text) => text.includes('30D'))).toBe(true);
    for (const margin of MARGIN_HEADERS) expect(headers.some((text) => text.includes(margin)), margin).toBe(false);
    const row = rowOf('Router Archer AX55');
    expect(within(row).getByText('12.345')).toBeInTheDocument();
    expect(within(row).queryByText(/18,4/)).not.toBeInTheDocument(); // the fixture's real markup
  });
});

describe('the product checkbox', () => {
  // The tree's indentation is driven by depth alone: the toggle leads the pinned cell, the checkbox follows it,
  // so a branch's state and sub-rows line up one level under the toggle (pinned in the visual suite).
  it('follows the product toggle, never precedes it', async () => {
    render(<Harness selection={{ checked: new Set(), onToggle: () => {} }} />);
    const toggle = await screen.findByRole('button', { name: /Abrir Router Archer AX55/ });
    const box = within(rowOf('Router Archer AX55')).getByRole('checkbox');
    expect(toggle.compareDocumentPosition(box) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

describe('row colors (S8)', () => {
  it("paints a product with its layer's color and its publications with it, and hints the global one", async () => {
    const [first, second] = PRODUCT_ROWS;
    publicacionesMlAPI.products.mockResolvedValue({
      data: productsResponse([{ ...first, color_marcado: 'rojo' }, { ...second, color_hint_global: 'azul' }]),
    });
    publicacionesMlAPI.items.mockResolvedValue({ data: { ...itemsPage(1), items: [makeItem({ item_id: 'MLA1', title: 'Pintada', color_marcado: 'rojo' })] } });
    render(<Harness />);
    await screen.findByText(first.descripcion);
    const painted = rowOf(first.descripcion);
    expect(painted).toHaveAttribute('data-tone');
    expect(painted).toHaveAttribute('title', 'Color: Urgente');
    expect(rowOf(second.descripcion)).toHaveAttribute('data-marker');
    await userEvent.click(within(painted).getByRole('button', { name: `Abrir ${first.descripcion}` }));
    expect((await screen.findByText(/Pintada/)).closest('tr')).toHaveAttribute('data-tone');
  });
});
