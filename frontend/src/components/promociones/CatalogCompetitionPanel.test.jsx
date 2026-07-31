import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import CatalogCompetitionPanel from './CatalogCompetitionPanel';
import { promocionesAPI } from '../../services/api';

// setup.js stubs PermisosContext globally with tienePermiso() => true, so the
// write gate is invisible unless this test overrides it locally.
const { mockTienePermiso } = vi.hoisted(() => ({ mockTienePermiso: vi.fn(() => true) }));
vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: mockTienePermiso, cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../../services/api', () => ({
  promocionesAPI: {
    getCompetenciaCatalogo: vi.fn(),
    refreshCompetenciaCatalogo: vi.fn(),
  },
}));

function renderPanel(props = {}) {
  const catalogCompetitionCacheRef = { current: new Map() };
  return render(
    <CatalogCompetitionPanel mla="MLA001" catalogCompetitionCacheRef={catalogCompetitionCacheRef} {...props} />,
  );
}

describe('CatalogCompetitionPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows a loading state while the read fetch is in flight', async () => {
    let resolveFetch;
    promocionesAPI.getCompetenciaCatalogo.mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve;
      }),
    );

    renderPanel();
    expect(screen.getByText(/cargando competencia de cat/i)).toBeInTheDocument();

    resolveFetch({ data: { mla: 'MLA001', fetch_status: 'never', undercutting: [] } });
    await waitFor(() => expect(screen.queryByText(/cargando competencia de cat/i)).not.toBeInTheDocument());
  });

  it('never auto-fetches a fresh snapshot on mount — only reads the stored one', async () => {
    promocionesAPI.getCompetenciaCatalogo.mockResolvedValue({
      data: { mla: 'MLA001', fetch_status: 'never', undercutting: [] },
    });

    renderPanel();
    await waitFor(() => expect(promocionesAPI.getCompetenciaCatalogo).toHaveBeenCalledTimes(1));
    expect(promocionesAPI.refreshCompetenciaCatalogo).not.toHaveBeenCalled();
    expect(screen.getByText(/sin consultar todav/i)).toBeInTheDocument();
  });

  it('shows the "no aplica" state for a not_catalog snapshot, panel stays visible', async () => {
    promocionesAPI.getCompetenciaCatalogo.mockResolvedValue({
      data: { mla: 'MLA001', fetch_status: 'not_catalog', undercutting: [] },
    });

    renderPanel();
    await waitFor(() => expect(screen.getByText(/no aplica/i)).toBeInTheDocument());
  });

  it('shows an error state with retry for an error snapshot', async () => {
    promocionesAPI.getCompetenciaCatalogo.mockResolvedValue({
      data: { mla: 'MLA001', fetch_status: 'error', error_detail: 'HTTP 500', undercutting: [] },
    });

    renderPanel();
    await waitFor(() => expect(screen.getByText(/error al consultar/i)).toBeInTheDocument());
    expect(screen.getByText(/HTTP 500/)).toBeInTheDocument();
  });

  it('shows an error state when the read request itself fails, with a working retry', async () => {
    promocionesAPI.getCompetenciaCatalogo.mockRejectedValueOnce(new Error('network'));
    renderPanel();
    await waitFor(() => expect(screen.getByText(/error al cargar/i)).toBeInTheDocument());

    promocionesAPI.getCompetenciaCatalogo.mockResolvedValueOnce({
      data: { mla: 'MLA001', fetch_status: 'never', undercutting: [] },
    });
    fireEvent.click(screen.getByText(/reintentar/i));
    await waitFor(() => expect(screen.getByText(/sin consultar todav/i)).toBeInTheDocument());
  });

  it('renders only same-bucket cheaper competitors from an ok snapshot, with their markup', async () => {
    promocionesAPI.getCompetenciaCatalogo.mockResolvedValue({
      data: {
        mla: 'MLA001',
        fetch_status: 'ok',
        fecha_consulta: '2026-07-30T10:00:00Z',
        our_price: 1000,
        competitor_count: 5,
        undercutting: [
          { item_id: 'RIVAL1', seller_nickname: 'Rival Uno', price: 900, price_ars: 900, markup: 32.5 },
        ],
      },
    });

    renderPanel();
    await waitFor(() => expect(screen.getByText('Rival Uno')).toBeInTheDocument());
    expect(screen.getByText('$900')).toBeInTheDocument();
    expect(screen.getByText(/32\.5%/)).toBeInTheDocument();
    expect(screen.getByText(/Nuestro precio: \$1\.000/)).toBeInTheDocument();
  });

  it('shows the empty-undercutting message with the hidden competitor count', async () => {
    promocionesAPI.getCompetenciaCatalogo.mockResolvedValue({
      data: { mla: 'MLA001', fetch_status: 'ok', our_price: 1000, competitor_count: 3, undercutting: [] },
    });

    renderPanel();
    await waitFor(() => expect(screen.getByText(/sin competidores m.s baratos/i)).toBeInTheDocument());
    expect(screen.getByText(/3 competidores relevados/)).toBeInTheDocument();
  });

  it('refresh button triggers exactly one POST, then re-reads the snapshot', async () => {
    promocionesAPI.getCompetenciaCatalogo
      .mockResolvedValueOnce({ data: { mla: 'MLA001', fetch_status: 'never', undercutting: [] } })
      .mockResolvedValueOnce({ data: { mla: 'MLA001', fetch_status: 'ok', our_price: 1000, undercutting: [] } });
    promocionesAPI.refreshCompetenciaCatalogo.mockResolvedValue({
      data: { mla: 'MLA001', fetch_status: 'ok' },
    });

    renderPanel();
    await waitFor(() => expect(screen.getByText(/sin consultar todav/i)).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /refrescar competencia de cat/i }));

    await waitFor(() => expect(promocionesAPI.refreshCompetenciaCatalogo).toHaveBeenCalledTimes(1));
    expect(promocionesAPI.refreshCompetenciaCatalogo).toHaveBeenCalledWith('MLA001');
    await waitFor(() => expect(promocionesAPI.getCompetenciaCatalogo).toHaveBeenCalledTimes(2));
  });

  it('shows a refresh-failure message without crashing when the refresh POST rejects', async () => {
    promocionesAPI.getCompetenciaCatalogo.mockResolvedValue({
      data: { mla: 'MLA001', fetch_status: 'never', undercutting: [] },
    });
    promocionesAPI.refreshCompetenciaCatalogo.mockRejectedValue(new Error('proxy down'));

    renderPanel();
    await waitFor(() => expect(screen.getByText(/sin consultar todav/i)).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /refrescar competencia de cat/i }));

    await waitFor(() => expect(screen.getByText(/no se pudo consultar/i)).toBeInTheDocument());
  });
});


