/**
 * ProductPanel: the side panel of one product of the Producto view. Its data comes from `useProductPanel` (mocked
 * here at that boundary); the panel draws the header, the summed figures the permissions allow, and the product's
 * publications, each one opening its own panel.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProductPanel from './ProductPanel';
import useProductPanel from './panel/useProductPanel';
import { readProduct } from './useProductRows';
import { makeItem, makeProductRow, PRODUCT_ROWS } from '../../test/visual/publicacionesMlFixtures';

vi.mock('./panel/useProductPanel', async (importOriginal) => ({
  ...(await importOriginal()),
  default: vi.fn(),
}));

let granted = new Set();
vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: (permiso) => granted.has(permiso) }),
}));

vi.mock('../pricing/ProductPrices', () => ({
  default: ({ productItemId, permissions, showCost }) => (
    <div data-testid="product-prices">
      {`prices of ${productItemId}, cost ${showCost ? 'shown' : 'hidden'}, clasica ${permissions.canEditClasica ? 'editable' : 'read-only'}`}
    </div>
  ),
}));

vi.mock('./panel/ProductIdentity', () => ({
  default: ({ productItemId }) => <div data-testid="product-identity">{`identity of ${productItemId}`}</div>,
}));

vi.mock('./panel/ProductChangesTab', () => ({
  default: ({ productItemId }) => <div data-testid="product-changes">{`changes of ${productItemId}`}</div>,
}));

vi.mock('./panel/ProductCuotasConfig', () => ({
  default: ({ productItemId }) => <div data-testid="product-cuotas">{`cuotas of ${productItemId}`}</div>,
}));

vi.mock('./panel/ProductCatalogCompetition', () => ({
  default: ({ publications }) => (
    <div data-testid="product-catalog-competition">{`competition of ${publications.map((p) => p.item_id).join(',')}`}</div>
  ),
}));

vi.mock('./panel/ProductPxq', () => ({
  default: ({ publications }) => <div data-testid="product-pxq">{`pxq of ${publications.map((p) => p.item_id).join(',')}`}</div>,
}));

vi.mock('./panel/ProductPurchases', () => ({
  default: ({ productItemId }) => <div data-testid="product-purchases">{`purchases of ${productItemId}`}</div>,
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

  it('lists the publications and opens the one clicked', async () => {
    const { onSelectItem } = renderPanel();
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

  it('asks for more publications while there are more', async () => {
    const { state } = renderPanel({ state: hookState({ hasMore: true }) });
    await userEvent.click(screen.getByRole('button', { name: 'Ver más' }));
    expect(state.loadMore).toHaveBeenCalledTimes(1);
  });

  it('has no "Ver más" when every publication is shown', () => {
    renderPanel();
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

  it('says the publications are loading once the product is there', () => {
    renderPanel({ state: hookState({ items: [], loading: true }) });
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
