import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import PxqPanel from './PxqPanel';
import { pxqAPI } from '../../services/api';

// setup.js stubs PermisosContext globally with tienePermiso() => true, so the
// read gate is invisible unless this test overrides it locally.
const { mockTienePermiso } = vi.hoisted(() => ({ mockTienePermiso: vi.fn(() => true) }));
vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: mockTienePermiso, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../../services/api', () => ({
  pxqAPI: {
    getLive: vi.fn(),
  },
}));

function renderPanel(props = {}) {
  const pxqCacheRef = { current: new Map() };
  return render(<PxqPanel itemId="MLA001" pxqCacheRef={pxqCacheRef} {...props} />);
}

describe('PxqPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockTienePermiso.mockReturnValue(true);
  });

  afterEach(() => {
    mockTienePermiso.mockReturnValue(true);
  });

  it('shows nothing at all without pxq.ver — never renders an error/403 for a view-only-denied user', async () => {
    mockTienePermiso.mockReturnValue(false);
    const { container } = renderPanel();
    expect(container).toBeEmptyDOMElement();
    expect(pxqAPI.getLive).not.toHaveBeenCalled();
  });

  it('shows a loading state while the live-state fetch is in flight', async () => {
    let resolveFetch;
    pxqAPI.getLive.mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve;
      }),
    );

    renderPanel();
    expect(screen.getByText(/cargando precios mayoristas/i)).toBeInTheDocument();

    resolveFetch({
      data: {
        item_id: 'MLA001',
        live_status: 'ok',
        live_tiers: [],
        mirror_tiers: [],
        fetched_at: '2026-08-01T10:00:00Z',
      },
    });
    await waitFor(() => expect(screen.queryByText(/cargando precios mayoristas/i)).not.toBeInTheDocument());
  });

  it('shows an error band with retry when the request itself fails', async () => {
    pxqAPI.getLive.mockRejectedValueOnce(new Error('network'));
    renderPanel();

    await waitFor(() => expect(screen.getByText(/error al cargar precios mayoristas/i)).toBeInTheDocument());

    pxqAPI.getLive.mockResolvedValueOnce({
      data: { item_id: 'MLA001', live_status: 'ok', live_tiers: [], mirror_tiers: [], fetched_at: '2026-08-01T10:00:00Z' },
    });
    screen.getByRole('button', { name: /reintentar/i }).click();
    await waitFor(() => expect(screen.queryByText(/error al cargar precios mayoristas/i)).not.toBeInTheDocument());
  });

  it('shows plainly that live state is unavailable (never "0 tramos en vivo") while still showing the mirror', async () => {
    pxqAPI.getLive.mockResolvedValue({
      data: {
        item_id: 'MLA001',
        live_status: 'unavailable',
        live_tiers: null,
        mirror_tiers: [
          { id: 1, cantidad_minima: 5, precio_unitario: 100, costo_envio_total: 20, ml_price_id: null, estado: 'listo' },
        ],
        fetched_at: '2026-08-01T10:00:00Z',
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText(/no se pudo leer el estado en vivo/i)).toBeInTheDocument());
    expect(screen.queryByText(/0 tramos en vivo/i)).not.toBeInTheDocument();
    expect(screen.getByText(/5/)).toBeInTheDocument();
  });

  it('shows the empty state distinctly when ML really has no tiers ([] not null)', async () => {
    pxqAPI.getLive.mockResolvedValue({
      data: {
        item_id: 'MLA001',
        live_status: 'ok',
        live_tiers: [],
        mirror_tiers: [],
        fetched_at: '2026-08-01T10:00:00Z',
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText(/ml no tiene tramos mayoristas/i)).toBeInTheDocument());
  });

  it('renders live and mirror tiers side by side when both are present', async () => {
    pxqAPI.getLive.mockResolvedValue({
      data: {
        item_id: 'MLA001',
        live_status: 'ok',
        live_tiers: [{ id: 'PXQ1', quantity: 5, amount: 100 }],
        mirror_tiers: [
          { id: 1, cantidad_minima: 5, precio_unitario: 100, costo_envio_total: 20, ml_price_id: 'PXQ1', estado: 'sincronizado' },
        ],
        fetched_at: '2026-08-01T10:00:00Z',
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText(/en mercadolibre/i)).toBeInTheDocument());
    expect(screen.getByText(/mirror local/i)).toBeInTheDocument();
  });

  it('marks a divergent tier visibly (no resolution action offered — read only)', async () => {
    pxqAPI.getLive.mockResolvedValue({
      data: {
        item_id: 'MLA001',
        live_status: 'ok',
        live_tiers: [{ id: 'PXQ1', quantity: 5, amount: 150 }],
        mirror_tiers: [
          { id: 1, cantidad_minima: 5, precio_unitario: 100, costo_envio_total: 20, ml_price_id: 'PXQ1', estado: 'sincronizado' },
        ],
        fetched_at: '2026-08-01T10:00:00Z',
      },
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText(/diverge/i)).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /resolver|sincronizar/i })).not.toBeInTheDocument();
  });
});
