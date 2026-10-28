import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProductoMLAsPanel from './ProductoMLAsPanel';
import { productosAPI } from '../../services/api';
import { useTreeViewStore } from '../../store/treeViewStore';

vi.mock('../../services/api', () => ({
  productosAPI: {
    getProductoMercadolibre: vi.fn(),
    getProductoTree: vi.fn(),
  },
  promocionesAPI: {
    getPromocionesItem: vi.fn().mockResolvedValue({ data: { promotions: [] } }),
    refreshItemPromociones: vi.fn().mockResolvedValue({ data: { ok: true } }),
    confirmarSinPromosML: vi.fn(() => Promise.resolve({ data: { sin_promos_confirmado: true, promos_en_ml: 0 } })),
  },
}));

function renderPanel(props = {}) {
  const mlasCacheRef = { current: new Map() };
  const promosCacheRef = { current: new Map() };
  return render(
    <table>
      <tbody>
        <tr>
          <td>
            <ProductoMLAsPanel
              itemId="ITEM001"
              mlasCacheRef={mlasCacheRef}
              promosCacheRef={promosCacheRef}
              {...props}
            />
          </td>
        </tr>
      </tbody>
    </table>,
  );
}

function treeResponse(children = [], overrides = {}) {
  return {
    data: {
      item_id: 1,
      tree: { level: 0, kind: 'producto', label: 'Producto', children },
      skipped_anomalous_edges: 0,
      skipped_edges: [],
      ...overrides,
    },
  };
}