describe('CatalogCompetitionPanel — refresh permission gate', () => {
  afterEach(() => mockTienePermiso.mockReturnValue(true));

  it('hides the refresh button without promos.escribir', async () => {
    // The read only needs promos.ver. Showing a refresh a view-only user
    // cannot use would just hand them a 403.
    mockTienePermiso.mockImplementation((perm) => perm !== 'promos.escribir');
    promocionesAPI.getCompetenciaCatalogo.mockResolvedValue({
      data: { mla: 'MLA001', fetch_status: 'ok', undercutting: [] },
    });

    renderPanel();
    await waitFor(() => expect(promocionesAPI.getCompetenciaCatalogo).toHaveBeenCalled());
    expect(screen.queryByRole('button', { name: /refrescar competencia de catálogo/i })).not.toBeInTheDocument();
  });

  it('shows the refresh button with promos.escribir', async () => {
    promocionesAPI.getCompetenciaCatalogo.mockResolvedValue({
      data: { mla: 'MLA001', fetch_status: 'ok', undercutting: [] },
    });

    renderPanel();
    await waitFor(() => expect(promocionesAPI.getCompetenciaCatalogo).toHaveBeenCalled());
    expect(screen.getByRole('button', { name: /refrescar competencia de catálogo/i })).toBeInTheDocument();
  });
});
