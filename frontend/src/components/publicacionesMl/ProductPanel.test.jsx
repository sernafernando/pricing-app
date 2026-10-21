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
  render(
    <ProductPanel filters={FILTERS} productKey={productKey} canSeeSales canSeeMargin {...handlers} {...props} />,
  );
  return { ...handlers, state };
}

const figures = () => screen.queryByRole('region', { name: 'Cifras' });

describe('ProductPanel', () => {
  beforeEach(() => {
    useProductPanel.mockReset();
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
});