describe('ProductoMLAsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useTreeViewStore.setState({ showFamilia: false });
  });

  it('shows a loading state while the fetch is in flight', async () => {
    let resolveFetch;
    productosAPI.getProductoTree.mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve;
      }),
    );

    renderPanel();
    expect(screen.getByText(/cargando publicaciones/i)).toBeInTheDocument();

    resolveFetch(treeResponse([]));
    await waitFor(() => expect(screen.queryByText(/cargando publicaciones/i)).not.toBeInTheDocument());
  });

  it('renders the recursive tree from the tree endpoint', async () => {
    useTreeViewStore.setState({ showFamilia: true });
    productosAPI.getProductoTree.mockResolvedValue(
      treeResponse([
        { level: 1, kind: 'publicacion', mla: 'MLA001', label: 'MLA001', matches_filter: true, children: [] },
        {
          level: 1,
          kind: 'familia',
          family_id: 'FAM1',
          label: 'Familia FAM1',
          children: [
            { level: 2, kind: 'catalogo', mla: 'MLA002', label: 'MLA002', matches_filter: true, children: [] },
          ],
        },
      ]),
    );

    renderPanel();

    await waitFor(() => expect(screen.getByText('MLA001')).toBeInTheDocument());
    expect(screen.getByText(/familia fam1/i)).toBeInTheDocument();
  });

  it('shows an error state distinct from empty', async () => {
    productosAPI.getProductoTree.mockRejectedValue(new Error('network error'));

    renderPanel();

    await waitFor(() => expect(screen.getByText(/error al cargar publicaciones/i)).toBeInTheDocument());
  });

  it('shows an empty state when the tree has zero children', async () => {
    productosAPI.getProductoTree.mockResolvedValue(treeResponse([]));

    renderPanel();

    await waitFor(() => expect(screen.getByText(/sin publicaciones/i)).toBeInTheDocument());
  });

  it('does not re-fetch when re-mounted with the same cached itemId', async () => {
    productosAPI.getProductoTree.mockResolvedValue(
      treeResponse([{ level: 1, kind: 'publicacion', mla: 'MLA001', label: 'MLA001', matches_filter: true, children: [] }]),
    );

    const mlasCacheRef = { current: new Map() };
    const promosCacheRef = { current: new Map() };

    const { unmount } = render(
      <ProductoMLAsPanel itemId="ITEM001" mlasCacheRef={mlasCacheRef} promosCacheRef={promosCacheRef} />,
    );
    await waitFor(() => expect(screen.getByText('MLA001')).toBeInTheDocument());
    unmount();

    render(
      <ProductoMLAsPanel itemId="ITEM001" mlasCacheRef={mlasCacheRef} promosCacheRef={promosCacheRef} />,
    );
    await waitFor(() => expect(screen.getByText('MLA001')).toBeInTheDocument());

    expect(productosAPI.getProductoTree).toHaveBeenCalledTimes(1);
  });

  it('expanding a leaf node lazily mounts the L2 promotions panel via its own sub-spoiler', async () => {
    productosAPI.getProductoTree.mockResolvedValue(
      treeResponse([{ level: 1, kind: 'publicacion', mla: 'MLA001', label: 'MLA001', matches_filter: true, children: [] }]),
    );

    renderPanel();
    await waitFor(() => expect(screen.getByText('MLA001')).toBeInTheDocument());

    const { promocionesAPI } = await import('../../services/api');
    expect(promocionesAPI.getPromocionesItem).not.toHaveBeenCalled();

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /expandir mla001/i }));
    await user.click(screen.getByRole('button', { name: /^promociones/i }));

    await waitFor(() => expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledWith('MLA001'));
  });

  it('hides matches_filter:false nodes with a "ver todos (N)" escape hatch, consistent with the flat panel', async () => {
    productosAPI.getProductoTree.mockResolvedValue(
      treeResponse([
        { level: 1, kind: 'publicacion', mla: 'MLA001', label: 'MLA001', matches_filter: true, children: [] },
        { level: 1, kind: 'publicacion', mla: 'MLA002', label: 'MLA002', matches_filter: false, children: [] },
        { level: 1, kind: 'publicacion', mla: 'MLA003', label: 'MLA003', matches_filter: false, children: [] },
      ]),
    );

    renderPanel({ promoTipos: ['SELLER_CAMPAIGN'], promoEstado: 'aplicada' });

    await waitFor(() => expect(screen.getByText('MLA001')).toBeInTheDocument());
    expect(screen.queryByText('MLA002')).not.toBeInTheDocument();
    expect(screen.queryByText('MLA003')).not.toBeInTheDocument();
    expect(screen.getByText(/ver todos \(2\)/i)).toBeInTheDocument();
  });

  it('clicking "ver todos (N)" reveals hidden nodes at any depth', async () => {
    productosAPI.getProductoTree.mockResolvedValue(
      treeResponse([
        {
          level: 1,
          kind: 'familia',
          label: 'Familia FAM1',
          children: [
            { level: 2, kind: 'catalogo', mla: 'MLA_HIDDEN', label: 'MLA_HIDDEN', matches_filter: false, children: [] },
          ],
        },
      ]),
    );

    renderPanel({ promoTipos: ['SELLER_CAMPAIGN'], promoEstado: 'aplicada' });

    await waitFor(() => expect(screen.getByText(/ver todos \(1\)/i)).toBeInTheDocument());
    expect(screen.queryByText('MLA_HIDDEN')).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByText(/ver todos \(1\)/i));

    // With familia hidden (default), its catalogo child is hoisted directly
    // and its header (with the label) renders without needing an extra
    // expand click.
    expect(screen.getByText('MLA_HIDDEN')).toBeInTheDocument();
  });

  it('forwards promo_tipos/promo_estado to the tree fetch when a filter is active', async () => {
    productosAPI.getProductoTree.mockResolvedValue(
      treeResponse([{ level: 1, kind: 'publicacion', mla: 'MLA001', label: 'MLA001', matches_filter: true, children: [] }]),
    );

    renderPanel({ promoTipos: ['SELLER_CAMPAIGN', 'DEAL'], promoEstado: 'aplicada' });

    await waitFor(() => expect(screen.getByText('MLA001')).toBeInTheDocument());
    expect(productosAPI.getProductoTree).toHaveBeenCalledWith(
      'ITEM001',
      expect.objectContaining({ promo_tipos: 'SELLER_CAMPAIGN,DEAL', promo_estado: 'aplicada' }),
    );
  });

  it('does not forward promo params when no filter is active', async () => {
    productosAPI.getProductoTree.mockResolvedValue(
      treeResponse([{ level: 1, kind: 'publicacion', mla: 'MLA001', label: 'MLA001', matches_filter: true, children: [] }]),
    );

    renderPanel();

    await waitFor(() => expect(screen.getByText('MLA001')).toBeInTheDocument());
    expect(productosAPI.getProductoTree).toHaveBeenCalledWith('ITEM001', {});
  });

  it('uses a composite cache key (itemId::filterKey) so different filters do not collide', async () => {
    productosAPI.getProductoTree
      .mockResolvedValueOnce(
        treeResponse([{ level: 1, kind: 'publicacion', mla: 'MLA_ALL', label: 'MLA_ALL', matches_filter: true, children: [] }]),
      )
      .mockResolvedValueOnce(
        treeResponse([{ level: 1, kind: 'publicacion', mla: 'MLA_FILTERED', label: 'MLA_FILTERED', matches_filter: true, children: [] }]),
      );

    const mlasCacheRef = { current: new Map() };
    const promosCacheRef = { current: new Map() };

    const { rerender } = render(
      <table>
        <tbody>
          <tr>
            <td>
              <ProductoMLAsPanel itemId="ITEM001" mlasCacheRef={mlasCacheRef} promosCacheRef={promosCacheRef} />
            </td>
          </tr>
        </tbody>
      </table>,
    );
    await waitFor(() => expect(screen.getByText('MLA_ALL')).toBeInTheDocument());

    rerender(
      <table>
        <tbody>
          <tr>
            <td>
              <ProductoMLAsPanel
                itemId="ITEM001"
                mlasCacheRef={mlasCacheRef}
                promosCacheRef={promosCacheRef}
                promoTipos={['SELLER_CAMPAIGN']}
                promoEstado="aplicada"
              />
            </td>
          </tr>
        </tbody>
      </table>,
    );

    await waitFor(() => expect(screen.getByText('MLA_FILTERED')).toBeInTheDocument());
    expect(productosAPI.getProductoTree).toHaveBeenCalledTimes(2);
    expect(mlasCacheRef.current.size).toBe(2);
  });

  it('shows the "Ver familias" toggle only when the tree has a familia node among the root children', async () => {
    productosAPI.getProductoTree.mockResolvedValue(
      treeResponse([{ level: 1, kind: 'publicacion', mla: 'MLA001', label: 'MLA001', matches_filter: true, children: [] }]),
    );

    renderPanel();

    await waitFor(() => expect(screen.getByText('MLA001')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /ver familias/i })).not.toBeInTheDocument();
  });

  it('toggling "Ver familias" reveals the familia header and hides it again', async () => {
    productosAPI.getProductoTree.mockResolvedValue(
      treeResponse([
        {
          level: 1,
          kind: 'familia',
          label: 'Familia FAM1',
          children: [
            { level: 2, kind: 'catalogo', mla: 'MLA002', label: 'MLA002', matches_filter: true, children: [] },
          ],
        },
      ]),
    );

    renderPanel();

    await waitFor(() => expect(screen.getByText('MLA002')).toBeInTheDocument());
    expect(screen.queryByText(/familia fam1/i)).not.toBeInTheDocument();

    const user = userEvent.setup();
    const toggle = screen.getByRole('button', { name: /ver familias/i });
    await user.click(toggle);

    expect(screen.getByText(/familia fam1/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /ocultar familias/i }));
    expect(screen.queryByText(/familia fam1/i)).not.toBeInTheDocument();
  });
});

