// Incident 2026-10-05: the panel showed a stale SMART offer as if it were
// current, and later an EMPTY mirror for an MLA that had 9 promos live on ML.
// The panel must say how old each row is, pull fresh state for read-only
// users too, and never present an unconfirmed empty mirror as "no promos".
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import MlaPromocionesPanel from './MlaPromocionesPanel';
import { promocionesAPI } from '../../services/api';
import { usePromoFilterStore } from '../../store/promoFilterStore';

vi.mock('../../services/api', () => ({
  promocionesAPI: {
    getPromocionesItem: vi.fn(),
    postPromocionItem: vi.fn(),
    refreshItemPromociones: vi.fn(),
  },
}));

const permisosMock = vi.hoisted(() => ({ granted: ['promos.ver', 'promos.escribir'] }));

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: (permiso) => permisosMock.granted.includes(permiso),
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

const NOW = new Date('2026-10-05T15:00:00Z');

function renderPanel(mla = 'MLA2385168136') {
  return render(<MlaPromocionesPanel mla={mla} promosCacheRef={{ current: new Map() }} />);
}

describe('MlaPromocionesPanel — freshness', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(NOW);
    usePromoFilterStore.setState({ selectedTypes: [], selectedNames: {} });
    permisosMock.granted = ['promos.ver', 'promos.escribir'];
    promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: true } });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows how long ago each row was updated', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: {
        promotions: [
          {
            promotion_id: 'P-MLA18091086',
            promotion_type: 'SMART',
            status: 'candidate',
            name: 'Ofertas compartidas 10.10',
            price: 469120,
            updated_at: '2026-10-04T12:00:00Z',
          },
        ],
      },
    });

    renderPanel();

    expect(await screen.findByText('actualizado hace 1 d')).toBeInTheDocument();
  });

  it('says nothing about age when the row has no timestamp', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: { promotions: [{ promotion_id: 'P1', promotion_type: 'DEAL', name: 'Deal', price: 80 }] },
    });

    renderPanel();

    await screen.findByText('Deal');
    expect(screen.queryByText(/actualizado/)).not.toBeInTheDocument();
  });

  it('a promos.ver-only user also pulls fresh state on open (it is a read)', async () => {
    permisosMock.granted = ['promos.ver'];
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [] } });

    renderPanel('MLA_RO');

    await waitFor(() => expect(promocionesAPI.refreshItemPromociones).toHaveBeenCalledWith('MLA_RO'));
    await waitFor(() => expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledWith('MLA_RO'));
  });

  it('a user without promos.ver never pulls', async () => {
    permisosMock.granted = [];
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [] } });

    renderPanel('MLA_NONE');

    await waitFor(() => expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledWith('MLA_NONE'));
    expect(promocionesAPI.refreshItemPromociones).not.toHaveBeenCalled();
  });
});

describe('MlaPromocionesPanel — an empty mirror is not "no promos" unless ML agrees', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    usePromoFilterStore.setState({ selectedTypes: [], selectedNames: {} });
    permisosMock.granted = ['promos.ver', 'promos.escribir'];
  });

  it('empty mirror while ML reports promos -> cannot confirm', async () => {
    promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: true } });
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: { promotions: [], posiblemente_desactualizado: true, promos_en_ml: 9 },
    });

    renderPanel();

    expect(await screen.findByText(/no se pudo confirmar con ml/i)).toBeInTheDocument();
    expect(screen.getByText(/datos posiblemente desactualizados/i)).toBeInTheDocument();
    expect(screen.getByText(/ml informa 9 promociones/i)).toBeInTheDocument();
    expect(screen.queryByText(/sin promociones habilitadas/i)).not.toBeInTheDocument();
  });

  it('empty mirror after a failed refresh -> cannot confirm', async () => {
    promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: false, motivo: null } });
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [] } });

    renderPanel();

    expect(await screen.findByText(/no se pudo confirmar con ml/i)).toBeInTheDocument();
    expect(screen.queryByText(/sin promociones habilitadas/i)).not.toBeInTheDocument();
  });

  it('empty mirror that ML confirms -> "Sin promociones habilitadas"', async () => {
    promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: true } });
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: { promotions: [], posiblemente_desactualizado: false, promos_en_ml: 0 },
    });

    renderPanel();

    expect(await screen.findByText(/sin promociones habilitadas/i)).toBeInTheDocument();
    expect(screen.queryByText(/no se pudo confirmar con ml/i)).not.toBeInTheDocument();
  });
});
