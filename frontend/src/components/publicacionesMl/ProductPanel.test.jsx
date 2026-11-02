/**
 * ProductPanel: the side panel of one product of the Producto view. Its data comes from `useProductPanel` (mocked
 * here at that boundary); the panel draws the header, the summed figures the permissions allow, and the product's
 * publications: Productos' publication tree for a product (`ProductoMLAsPanel`, the real one over a mocked tree
 * endpoint), the flat list for "Sin producto", each one of its publications opening its own panel.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProductPanel from './ProductPanel';
import useProductPanel from './panel/useProductPanel';
import ProductoMLAsPanel from '../promociones/ProductoMLAsPanel';
import { productosAPI } from '../../services/api';
import { readProduct } from './useProductRows';
import { makeItem, makeProductRow, PRODUCT_ROWS } from '../../test/visual/publicacionesMlFixtures';

vi.mock('./panel/useProductPanel', async (importOriginal) => ({
  ...(await importOriginal()),
  default: vi.fn(),
}));

// The tree is the real component (so its controls are the ones Productos shows), wrapped to read its props; only
// its endpoint is mocked. The tiendas oficiales store reads `api.get` too.
vi.mock('../promociones/ProductoMLAsPanel', async (importOriginal) => {
  const Real = (await importOriginal()).default;
  return { default: vi.fn((props) => <Real {...props} />) };
});
vi.mock('../../services/api', async (importOriginal) => {
  const original = await importOriginal();
  return {
    ...original,
    default: { ...original.default, get: vi.fn(() => Promise.resolve({ data: [] })) },
    productosAPI: { ...original.productosAPI, getProductoTree: vi.fn() },
  };
});

let granted = new Set();
vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: (permiso) => granted.has(permiso) }),
}));

// Each mount of the prices is a fresh read of them; `readAgain` asks one more without remounting.
const pricesMounts = vi.hoisted(() => ({ count: 0 }));
vi.mock('../pricing/ProductPrices', async () => {
  const { useEffect } = await import('react');
  return {
    default: function ProductPricesMock({ productItemId, permissions, showCost, readAgain }) {
      useEffect(() => {
        pricesMounts.count += 1;
      }, []);
      return (
        <div data-testid="product-prices" data-read-again={readAgain}>
          {`prices of ${productItemId}, cost ${showCost ? 'shown' : 'hidden'}, clasica ${permissions.canEditClasica ? 'editable' : 'read-only'}`}
        </div>
      );
    },
  };
});

vi.mock('./panel/ProductIdentity', () => ({
  default: ({ productItemId }) => <div data-testid="product-identity">{`identity of ${productItemId}`}</div>,
}));

vi.mock('./panel/ProductChangesTab', () => ({
  default: ({ productItemId }) => <div data-testid="product-changes">{`changes of ${productItemId}`}</div>,
}));

vi.mock('./panel/ProductCuotasConfig', () => ({
  default: ({ productItemId, onRecalculated }) => (
    <div data-testid="product-cuotas">
      {`cuotas of ${productItemId}`}
      <button type="button" onClick={onRecalculated}>
        Simular recálculo
      </button>
    </div>
  ),
}));

vi.mock('./panel/ProductCatalogCompetition', () => ({
  default: ({ publications }) => (
    <div data-testid="product-catalog-competition">{`competition of ${publications.map((p) => p.item_id).join(',')}`}</div>
  ),
}));

vi.mock('./panel/ProductPrearmadas', () => ({
  default: ({ productItemId }) => <span data-testid="product-prearmadas">{`prearmadas of ${productItemId}`}</span>,
}));

vi.mock('./panel/ProductPxq', () => ({
  default: ({ publications }) => <div data-testid="product-pxq">{`pxq of ${publications.map((p) => p.item_id).join(',')}`}</div>,
}));

vi.mock('./panel/ProductPurchases', () => ({
  default: ({ productItemId }) => <div data-testid="product-purchases">{`purchases of ${productItemId}`}</div>,
}));

vi.mock('../sellIn/SellInLotes', () => ({
  default: ({ productItemId }) => <div data-testid="sell-in-lotes">{`lotes of ${productItemId}`}</div>,
}));

vi.mock('./panel/ProductBanAction', () => ({
  default: ({ productItemId, description }) => <div data-testid="product-ban">{`ban ${productItemId}: ${description}`}</div>,
}));

const FILTERS = { vista: 'producto', estado: ['active'] };
const SUMMARY = readProduct(makeProductRow());
const NO_PRODUCT = readProduct(PRODUCT_ROWS[2]);
const ITEMS = [
  makeItem({
    item_id: 'MLA1100000001',
    title: 'Router Archer AX55',
    status: 'active',
    price: { amount: 98500, source: 'sale_price', regular_amount: null },
    stock: { available: 34, full: 20, own: 14 },
    metrics: { units_30d: 41 },
    markup: { min: 12.5, max: 12.5, partial: 0 },
  }),
  makeItem({ item_id: 'MLA1100000002', title: 'Router Archer AX55 usado', status: 'paused' }),
];

function hookState(overrides = {}) {
  return {
    summary: SUMMARY,
    items: ITEMS,
    loading: false,
    error: null,
    reload: vi.fn(),
    loadMore: vi.fn(),
    hasMore: false,
    ...overrides,
  };
}

function renderPanel({ state = hookState(), productKey = '4101', ...props } = {}) {
  useProductPanel.mockReturnValue(state);
  const handlers = { onClose: vi.fn(), onSelectItem: vi.fn() };
  const panel = (key) => <ProductPanel filters={FILTERS} productKey={key} canSeeSales canSeeMargin {...handlers} {...props} />;
  const { rerender } = render(panel(productKey));
  return { ...handlers, state, reopen: (key) => rerender(panel(key)) };
}

const figures = () => screen.queryByRole('region', { name: 'Cifras' });

describe('ProductPanel', () => {
  beforeEach(() => {
    useProductPanel.mockReset();
    ProductoMLAsPanel.mockClear();
    // An empty tree unless a test gives one.
    productosAPI.getProductoTree.mockReset();
    productosAPI.getProductoTree.mockResolvedValue({ data: { item_id: 4101, tree: { level: 0, kind: 'producto', children: [] } } });
    granted = new Set(['productos.ver']);
  });

  it('asks the hook for the product under the page filters', () => {
    renderPanel();
    expect(useProductPanel).toHaveBeenCalledWith(FILTERS, '4101');
  });

  it('names the product and shows its code, brand and publication count', () => {
    renderPanel();
    expect(screen.getByRole('heading', { level: 2, name: 'Router Archer AX55' })).toBeInTheDocument();
    expect(screen.getByText('ARCHER-AX55')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copiar código' })).toBeInTheDocument();
    expect(screen.getByText('TP-LINK')).toBeInTheDocument();
    expect(screen.getByText('3 publicaciones')).toBeInTheDocument();
  });

  it('closes from the header', async () => {
    const { onClose } = renderPanel();
    await userEvent.click(screen.getByRole('button', { name: 'Cerrar panel' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('draws the summed figures with the current filters, margin included', () => {
    renderPanel();
    const region = figures();
    expect(region).toBeInTheDocument();
    expect(within(region).getByText('Con los filtros actuales')).toBeInTheDocument();
    expect(within(region).getByText('Ventas 30D')).toBeInTheDocument();
    expect(within(region).getByText('12.345')).toBeInTheDocument();
    expect(within(region).getByText('Facturado 30D')).toBeInTheDocument();
    expect(within(region).getByText('Markup real 30D')).toBeInTheDocument();
    expect(within(region).getByText('Total Gauss 30D')).toBeInTheDocument();
  });

  it('hides the margin figures without the margin permission', () => {
    renderPanel({ canSeeMargin: false });
    const region = figures();
    expect(within(region).getByText('Facturado 30D')).toBeInTheDocument();
    expect(within(region).queryByText('Markup real 30D')).not.toBeInTheDocument();
    expect(within(region).queryByText('Tendencia de markup')).not.toBeInTheDocument();
    expect(within(region).queryByText('Total Gauss 30D')).not.toBeInTheDocument();
    expect(screen.queryByText('12,5%')).not.toBeInTheDocument();
  });

  it('has no figures without the metrics permission', () => {
    renderPanel({ canSeeSales: false, canSeeMargin: false });
    expect(figures()).not.toBeInTheDocument();
    expect(screen.queryByText('41')).not.toBeInTheDocument();
  });

  it('lists the publications of "Sin producto" and opens the one clicked', async () => {
    const { onSelectItem } = renderPanel({ productKey: '0', state: hookState({ summary: NO_PRODUCT }) });
    const list = screen.getByRole('region', { name: 'Publicaciones' });
    const first = within(list).getByRole('button', { name: /MLA1100000001/ });
    expect(within(first).getByText('Router Archer AX55')).toBeInTheDocument();
    expect(within(first).getByText('Activa')).toBeInTheDocument();
    expect(within(first).getByText('41')).toBeInTheDocument();
    expect(within(first).getByText('12,5%')).toBeInTheDocument();
    expect(within(list).getByRole('button', { name: /MLA1100000002/ })).toBeInTheDocument();
    await userEvent.click(first);
    expect(onSelectItem).toHaveBeenCalledWith('MLA1100000001');
  });

  it('asks for more publications of "Sin producto" while there are more', async () => {
    const { state } = renderPanel({ productKey: '0', state: hookState({ summary: NO_PRODUCT, hasMore: true }) });
    await userEvent.click(screen.getByRole('button', { name: 'Ver más' }));
    expect(state.loadMore).toHaveBeenCalledTimes(1);
  });

  it('has no "Ver más" when every publication of "Sin producto" is shown', () => {
    renderPanel({ productKey: '0', state: hookState({ summary: NO_PRODUCT }) });
    expect(screen.queryByRole('button', { name: 'Ver más' })).not.toBeInTheDocument();
  });

  it('shows "Sin producto" with only its figures and publications, no product fields', () => {
    renderPanel({ productKey: '0', state: hookState({ summary: NO_PRODUCT }) });
    expect(screen.getByRole('heading', { level: 2, name: 'Sin producto' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Copiar código' })).not.toBeInTheDocument();
    expect(screen.queryByText('TP-LINK')).not.toBeInTheDocument();
    expect(screen.getByText('2 publicaciones')).toBeInTheDocument();
    expect(figures()).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Publicaciones' })).toBeInTheDocument();
  });

  it('shows the SKU and EAN of the product under Resumen', () => {
    renderPanel();
    expect(screen.getByTestId('product-identity')).toHaveTextContent(`identity of ${SUMMARY.productoItemId}`);
  });

  it('shows the last purchases under Resumen, after the SKU and EAN', () => {
    renderPanel();
    const identity = screen.getByTestId('product-identity');
    const purchases = screen.getByTestId('product-purchases');
    expect(purchases).toHaveTextContent(`purchases of ${SUMMARY.productoItemId}`);
    expect(identity.compareDocumentPosition(purchases) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('shows the sell-in lots under Resumen, after the last purchases', () => {
    renderPanel();
    const purchases = screen.getByTestId('product-purchases');
    const lotes = screen.getByTestId('sell-in-lotes');
    expect(lotes).toHaveTextContent(`lotes of ${SUMMARY.productoItemId}`);
    expect(purchases.compareDocumentPosition(lotes) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('has no sell-in lots for "Sin producto"', () => {
    renderPanel({ state: hookState({ summary: NO_PRODUCT }), productKey: '0' });
    expect(screen.queryByTestId('sell-in-lotes')).not.toBeInTheDocument();
  });

  it('shows the catalog competition of the listed publications under Resumen, after them', () => {
    renderPanel();
    const competition = screen.getByTestId('product-catalog-competition');
    expect(competition).toHaveTextContent(`competition of ${ITEMS.map((item) => item.item_id).join(',')}`);
    const publications = screen.getByRole('heading', { name: 'Publicaciones' });
    expect(publications.compareDocumentPosition(competition) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('shows the catalog competition for "Sin producto" too: it belongs to each publication', () => {
    renderPanel({ state: hookState({ summary: NO_PRODUCT }), productKey: '0' });
    expect(screen.getByTestId('product-catalog-competition')).toBeInTheDocument();
  });

  it('shows the wholesale prices of the listed publications under Resumen, after the catalog competition', () => {
    renderPanel();
    const pxq = screen.getByTestId('product-pxq');
    expect(pxq).toHaveTextContent(`pxq of ${ITEMS.map((item) => item.item_id).join(',')}`);
    const competition = screen.getByTestId('product-catalog-competition');
    expect(competition.compareDocumentPosition(pxq) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("gives each Resumen section its own key, so switching products restarts every one of them", () => {
    const errors = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      renderPanel();
      const duplicated = errors.mock.calls.filter((args) => String(args[0]).includes('same key'));
      expect(duplicated).toEqual([]);
    } finally {
      errors.mockRestore();
    }
  });

  it("shows the product's prearmadas in the header, beside its brand", () => {
    renderPanel();
    expect(screen.getByTestId('product-prearmadas')).toHaveTextContent(`prearmadas of ${SUMMARY.productoItemId}`);
  });

  it('has no prearmadas for "Sin producto"', () => {
    renderPanel({ state: hookState({ summary: NO_PRODUCT }), productKey: '0' });
    expect(screen.queryByTestId('product-prearmadas')).not.toBeInTheDocument();
  });

  it('shows the wholesale prices for "Sin producto" too', () => {
    renderPanel({ state: hookState({ summary: NO_PRODUCT }), productKey: '0' });
    expect(screen.getByTestId('product-pxq')).toBeInTheDocument();
  });

  it('has no last purchases for "Sin producto"', () => {
    renderPanel({ state: hookState({ summary: NO_PRODUCT }), productKey: '0' });
    expect(screen.queryByTestId('product-purchases')).not.toBeInTheDocument();
  });

  it('has no SKU and EAN for "Sin producto"', () => {
    renderPanel({ state: hookState({ summary: NO_PRODUCT }), productKey: '0' });
    expect(screen.queryByTestId('product-identity')).not.toBeInTheDocument();
  });

  it('offers banning the product under Resumen, with its description', () => {
    renderPanel();
    expect(screen.getByTestId('product-ban')).toHaveTextContent(`ban ${SUMMARY.productoItemId}: ${SUMMARY.label}`);
  });

  it('offers no ban for "Sin producto"', () => {
    renderPanel({ state: hookState({ summary: NO_PRODUCT }), productKey: '0' });
    expect(screen.queryByTestId('product-ban')).not.toBeInTheDocument();
  });

  it('shows the skeleton while the product loads', () => {
    renderPanel({ state: hookState({ summary: null, items: [], loading: true }) });
    expect(screen.getByRole('status', { name: 'Cargando producto' })).toBeInTheDocument();
    expect(figures()).not.toBeInTheDocument();
  });

  it('says the publications of "Sin producto" are loading once its figures are there', () => {
    renderPanel({ productKey: '0', state: hookState({ summary: NO_PRODUCT, items: [], loading: true }) });
    expect(screen.queryByRole('status', { name: 'Cargando producto' })).not.toBeInTheDocument();
    expect(screen.getByText('Cargando publicaciones…')).toBeInTheDocument();
  });

  it('shows the error and retries', async () => {
    const error = { response: { status: 500 } };
    const { state } = renderPanel({ state: hookState({ summary: null, items: [], error }) });
    expect(screen.getByRole('alert')).toHaveTextContent('No se pudo cargar el producto.');
    await userEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
    expect(state.reload).toHaveBeenCalledTimes(1);
  });

  it('says so when the filters leave the product out', () => {
    renderPanel({ state: hookState({ summary: null, items: [] }) });
    expect(screen.getByText('Los filtros actuales no incluyen este producto.')).toBeInTheDocument();
    expect(figures()).not.toBeInTheDocument();
  });

  it('feeds the catalog competition and the wholesale prices of "Sin producto" its listed publications', () => {
    renderPanel({ productKey: '0', state: hookState({ summary: NO_PRODUCT }) });
    const ids = ITEMS.map((item) => item.item_id).join(',');
    expect(screen.getByTestId('product-catalog-competition')).toHaveTextContent(`competition of ${ids}`);
    expect(screen.getByTestId('product-pxq')).toHaveTextContent(`pxq of ${ids}`);
  });

  it('keeps the flat list for "Sin producto", with no tree: it has no product to read one of', () => {
    renderPanel({ productKey: '0', state: hookState({ summary: NO_PRODUCT }) });
    const section = screen.getByRole('region', { name: 'Publicaciones' });
    expect(within(section).getAllByRole('listitem')).toHaveLength(ITEMS.length);
    expect(ProductoMLAsPanel).not.toHaveBeenCalled();
    expect(productosAPI.getProductoTree).not.toHaveBeenCalled();
  });

  describe("a product's publications as Productos' tree", () => {
    const TREE = {
      data: {
        item_id: 4101,
        tree: {
          level: 0,
          kind: 'producto',
          label: 'Router Archer AX55',
          children: [{ level: 1, kind: 'publicacion', mla: 'MLA1100000001', label: 'MLA1100000001', children: [] }],
        },
        skipped_anomalous_edges: 0,
        skipped_edges: [],
      },
    };

    const treeProps = () => ProductoMLAsPanel.mock.lastCall[0];

    beforeEach(() => {
      productosAPI.getProductoTree.mockResolvedValue(TREE);
    });

    it("shows the tree of the product's item id, with Expandir todo and Colapsar todo, instead of the flat list", async () => {
      renderPanel();
      const section = screen.getByRole('region', { name: 'Publicaciones' });
      expect(await within(section).findByRole('button', { name: 'Expandir todo' })).toBeInTheDocument();
      expect(within(section).getByRole('button', { name: 'Colapsar todo' })).toBeInTheDocument();
      expect(within(section).getByText('MLA1100000001')).toBeInTheDocument();
      expect(within(section).queryByRole('list')).not.toBeInTheDocument();
      expect(treeProps()).toMatchObject({ itemId: SUMMARY.productoItemId });
      expect(productosAPI.getProductoTree).toHaveBeenCalledWith(SUMMARY.productoItemId, {});
    });

    it('opens a publication of the tree in its own panel, from its "Abrir" button', async () => {
      const { onSelectItem } = renderPanel();
      await userEvent.click(await screen.findByRole('button', { name: 'Abrir MLA1100000001' }));
      expect(onSelectItem).toHaveBeenCalledWith('MLA1100000001');
    });

    it("hands the tree the page's promo, store and wholesale filters, in the tree endpoint's terms", async () => {
      renderPanel({
        filters: { ...FILTERS, promo_tipos: ['DEAL', 'SMART'], promo_estado: 'aplicada', tiendas: ['57997', 'sin_tienda'], pxq: 'con_pxq' },
      });
      await waitFor(() => expect(productosAPI.getProductoTree).toHaveBeenCalled());
      expect(treeProps()).toMatchObject({
        itemId: SUMMARY.productoItemId,
        promoTipos: ['DEAL', 'SMART'],
        promoEstado: 'aplicada',
        tiendaOficial: '57997,sin_tienda',
        conPxq: true,
      });
      expect(productosAPI.getProductoTree).toHaveBeenCalledWith(SUMMARY.productoItemId, {
        promo_tipos: 'DEAL,SMART',
        promo_estado: 'aplicada',
        tiendas_oficiales: '57997,sin_tienda',
        con_pxq: true,
      });
    });

    it('hands the tree no filter when the page has none of those', async () => {
      renderPanel({ filters: { ...FILTERS, promo_tipos: [], promo_estado: '', tiendas: [], pxq: '' } });
      await waitFor(() => expect(productosAPI.getProductoTree).toHaveBeenCalledWith(SUMMARY.productoItemId, {}));
      expect(treeProps()).toMatchObject({ promoTipos: [], promoEstado: undefined, tiendaOficial: undefined, conPxq: false });
    });

    it('keeps feeding the catalog competition and the wholesale prices the listed publications, not the tree', async () => {
      renderPanel();
      await screen.findByRole('button', { name: 'Expandir todo' });
      const ids = ITEMS.map((item) => item.item_id).join(',');
      expect(screen.getByTestId('product-catalog-competition')).toHaveTextContent(`competition of ${ids}`);
      expect(screen.getByTestId('product-pxq')).toHaveTextContent(`pxq of ${ids}`);
    });
  });

  describe('tabs', () => {
    const tab = (name) => screen.queryByRole('tab', { name });

    it('opens on Resumen, with the figures and the publications', () => {
      renderPanel();
      expect(screen.getByRole('tablist', { name: 'Secciones del producto' })).toBeInTheDocument();
      expect(tab('Resumen')).toHaveAttribute('aria-selected', 'true');
      expect(tab('Precios')).toHaveAttribute('aria-selected', 'false');
      expect(figures()).toBeInTheDocument();
      expect(screen.getByRole('region', { name: 'Publicaciones' })).toBeInTheDocument();
      expect(screen.queryByTestId('product-prices')).not.toBeInTheDocument();
    });

    it("shows the product's prices on Precios, with the cost behind the margin permission", async () => {
      granted = new Set(['productos.ver', 'productos.editar_precio_clasica']);
      renderPanel();
      await userEvent.click(tab('Precios'));
      expect(tab('Precios')).toHaveAttribute('aria-selected', 'true');
      expect(screen.getByRole('tabpanel')).toHaveTextContent('prices of 4101, cost shown, clasica editable');
      expect(figures()).not.toBeInTheDocument();
    });

    it("shows the product's instalment settings on Precios, under its prices", async () => {
      renderPanel();
      await userEvent.click(tab('Precios'));
      const prices = screen.getByTestId('product-prices');
      const cuotas = screen.getByTestId('product-cuotas');
      expect(cuotas).toHaveTextContent('cuotas of 4101');
      expect(prices.compareDocumentPosition(cuotas) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it("a recalculation from the instalment settings reads the product's prices again, without remounting them, and reloads the list", async () => {
      const onListReload = vi.fn();
      renderPanel({ onListReload });
      await userEvent.click(tab('Precios'));
      const before = pricesMounts.count;
      expect(screen.getByTestId('product-prices')).toHaveAttribute('data-read-again', '0');

      await userEvent.click(screen.getByRole('button', { name: 'Simular recálculo' }));

      expect(screen.getByTestId('product-prices')).toHaveAttribute('data-read-again', '1');
      // A remount would drop a price edit the user has open beside the settings.
      expect(pricesMounts.count).toBe(before);
      expect(onListReload).toHaveBeenCalledTimes(1);
    });

    it('hides the cost on Precios without the margin permission', async () => {
      renderPanel({ canSeeMargin: false });
      await userEvent.click(tab('Precios'));
      expect(screen.getByTestId('product-prices')).toHaveTextContent('prices of 4101, cost hidden, clasica read-only');
    });

    it('moves between tabs with the arrow keys', async () => {
      renderPanel();
      tab('Resumen').focus();
      await userEvent.keyboard('{ArrowRight}');
      expect(tab('Precios')).toHaveAttribute('aria-selected', 'true');
      expect(tab('Precios')).toHaveFocus();
      await userEvent.keyboard('{Home}');
      expect(tab('Resumen')).toHaveAttribute('aria-selected', 'true');
    });

    it('has no Precios without a price permission', () => {
      granted = new Set();
      renderPanel();
      expect(tab('Resumen')).toBeInTheDocument();
      expect(tab('Precios')).not.toBeInTheDocument();
    });

    it('has no Precios for "Sin producto"', () => {
      renderPanel({ productKey: '0', state: hookState({ summary: NO_PRODUCT }) });
      expect(tab('Precios')).not.toBeInTheDocument();
      expect(figures()).toBeInTheDocument();
    });

    it("shows the product's changes made in the app on Cambios, with or without a price permission", async () => {
      granted = new Set();
      renderPanel();
      await userEvent.click(tab('Cambios'));
      expect(tab('Cambios')).toHaveAttribute('aria-selected', 'true');
      expect(screen.getByRole('tabpanel')).toHaveTextContent('changes of 4101');
      expect(figures()).not.toBeInTheDocument();
    });

    it('has no Cambios for "Sin producto"', () => {
      renderPanel({ productKey: '0', state: hookState({ summary: NO_PRODUCT }) });
      expect(tab('Cambios')).not.toBeInTheDocument();
    });

    it('goes back to Resumen when another product is opened', async () => {
      const { reopen } = renderPanel();
      await userEvent.click(tab('Precios'));
      useProductPanel.mockReturnValue(hookState({ summary: readProduct(makeProductRow({ key: '4102', product_item_id: 4102 })) }));
      reopen('4102');
      expect(tab('Resumen')).toHaveAttribute('aria-selected', 'true');
      expect(figures()).toBeInTheDocument();
    });
  });
});