describe('ProductoMLAsPanel — official store filter reaches the tree', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useTreeViewStore.setState({ showFamilia: false });
  });

  it('forwards tiendaOficial as the tiendas_oficiales tree param', async () => {
    // The product list filters by "has at least one publication in this
    // store", so a product with both a TP-Link and a Gauss MLA legitimately
    // matches the TP-Link filter. Without this param the expanded tree then
    // showed EVERY MLA of that product, Gauss included — the filter looked
    // broken because the MLA level never received it.
    productosAPI.getProductoTree.mockResolvedValue(treeResponse());

    renderPanel({ tiendaOficial: '2645' });

    await waitFor(() => expect(productosAPI.getProductoTree).toHaveBeenCalled());
    const [, params] = productosAPI.getProductoTree.mock.calls[0];
    expect(params).toMatchObject({ tiendas_oficiales: '2645' });
  });

  it('omits the param entirely when no store is selected', async () => {
    productosAPI.getProductoTree.mockResolvedValue(treeResponse());

    renderPanel({ tiendaOficial: null });

    await waitFor(() => expect(productosAPI.getProductoTree).toHaveBeenCalled());
    const [, params] = productosAPI.getProductoTree.mock.calls[0];
    expect(params).not.toHaveProperty('tiendas_oficiales');
  });

  it('refetches when the selected store changes instead of serving the cached tree', async () => {
    // The cache key is per (itemId, filters). If the store is not part of it,
    // switching stores would replay the previous store's tree from cache and
    // the filter would appear to do nothing.
    productosAPI.getProductoTree.mockResolvedValue(treeResponse());
    const mlasCacheRef = { current: new Map() };
    const promosCacheRef = { current: new Map() };

    const view = render(
      <table><tbody><tr><td>
        <ProductoMLAsPanel
          itemId="ITEM001"
          mlasCacheRef={mlasCacheRef}
          promosCacheRef={promosCacheRef}
          tiendaOficial="2645"
        />
      </td></tr></tbody></table>,
    );
    await waitFor(() => expect(productosAPI.getProductoTree).toHaveBeenCalledTimes(1));

    view.rerender(
      <table><tbody><tr><td>
        <ProductoMLAsPanel
          itemId="ITEM001"
          mlasCacheRef={mlasCacheRef}
          promosCacheRef={promosCacheRef}
          tiendaOficial="57997"
        />
      </td></tr></tbody></table>,
    );

    await waitFor(() => expect(productosAPI.getProductoTree).toHaveBeenCalledTimes(2));
    const [, params] = productosAPI.getProductoTree.mock.calls[1];
    expect(params).toMatchObject({ tiendas_oficiales: '57997' });
  });

  it('hides the deleted publications again when the filter changes, as "ver todos" does', async () => {
    productosAPI.getProductoTree.mockResolvedValue(
      treeResponse([
        { level: 1, kind: 'publicacion', mla: 'MLA_LIVE', label: 'MLA_LIVE', publication_status: 'active', children: [] },
        { level: 1, kind: 'publicacion', mla: 'MLA_GONE', label: 'MLA_GONE', publication_status: 'gone', children: [] },
      ]),
    );
    const refs = { mlasCacheRef: { current: new Map() }, promosCacheRef: { current: new Map() } };
    const panel = (tienda) => (
      <table><tbody><tr><td>
        <ProductoMLAsPanel itemId="ITEM001" {...refs} tiendaOficial={tienda} />
      </td></tr></tbody></table>
    );
    const view = render(panel('2645'));
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Ver eliminadas (1)' }));
    expect(screen.getByText('MLA_GONE')).toBeInTheDocument();

    view.rerender(panel('57997'));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Ver eliminadas (1)' })).toBeInTheDocument());
    expect(screen.queryByText('MLA_GONE')).not.toBeInTheDocument();
  });
});

