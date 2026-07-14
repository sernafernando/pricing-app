import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ProductoMLAsPanel from './ProductoMLAsPanel';
import { productosAPI } from '../../services/api';

vi.mock('../../services/api', () => ({
  productosAPI: {
    getProductoMercadolibre: vi.fn(),
    getProductoMercadolibreLite: vi.fn(),
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

describe('ProductoMLAsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows a loading state while the fetch is in flight', async () => {
    let resolveFetch;
    productosAPI.getProductoMercadolibreLite.mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve;
      }),
    );

    renderPanel();
    expect(screen.getByText(/cargando publicaciones/i)).toBeInTheDocument();

    resolveFetch({ data: { publicaciones_ml: [] } });
    await waitFor(() => expect(screen.queryByText(/cargando publicaciones/i)).not.toBeInTheDocument());
  });

  it('renders ordered MLA rows with correct badges', async () => {
    productosAPI.getProductoMercadolibreLite.mockResolvedValue({
      data: {
        publicaciones_ml: [
          { mla: 'MLA001', pricelist_id: 4, publication_status: 'active' },
          { mla: 'MLA002', pricelist_id: 17, publication_status: 'active' },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('MLA001')).toBeInTheDocument());
    expect(screen.getByText('Clásica')).toBeInTheDocument();
    expect(screen.getByText('MLA002')).toBeInTheDocument();
    expect(screen.getByText('3 Cuotas')).toBeInTheDocument();
  });

  it('renders the backend-provided lista_nombre as the badge label', async () => {
    productosAPI.getProductoMercadolibreLite.mockResolvedValue({
      data: {
        publicaciones_ml: [
          { mla: 'MLA001', pricelist_id: 4, lista_nombre: 'Precio Personalizado 6 Cuotas', publication_status: 'active' },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('MLA001')).toBeInTheDocument());
    expect(screen.getByText('Precio Personalizado 6 Cuotas')).toBeInTheDocument();
  });

  it('falls back to getPublicationTypeLabel when lista_nombre is missing', async () => {
    productosAPI.getProductoMercadolibreLite.mockResolvedValue({
      data: {
        publicaciones_ml: [{ mla: 'MLA001', pricelist_id: 4, publication_status: 'active' }],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('MLA001')).toBeInTheDocument());
    expect(screen.getByText('Clásica')).toBeInTheDocument();
  });

  it('shows an error state distinct from empty', async () => {
    productosAPI.getProductoMercadolibreLite.mockRejectedValue(new Error('network error'));

    renderPanel();

    await waitFor(() => expect(screen.getByText(/error al cargar publicaciones/i)).toBeInTheDocument());
  });

  it('shows an empty state when there are zero MLAs', async () => {
    productosAPI.getProductoMercadolibreLite.mockResolvedValue({ data: { publicaciones_ml: [] } });

    renderPanel();

    await waitFor(() => expect(screen.getByText(/sin publicaciones/i)).toBeInTheDocument());
  });

  it('does not re-fetch when re-mounted with the same cached itemId', async () => {
    productosAPI.getProductoMercadolibreLite.mockResolvedValue({
      data: { publicaciones_ml: [{ mla: 'MLA001', pricelist_id: 4, publication_status: 'active' }] },
    });

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

    expect(productosAPI.getProductoMercadolibreLite).toHaveBeenCalledTimes(1);
  });

  it('expanding an MLA row lazily mounts the L2 promotions panel', async () => {
    productosAPI.getProductoMercadolibreLite.mockResolvedValue({
      data: { publicaciones_ml: [{ mla: 'MLA001', pricelist_id: 4, publication_status: 'active' }] },
    });

    renderPanel();
    await waitFor(() => expect(screen.getByText('MLA001')).toBeInTheDocument());

    const { promocionesAPI } = await import('../../services/api');
    expect(promocionesAPI.getPromocionesItem).not.toHaveBeenCalled();

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /expandir mla001/i }));

    await waitFor(() => expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledWith('MLA001'));
  });

  it('renders a count badge when promo_active_count > 0', async () => {
    productosAPI.getProductoMercadolibreLite.mockResolvedValue({
      data: {
        publicaciones_ml: [
          { mla: 'MLA001', pricelist_id: 4, publication_status: 'active', promo_active_count: 3 },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('MLA001')).toBeInTheDocument());
    expect(screen.getByText(/3/)).toBeInTheDocument();
  });

  it('does not render a count badge when promo_active_count is 0 or absent', async () => {
    productosAPI.getProductoMercadolibreLite.mockResolvedValue({
      data: {
        publicaciones_ml: [
          { mla: 'MLA001', pricelist_id: 4, publication_status: 'active', promo_active_count: 0 },
          { mla: 'MLA002', pricelist_id: 4, publication_status: 'active' },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('MLA001')).toBeInTheDocument());
    expect(screen.queryByText('0 promos')).not.toBeInTheDocument();
  });

  it('renders an applied indicator when promo_has_applied is true', async () => {
    productosAPI.getProductoMercadolibreLite.mockResolvedValue({
      data: {
        publicaciones_ml: [
          { mla: 'MLA001', pricelist_id: 4, publication_status: 'active', promo_has_applied: true },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('MLA001')).toBeInTheDocument());
    expect(screen.getByText(/aplicada/i)).toBeInTheDocument();
  });

  it('shows promo_applied_name in the applied indicator when present', async () => {
    productosAPI.getProductoMercadolibreLite.mockResolvedValue({
      data: {
        publicaciones_ml: [
          {
            mla: 'MLA001',
            pricelist_id: 4,
            publication_status: 'active',
            promo_has_applied: true,
            promo_applied_name: 'Oferta Relámpago',
          },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('MLA001')).toBeInTheDocument());
    expect(screen.getByText(/oferta relámpago/i)).toBeInTheDocument();
  });

  it('shows the applied indicator without blank text when promo_applied_name is absent', async () => {
    productosAPI.getProductoMercadolibreLite.mockResolvedValue({
      data: {
        publicaciones_ml: [
          { mla: 'MLA001', pricelist_id: 4, publication_status: 'active', promo_has_applied: true },
        ],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('MLA001')).toBeInTheDocument());
    const indicator = screen.getByText(/aplicada/i);
    expect(indicator.textContent).not.toMatch(/null|undefined/);
  });

  it('does not render badge/indicator when promo fields are entirely absent (degraded backend)', async () => {
    productosAPI.getProductoMercadolibreLite.mockResolvedValue({
      data: {
        publicaciones_ml: [{ mla: 'MLA001', pricelist_id: 4, publication_status: 'active' }],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('MLA001')).toBeInTheDocument());
    expect(screen.queryByText(/aplicada/i)).not.toBeInTheDocument();
  });

  it('exposes L1_COL_SPAN of 5 to keep the detail row colSpan in sync with the new header column', async () => {
    productosAPI.getProductoMercadolibreLite.mockResolvedValue({
      data: {
        publicaciones_ml: [{ mla: 'MLA001', pricelist_id: 4, publication_status: 'active' }],
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('MLA001')).toBeInTheDocument());
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /expandir mla001/i }));

    const detailCell = document.querySelector('td[colspan]');
    expect(detailCell).toHaveAttribute('colspan', '5');
  });
});
