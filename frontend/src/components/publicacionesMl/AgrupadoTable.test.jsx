/**
 * The Agrupado tree (publicaciones-ml-vista P12a): lazy nodes from
 * `/view/groups`, leaves from `/view/items` with the node's params, "Ver más",
 * node figures, and the variation sub-rows of a leaf MLA. Layout is the visual
 * suite's job.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useState } from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AgrupadoTable from './AgrupadoTable';
import { buildColumns } from './columns';
import { publicacionesMlAPI } from '../../services/api';
import {
  BRAND_NODES,
  PRODUCT_NODES,
  VARIATIONS_RESPONSE,
  VARIATION_ITEM,
  groupsResponse,
  makeItem,
  makeNode,
} from '../../test/visual/publicacionesMlFixtures';

vi.mock('../../services/api', () => ({
  publicacionesMlAPI: { items: vi.fn(), groups: vi.fn(), variations: vi.fn() },
}));

const FILTERS = {
  q: '',
  familia: '',
  evento_desde: '',
  estado: [],
  estado_excluir: [],
  tiendas: ['57997'],
  marcas: [],
  categorias: [],
  subcategorias: [],
  pms: [],
  tipo: [],
  vinculo: [],
  stock: [],
  evento: [],
  markup_neg: '',
  markup_min: '',
  markup_max: '',
  orden: '',
  dir: '',
  pagina: 1,
  limite: 50,
  sel: '',
};

const CATEGORY = makeNode({ kind: 'categoria', key: 'ROUTERS', label: 'ROUTERS', count: 90, params: { marcas: 'TP-LINK', categorias: 'ROUTERS' } });
const SUBCATEGORY = makeNode({
  kind: 'subcategoria',
  key: '55',
  label: 'Routers WiFi',
  count: 90,
  params: { marcas: 'TP-LINK', categorias: 'ROUTERS', subcategorias: '55' },
});

// Children by the `path` the tree asks for.
const TREE = {
  '': groupsResponse('marca', BRAND_NODES),
  'TP-LINK': groupsResponse('categoria', [CATEGORY]),
  'TP-LINK,ROUTERS': groupsResponse('subcategoria', [SUBCATEGORY]),
  'TP-LINK,ROUTERS,55': groupsResponse('producto', PRODUCT_NODES),
  'TP%2CLINK': groupsResponse('categoria', [makeNode({ kind: 'categoria', key: 'X', label: 'X', count: 7, params: {} })]),
};
const LEAF_ITEMS = {
  items: [
    makeItem({ item_id: 'MLA1', title: 'Router A', status: 'active' }),
    VARIATION_ITEM,
    makeItem({ item_id: 'MLA3', title: 'Router C' }),
  ],
  total: 3,
  limit: 100,
  offset: 0,
  can_see_margin: true,
  events_enabled: false,
  data_state: {},
};

const groupCalls = () => publicacionesMlAPI.groups.mock.calls.map(([params]) => params);
const itemCalls = () => publicacionesMlAPI.items.mock.calls.map(([params]) => params);
const httpError = (status) => Object.assign(new Error(`HTTP ${status}`), { response: { status } });

function Harness({ filters = FILTERS, familias = false, canSeeMargin = true, onSelectItem = () => {} }) {
  const [expandedIds, setExpandedIds] = useState(() => new Set());
  const toggle = (id) =>
    setExpandedIds((current) => {
      const next = new Set(current);
      if (!next.delete(id)) next.add(id);
      return next;
    });
  const columns = buildColumns({ eventsEnabled: false, canSeeMargin, expandedIds, onToggleVariations: toggle, agrupado: true });
  return (
    <AgrupadoTable
      columns={columns}
      filters={filters}
      familias={familias}
      canSeeMargin={canSeeMargin}
      expandedIds={expandedIds}
      onSelectItem={onSelectItem}
      selectedKey={filters.sel || undefined}
    />
  );
}

const open = async (user, name) => user.click(await screen.findByRole('button', { name }));
const rowOf = (text) => screen.getByText(text).closest('tr');

async function openToProducts(user) {
  await open(user, /Abrir TP-LINK/);
  await open(user, /Abrir ROUTERS/);
  await open(user, /Abrir Routers WiFi/);
  await screen.findByText('Router Archer AX55');
}

beforeEach(() => {
  publicacionesMlAPI.groups.mockReset();
  publicacionesMlAPI.items.mockReset();
  publicacionesMlAPI.variations.mockReset();
  publicacionesMlAPI.groups.mockImplementation(({ path = '' }) => Promise.resolve({ data: TREE[path] }));
  publicacionesMlAPI.items.mockResolvedValue({ data: LEAF_ITEMS });
  publicacionesMlAPI.variations.mockResolvedValue({ data: VARIATIONS_RESPONSE });
});

describe('the roots', () => {
  it('asks for the first 100 brands under the user filters, with no path', async () => {
    render(<Harness />);
    await screen.findByText('EPSON');
    expect(groupCalls()).toEqual([{ tiendas: '57997', familias: false, limit: 100, offset: 0 }]);
    expect(screen.getByText('TP,LINK')).toBeInTheDocument();
  });

  it('shows "Sin marca" like any node, and the count of each', async () => {
    render(<Harness />);
    const none = (await screen.findByText('Sin marca')).closest('tr');
    expect(within(none).getByText('25')).toBeInTheDocument();
    expect(within(rowOf('EPSON')).getByText('60')).toBeInTheDocument();
  });

  it('says so when there is nothing', async () => {
    publicacionesMlAPI.groups.mockResolvedValue({ data: groupsResponse('marca', []) });
    render(<Harness />);
    expect(await screen.findByText('Ninguna publicación coincide con los filtros')).toBeInTheDocument();
  });

  it('shows an error with a retry, and the retry asks again', async () => {
    const user = userEvent.setup();
    publicacionesMlAPI.groups.mockRejectedValueOnce(httpError(503));
    render(<Harness />);
    expect(await screen.findByText(/La consulta tardó demasiado/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Reintentar' }));
    await screen.findByText('EPSON');
    expect(groupCalls()).toHaveLength(2);
  });
});

describe('opening nodes', () => {
  it('asks for the children of the node by its path, indented one level', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await open(user, /Abrir TP-LINK/);
    await screen.findByText('ROUTERS');
    expect(groupCalls().at(-1)).toMatchObject({ path: 'TP-LINK', tiendas: '57997', limit: 100, offset: 0 });
    expect(rowOf('ROUTERS').style.getPropertyValue('--indent')).toBe('1');
    expect(rowOf('EPSON').style.getPropertyValue('--indent')).toBe('0');
  });

  it('sends an escaped key back exactly as it came', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await open(user, /Abrir TP,LINK/);
    await waitFor(() => expect(groupCalls().at(-1).path).toBe('TP%2CLINK'));
  });

  it('collapses and reopens without asking again', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await open(user, /Abrir TP-LINK/);
    await screen.findByText('ROUTERS');
    await user.click(screen.getByRole('button', { name: /Cerrar TP-LINK/ }));
    expect(screen.queryByText('ROUTERS')).not.toBeInTheDocument();
    await open(user, /Abrir TP-LINK/);
    expect(screen.getByText('ROUTERS')).toBeInTheDocument();
    expect(groupCalls()).toHaveLength(2);
  });

  it('opens a node with a click on its row too', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(await screen.findByText('EPSON'));
    await waitFor(() => expect(groupCalls().at(-1).path).toBe('EPSON'));
  });

  it('shows a loading row under the node while its children come', async () => {
    const user = userEvent.setup();
    let release;
    publicacionesMlAPI.groups.mockImplementation(({ path = '' }) =>
      path === 'EPSON' ? new Promise((resolve) => { release = () => resolve({ data: groupsResponse('categoria', []) }); }) : Promise.resolve({ data: TREE[path] }),
    );
    render(<Harness />);
    await user.click(await screen.findByText('EPSON'));
    expect(await screen.findByRole('status')).toHaveTextContent('Cargando');
    release();
    expect(await screen.findByText('Sin publicaciones con los filtros actuales')).toBeInTheDocument();
  });
});

describe('leaves', () => {
  it('lists "Sin producto" as its own node, after the products', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await openToProducts(user);
    const names = screen.getAllByRole('row').map((row) => row.textContent);
    const archer = names.findIndex((text) => text.includes('Router Archer AX55'));
    const none = names.findIndex((text) => text.includes('Sin producto'));
    expect(archer).toBeGreaterThan(-1);
    expect(none).toBeGreaterThan(archer);
  });

  it("fetches a leaf's publications from /items with the node's params over the user's, 100 at a time", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await openToProducts(user);
    await open(user, /Abrir Router Archer AX55/);
    await screen.findByText('Router A');
    expect(itemCalls().at(-1)).toEqual({
      tiendas: '57997',
      marcas: 'TP-LINK',
      categorias: 'ROUTERS',
      subcategorias: '55',
      producto: '4101',
      limit: 100,
      offset: 0,
    });
    expect(rowOf('Router A').style.getPropertyValue('--indent')).toBe('4');
  });

  it('opens "Sin producto" with sin_producto', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await openToProducts(user);
    await open(user, /Abrir Sin producto/);
    await waitFor(() => expect(itemCalls().at(-1)).toMatchObject({ sin_producto: 'true' }));
    expect(itemCalls().at(-1)).not.toHaveProperty('producto');
  });

  it('keeps the variation sub-rows of a publication with several variations', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await openToProducts(user);
    await open(user, /Abrir Router Archer AX55/);
    await user.click(await screen.findByRole('button', { name: /variaciones de MLA1100000005/ }));
    expect(await screen.findByText('Variación 9002')).toBeInTheDocument();
    expect(publicacionesMlAPI.variations).toHaveBeenCalledWith('MLA1100000005');
  });

  it('highlights one row for the selected MLA', async () => {
    const user = userEvent.setup();
    render(<Harness filters={{ ...FILTERS, sel: 'MLA3' }} />);
    await openToProducts(user);
    await open(user, /Abrir Router Archer AX55/);
    await screen.findByText('Router C');
    expect(rowOf('Router C')).toHaveAttribute('aria-current', 'true');
    expect(rowOf('Router A')).not.toHaveAttribute('aria-current');
  });

  it('selects a publication with a click on its row', async () => {
    const user = userEvent.setup();
    const onSelectItem = vi.fn();
    render(<Harness onSelectItem={onSelectItem} />);
    await openToProducts(user);
    await open(user, /Abrir Router Archer AX55/);
    await user.click(await screen.findByText('Router C'));
    expect(onSelectItem).toHaveBeenCalledWith(expect.objectContaining({ item_id: 'MLA3' }), expect.anything());
  });
});

describe('"Ver más"', () => {
  const page = (from, n) => Array.from({ length: n }, (_, i) => makeNode({ key: `B${from + i}`, label: `Marca ${from + i}`, params: { marcas: `B${from + i}` } }));

  it('loads the next 100 and goes away when everything is in', async () => {
    const user = userEvent.setup();
    publicacionesMlAPI.groups.mockImplementation(({ offset }) =>
      Promise.resolve({ data: groupsResponse('marca', page(offset, offset === 0 ? 100 : 50), { total: 150, offset }) }),
    );
    render(<Harness />);
    await screen.findByText('Marca 0');
    await user.click(screen.getByRole('button', { name: /Ver más/ }));
    await screen.findByText('Marca 149');
    expect(groupCalls().map((c) => c.offset)).toEqual([0, 100]);
    expect(screen.getByText('Marca 0')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Ver más/ })).not.toBeInTheDocument();
  });

  it('pages the publications of a leaf by 100 too', async () => {
    const user = userEvent.setup();
    publicacionesMlAPI.items.mockImplementation(({ offset }) =>
      Promise.resolve({
        data: {
          ...LEAF_ITEMS,
          items: Array.from({ length: offset === 0 ? 100 : 1 }, (_, i) =>
            makeItem({ item_id: `MLA${offset + i + 1}`, title: `Pub ${offset + i + 1}` }),
          ),
          total: 101,
        },
      }),
    );
    render(<Harness />);
    await openToProducts(user);
    await open(user, /Abrir Router Archer AX55/);
    await screen.findByText('Pub 1');
    await user.click(screen.getByRole('button', { name: /Ver más/ }));
    await screen.findByText('Pub 101');
    expect(itemCalls().map((c) => c.offset)).toEqual([0, 100]);
  });
});

describe('a page that overlaps the last one', () => {
  it('lists a publication once when it moved between "Ver más" requests', async () => {
    const user = userEvent.setup();
    const item = (n) => makeItem({ item_id: `MLA${n}`, title: `Pub ${n}` });
    publicacionesMlAPI.items.mockImplementation(({ offset }) =>
      Promise.resolve({
        data: {
          ...LEAF_ITEMS,
          items: offset === 0 ? Array.from({ length: 100 }, (_, i) => item(i + 1)) : [item(100), item(101)],
          total: 101,
        },
      }),
    );
    render(<Harness />);
    await openToProducts(user);
    await open(user, /Abrir Router Archer AX55/);
    await screen.findByText('Pub 1');
    await user.click(screen.getByRole('button', { name: /Ver más/ }));
    await screen.findByText('Pub 101');
    expect(screen.getAllByText('Pub 100')).toHaveLength(1);
  });
});

describe('node figures', () => {
  it('shows count, negativos and the markup range with ver_ganancia', async () => {
    render(<Harness />);
    const row = (await screen.findByText('TP-LINK')).closest('tr');
    expect(within(row).getByText('90')).toBeInTheDocument();
    expect(within(row).getByText('4')).toBeInTheDocument();
    expect(within(row).getByText(/-6,5%.*38,2%/)).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /Negativos/ })).toBeInTheDocument();
  });

  it('shows a real 0 negativos as 0 and a range with nothing to compute as "—"', async () => {
    render(<Harness />);
    const row = (await screen.findByText('TP,LINK')).closest('tr');
    expect(within(row).getByText('0')).toBeInTheDocument();
    expect(within(row).getAllByText('—').length).toBeGreaterThanOrEqual(1);
  });

  it('shows "—", never a number, when the backend sent no aggregates (P7b missing)', async () => {
    publicacionesMlAPI.groups.mockResolvedValue({ data: groupsResponse('marca', [makeNode()]) });
    render(<Harness />);
    const row = (await screen.findByText('TP-LINK')).closest('tr');
    expect(within(row).getAllByText('—').length).toBeGreaterThanOrEqual(2);
    expect(within(row).queryByText('0')).not.toBeInTheDocument();
  });

  it('has no negativos and no markup without ver_ganancia, even if the payload carried them', async () => {
    render(<Harness canSeeMargin={false} />);
    await screen.findByText('TP-LINK');
    expect(screen.queryByRole('columnheader', { name: /Negativos/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: /Markup/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/38,2%/)).not.toBeInTheDocument();
  });

  it('has no sort: the tree has no order to choose', async () => {
    render(<Harness />);
    await screen.findByText('TP-LINK');
    expect(screen.queryAllByRole('columnheader').flatMap((th) => within(th).queryAllByRole('button'))).toEqual([]);
  });
});

describe('what resets the tree', () => {
  it('starts over, collapsed, when a filter changes', async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Harness />);
    await open(user, /Abrir TP-LINK/);
    await screen.findByText('ROUTERS');
    rerender(<Harness filters={{ ...FILTERS, tiendas: ['471846'] }} />);
    await waitFor(() => expect(screen.queryByText('ROUTERS')).not.toBeInTheDocument());
    await screen.findByText('EPSON');
    expect(groupCalls().at(-1)).toEqual({ tiendas: '471846', familias: false, limit: 100, offset: 0 });
  });

  it('asks for families when the toggle is on, and starts over', async () => {
    const { rerender } = render(<Harness />);
    await screen.findByText('EPSON');
    rerender(<Harness familias />);
    await waitFor(() => expect(groupCalls().at(-1).familias).toBe(true));
  });

  it('does not restart for the selection', async () => {
    const { rerender } = render(<Harness />);
    await screen.findByText('EPSON');
    rerender(<Harness filters={{ ...FILTERS, sel: 'MLA3' }} />);
    expect(groupCalls()).toHaveLength(1);
  });

  it('ignores an answer that arrives after the filters changed', async () => {
    let releaseFirst;
    publicacionesMlAPI.groups
      .mockImplementationOnce(() => new Promise((resolve) => { releaseFirst = () => resolve({ data: groupsResponse('marca', [makeNode({ key: 'OLD', label: 'VIEJA' })]) }); }))
      .mockImplementation(({ path = '' }) => Promise.resolve({ data: TREE[path] }));
    const { rerender } = render(<Harness />);
    rerender(<Harness filters={{ ...FILTERS, tiendas: ['471846'] }} />);
    await screen.findByText('EPSON');
    releaseFirst();
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(screen.queryByText('VIEJA')).not.toBeInTheDocument();
  });
});
