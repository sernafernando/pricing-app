// Incident 2026-10-05: the panel showed a stale SMART offer as if it were
// current, and later an EMPTY mirror for an MLA that had 9 promos live on ML.
// The panel must say how old each row is, pull fresh state for read-only
// users too, and never present an unconfirmed empty mirror as "no promos".
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import MlaPromocionesPanel from './MlaPromocionesPanel';
import { promocionesAPI } from '../../services/api';
import { usePromoFilterStore } from '../../store/promoFilterStore';

vi.mock('../../services/api', () => ({
  promocionesAPI: {
    getPromocionesItem: vi.fn(),
    postPromocionItem: vi.fn(),
    refreshItemPromociones: vi.fn(),
    confirmarSinPromosML: vi.fn(),
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

  // The mirror read stays mirror-only (fast); the panel asks ML separately,
  // AFTER rendering, and says "confirming" meanwhile — never "no promos".
  it('empty mirror while ML reports promos -> cannot confirm', async () => {
    promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: true } });
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [] } });
    promocionesAPI.confirmarSinPromosML.mockResolvedValue({
      data: { sin_promos_confirmado: false, promos_en_ml: 9 },
    });

    renderPanel();

    expect(await screen.findByText(/no se pudo confirmar con ml/i)).toBeInTheDocument();
    expect(screen.getByText(/datos posiblemente desactualizados/i)).toBeInTheDocument();
    expect(screen.getByText(/ml informa 9 promociones/i)).toBeInTheDocument();
    expect(screen.queryByText(/sin promociones habilitadas/i)).not.toBeInTheDocument();
    expect(promocionesAPI.confirmarSinPromosML).toHaveBeenCalledWith('MLA2385168136');
  });

  it('shows "confirming" while ML has not answered yet', async () => {
    promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: true } });
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [] } });
    promocionesAPI.confirmarSinPromosML.mockReturnValue(new Promise(() => {}));

    renderPanel();

    expect(await screen.findByText(/confirmando con ml/i)).toBeInTheDocument();
    expect(screen.queryByText(/sin promociones habilitadas/i)).not.toBeInTheDocument();
  });

  it('a failed confirmation call -> cannot confirm', async () => {
    promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: true } });
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [] } });
    promocionesAPI.confirmarSinPromosML.mockRejectedValue(new Error('network'));

    renderPanel();

    expect(await screen.findByText(/no se pudo confirmar con ml/i)).toBeInTheDocument();
  });

  it('empty mirror after a failed refresh -> cannot confirm, without asking ML again', async () => {
    promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: false, motivo: null } });
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [] } });

    renderPanel();

    expect(await screen.findByText(/no se pudo confirmar con ml/i)).toBeInTheDocument();
    expect(screen.queryByText(/sin promociones habilitadas/i)).not.toBeInTheDocument();
    expect(promocionesAPI.confirmarSinPromosML).not.toHaveBeenCalled();
  });

  it('empty mirror that ML confirms -> "Sin promociones habilitadas"', async () => {
    promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: true } });
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [] } });
    promocionesAPI.confirmarSinPromosML.mockResolvedValue({
      data: { sin_promos_confirmado: true, promos_en_ml: 0 },
    });

    renderPanel();

    expect(await screen.findByText(/sin promociones habilitadas/i)).toBeInTheDocument();
    expect(screen.queryByText(/no se pudo confirmar con ml/i)).not.toBeInTheDocument();
  });

  // A confirmation answers for the read that asked it. If the panel moves on
  // (another item, a newer read) a late answer for the old one must not
  // decide what the new empty mirror says.
  it('a late confirmation for a previous item is ignored', async () => {
    promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: true } });
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [] } });
    let answerA;
    let answerB;
    promocionesAPI.confirmarSinPromosML.mockImplementation((mla) =>
      new Promise((resolve) => {
        if (mla === 'MLA_A') answerA = resolve;
        else answerB = resolve;
      }),
    );
    const cache = { current: new Map() };

    const { rerender } = render(<MlaPromocionesPanel mla="MLA_A" promosCacheRef={cache} />);
    await waitFor(() => expect(answerA).toBeDefined());

    rerender(<MlaPromocionesPanel mla="MLA_B" promosCacheRef={cache} />);
    await waitFor(() => expect(answerB).toBeDefined());

    // ML says B has promos (cannot confirm); only then does A's stale
    // "ML agrees there are none" arrive.
    await act(async () => {
      answerB({ data: { sin_promos_confirmado: false, promos_en_ml: 3 } });
    });
    expect(await screen.findByText(/ml informa 3 promociones/i)).toBeInTheDocument();

    await act(async () => {
      answerA({ data: { sin_promos_confirmado: true, promos_en_ml: 0 } });
    });

    expect(screen.queryByText(/sin promociones habilitadas/i)).not.toBeInTheDocument();
    expect(screen.getByText(/ml informa 3 promociones/i)).toBeInTheDocument();
  });

  it('a non-empty mirror never asks ML for confirmation', async () => {
    promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: true } });
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: { promotions: [{ promotion_id: 'P1', promotion_type: 'DEAL', name: 'Deal', price: 80 }] },
    });

    renderPanel();

    await screen.findByText('Deal');
    expect(promocionesAPI.confirmarSinPromosML).not.toHaveBeenCalled();
  });
});