describe('ProductoMLAsPanel — tree controls look like buttons', () => {
  // Own setup: without it this passed only by inheriting the mock the previous
  // describe happened to leave behind, and failed the moment it ran alone.
  beforeEach(() => {
    vi.clearAllMocks();
    productosAPI.getProductoTree.mockResolvedValue(
      treeResponse([{ level: 1, kind: 'publicacion', mla: 'MLA001', label: 'MLA001', matches_filter: true, children: [] }]),
    );
  });

  it('renders expandir/colapsar with a visible variant, not the invisible ghost one', async () => {
    const mlasCacheRef = { current: new Map() };
    const promosCacheRef = { current: new Map() };
    render(
      <ProductoMLAsPanel itemId="ITEM001" mlasCacheRef={mlasCacheRef} promosCacheRef={promosCacheRef} />,
    );

    const expandir = await screen.findByRole('button', { name: /expandir todo/i });
    const colapsar = screen.getByRole('button', { name: /colapsar todo/i });

    for (const button of [expandir, colapsar]) {
      expect(button.className).not.toMatch(/\bghost\b/);
      expect(button.className).toMatch(/outline-subtle-primary/);
    }
  });
});

describe('ProductoMLAsPanel — wholesale (PxQ) filter forwarding', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useTreeViewStore.setState({ showFamilia: false });
  });

  it('sends con_pxq to the tree endpoint when the filter is on', async () => {
    productosAPI.getProductoTree.mockResolvedValue(treeResponse([]));

    renderPanel({ conPxq: 'con_pxq' });

    await waitFor(() => expect(productosAPI.getProductoTree).toHaveBeenCalled());
    expect(productosAPI.getProductoTree).toHaveBeenCalledWith('ITEM001', expect.objectContaining({ con_pxq: true }));
  });

  it('sends no con_pxq when the filter is off', async () => {
    productosAPI.getProductoTree.mockResolvedValue(treeResponse([]));

    renderPanel();

    await waitFor(() => expect(productosAPI.getProductoTree).toHaveBeenCalled());
    expect(productosAPI.getProductoTree.mock.calls[0][1]).not.toHaveProperty('con_pxq');
  });

  it('hides a publication the backend excluded, with PxQ as the only active filter', async () => {
    productosAPI.getProductoTree.mockResolvedValue(
      treeResponse([
        { level: 1, kind: 'publicacion', mla: 'MLA_CON', label: 'MLA_CON', matches_filter: true, children: [] },
        { level: 1, kind: 'publicacion', mla: 'MLA_SIN', label: 'MLA_SIN', matches_filter: false, children: [] },
      ]),
    );

    renderPanel({ conPxq: 'con_pxq' });

    await waitFor(() => expect(screen.getByText(/MLA_CON/)).toBeTruthy());
    expect(screen.queryByText(/MLA_SIN/)).toBeNull();
  });

  it('hides deleted publications by default and shows them with "Ver eliminadas (N)"', async () => {
    productosAPI.getProductoTree.mockResolvedValue(
      treeResponse([
        { level: 1, kind: 'publicacion', mla: 'MLA_LIVE', label: 'MLA_LIVE', publication_status: 'active', children: [] },
        { level: 1, kind: 'publicacion', mla: 'MLA_GONE', label: 'MLA_GONE', publication_status: 'gone', children: [] },
        {
          level: 1,
          kind: 'publicacion',
          mla: 'MLA_DELETED',
          label: 'MLA_DELETED',
          publication_status: 'inactive',
          publication_sub_status: ['forbidden', 'deleted'],
          children: [],
        },
      ]),
    );

    renderPanel();

    await waitFor(() => expect(screen.getByText('MLA_LIVE')).toBeInTheDocument());
    expect(screen.queryByText('MLA_GONE')).not.toBeInTheDocument();
    expect(screen.queryByText('MLA_DELETED')).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Ver eliminadas (2)' }));
    expect(screen.getByText('MLA_GONE')).toBeInTheDocument();
    expect(screen.getByText('MLA_DELETED')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ocultar eliminadas' })).toHaveAttribute('aria-pressed', 'true');

    await user.click(screen.getByRole('button', { name: 'Ocultar eliminadas' }));
    expect(screen.queryByText('MLA_GONE')).not.toBeInTheDocument();
  });

  it('offers no "Ver eliminadas" when nothing is deleted', async () => {
    productosAPI.getProductoTree.mockResolvedValue(
      treeResponse([{ level: 1, kind: 'publicacion', mla: 'MLA_LIVE', label: 'MLA_LIVE', publication_status: 'active', children: [] }]),
    );
    renderPanel();
    await waitFor(() => expect(screen.getByText('MLA_LIVE')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /eliminadas/i })).not.toBeInTheDocument();
  });

  it('says so when every publication is deleted, with the way to see them', async () => {
    productosAPI.getProductoTree.mockResolvedValue(
      treeResponse([{ level: 1, kind: 'publicacion', mla: 'MLA_GONE', label: 'MLA_GONE', publication_status: 'gone', children: [] }]),
    );
    renderPanel();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Ver eliminadas (1)' })).toBeInTheDocument());
    expect(screen.getByText('Las publicaciones de este producto quedan ocultas por estar eliminadas.')).toBeInTheDocument();
    expect(screen.queryByText('MLA_GONE')).not.toBeInTheDocument();

    await userEvent.setup().click(screen.getByRole('button', { name: 'Ver eliminadas (1)' }));
    expect(screen.getByText('MLA_GONE')).toBeInTheDocument();
    expect(screen.queryByText('Las publicaciones de este producto quedan ocultas por estar eliminadas.')).not.toBeInTheDocument();
  });

  it('each button counts what it then shows when a filter and deleted publications meet', async () => {
    productosAPI.getProductoTree.mockResolvedValue(
      treeResponse([
        { level: 1, kind: 'publicacion', mla: 'MLA_OK', label: 'MLA_OK', publication_status: 'active', matches_filter: true, children: [] },
        { level: 1, kind: 'publicacion', mla: 'MLA_OUT', label: 'MLA_OUT', publication_status: 'active', matches_filter: false, children: [] },
        { level: 1, kind: 'publicacion', mla: 'MLA_GONE_OUT', label: 'MLA_GONE_OUT', publication_status: 'gone', matches_filter: false, children: [] },
        { level: 1, kind: 'publicacion', mla: 'MLA_GONE_IN', label: 'MLA_GONE_IN', publication_status: 'gone', matches_filter: true, children: [] },
      ]),
    );
    renderPanel({ tiendaOficial: '57997' });

    await waitFor(() => expect(screen.getByText('MLA_OK')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'ver todos (1)' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ver eliminadas (1)' })).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Ver eliminadas (1)' }));
    expect(screen.getByText('MLA_GONE_IN')).toBeInTheDocument();
    expect(screen.queryByText('MLA_GONE_OUT')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'ver todos (2)' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'ver todos (2)' }));
    expect(screen.getByText('MLA_OUT')).toBeInTheDocument();
    expect(screen.getByText('MLA_GONE_OUT')).toBeInTheDocument();
  });

  it('does not blame deleted publications for what the filter hides', async () => {
    productosAPI.getProductoTree.mockResolvedValue(
      treeResponse([
        { level: 1, kind: 'publicacion', mla: 'MLA_OUT', label: 'MLA_OUT', publication_status: 'active', matches_filter: false, children: [] },
        { level: 1, kind: 'publicacion', mla: 'MLA_GONE', label: 'MLA_GONE', publication_status: 'gone', matches_filter: true, children: [] },
      ]),
    );
    renderPanel({ tiendaOficial: '57997' });
    await waitFor(() => expect(screen.getByRole('button', { name: 'Ver eliminadas (1)' })).toBeInTheDocument());
    expect(screen.queryByText(/quedan ocultas por estar eliminadas/)).not.toBeInTheDocument();
  });

  it('hands onOpenPublication to its rows: each publication offers "Abrir <mla>"', async () => {
    productosAPI.getProductoTree.mockResolvedValue(
      treeResponse([{ level: 1, kind: 'publicacion', mla: 'MLA001', label: 'MLA001', matches_filter: true, children: [] }]),
    );
    const onOpenPublication = vi.fn();
    renderPanel({ onOpenPublication });
    await userEvent.click(await screen.findByRole('button', { name: 'Abrir MLA001' }));
    expect(onOpenPublication).toHaveBeenCalledWith('MLA001');
  });

  it('offers no "Abrir" without onOpenPublication, as Productos mounts it', async () => {
    productosAPI.getProductoTree.mockResolvedValue(
      treeResponse([{ level: 1, kind: 'publicacion', mla: 'MLA001', label: 'MLA001', matches_filter: true, children: [] }]),
    );
    renderPanel();
    await screen.findByText('MLA001');
    expect(screen.queryByRole('button', { name: /^Abrir / })).not.toBeInTheDocument();
  });
});
