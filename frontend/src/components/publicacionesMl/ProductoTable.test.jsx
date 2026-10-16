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
import { PRODUCT_ROWS, makeItem, productsResponse } from '../../test/visual/publicacionesMlFixtures';

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

function Harness({ filters = FILTERS, canSeeSales = true, canSeeMargin = true, onSelectItem = () => {}, onSort = () => {} }) {
  const [expandedIds] = useState(() => new Set());
  const tree = useProductRows({ filters, pageSize: 50, canSeeSales, canSeeMargin });
  const columns = buildColumns({ eventsEnabled: false, canSeeMargin, canSeeSales, expandedIds, producto: true });
  return (
    <>
      <span data-testid="total">{tree.total}</span>
      <ProductoTable
        tree={tree}
        columns={columns}
        canSeeMargin={canSeeMargin}
        expandedIds={expandedIds}
        onSelectItem={onSelectItem}
        selectedKey={filters.sel || undefined}
        sort={tree.sort}
        onSort={onSort}
      />
    </>
  );
}

const rowOf = (text) => screen.getByText(text).closest('tr');

beforeEach(() => {
  publicacionesMlAPI.products.mockReset();
  publicacionesMlAPI.items.mockReset();
  publicacionesMlAPI.products.mockResolvedValue({ data: productsResponse() });
  publicacionesMlAPI.items.mockResolvedValue({ data: itemsPage(3) });
});

describe('the product rows', () => {
  it('asks /products once with the filters, the sort and the page -- never the markup filters', async () => {
    render(<Harness />);
    await screen.findByText('Router Archer AX55');
    expect(productCalls()).toEqual([{ estado: 'active', orden: 'facturado_30d', dir: 'desc', limit: 50, offset: 0 }]);
    expect(screen.getByTestId('total')).toHaveTextContent('3');
  });

  it('shows each product with its code, its publication count and its Métricas figures', async () => {
    render(<Harness />);
    const row = (await screen.findByText('Router Archer AX55')).closest('tr');
    expect(within(row).getByText(/ARCHER-AX55/)).toBeInTheDocument();
    expect(within(row).getByText('3')).toBeInTheDocument();
    expect(within(row).getByText('12.345')).toBeInTheDocument(); // units 30d
    expect(screen.getByText('Sin producto')).toBeInTheDocument();
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
    expect(onSort).toHaveBeenCalledWith('unidades_30d');
    expect(screen.queryByRole('button', { name: /^Precio/ })).not.toBeInTheDocument();
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

  it('a click on a publication selects it; a click on a product opens it', async () => {
    const onSelectItem = vi.fn();
    const user = userEvent.setup();
    render(<Harness onSelectItem={onSelectItem} />);
    await user.click(await screen.findByText('Router Archer AX55'));
    await user.click(await screen.findByText('Publicación MLA2'));
    expect(onSelectItem).toHaveBeenCalledWith(expect.objectContaining({ item_id: 'MLA2' }), expect.anything());
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
  });
});
