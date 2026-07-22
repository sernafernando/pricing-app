import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProductoMLAsPanel from './ProductoMLAsPanel';
import { productosAPI } from '../../services/api';

vi.mock('../../services/api', () => ({
  productosAPI: {
    getProductoMercadolibre: vi.fn(),
    getProductoTree: vi.fn(),
  },
  promocionesAPI: {
    getPromocionesItem: vi.fn().mockResolvedValue({ data: { promotions: [] } }),
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
    await user.click(screen.getByRole('button', { name: /expandir familia fam1/i }));

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
});
