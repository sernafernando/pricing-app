import { describe, it, expect, vi, beforeEach } from 'vitest';
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

const permisosMock = vi.hoisted(() => ({ denied: [] }));

vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: (permiso) => !permisosMock.denied.includes(permiso),
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

// First open of a product used to wait for one ML pull per MLA (25-30 s in production) before
// showing anything. The mirror we already have is shown at once; the pull runs in the background.

const MIRROR = {
  promotions: [{ promotion_id: 'P1', promotion_type: 'DEAL', name: 'Deal promo', price: 80 }],
};
const FRESHER = {
  promotions: [{ promotion_id: 'P1', promotion_type: 'DEAL', name: 'Deal promo', price: 70 }],
};

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function renderPanel(props = {}) {
  return render(<MlaPromocionesPanel mla="MLA_BG" promosCacheRef={{ current: new Map() }} {...props} />);
}

const REFRESHING = /actualizando desde ml/i;

describe('MlaPromocionesPanel - background refresh', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    permisosMock.denied = [];
    usePromoFilterStore.setState({ selectedTypes: [], selectedNames: {} });
    promocionesAPI.confirmarSinPromosML.mockResolvedValue({ data: { sin_promos_confirmado: true, promos_en_ml: 0 } });
  });

  it('renders the mirror before the refresh resolves, with a visible "updating" state', async () => {
    const pull = deferred();
    promocionesAPI.refreshItemPromociones.mockReturnValue(pull.promise);
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: MIRROR });

    renderPanel();

    expect(await screen.findByText('Deal promo')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent(REFRESHING);
    expect(promocionesAPI.refreshItemPromociones).toHaveBeenCalledWith('MLA_BG');
    // The refresh is the ONLY thing still pending: the first read did not wait for it.
    expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledTimes(1);
  });

  it('keeps apply/remove disabled until the refresh settles, then re-reads the mirror', async () => {
    const pull = deferred();
    promocionesAPI.refreshItemPromociones.mockReturnValue(pull.promise);
    promocionesAPI.getPromocionesItem.mockResolvedValueOnce({ data: MIRROR }).mockResolvedValue({ data: FRESHER });

    renderPanel();
    await screen.findByText('Deal promo');

    expect(screen.queryByRole('button', { name: /^aplicar$/i })).not.toBeInTheDocument();
    const locked = screen.getByRole('button', { name: REFRESHING });
    expect(locked).toBeDisabled();

    await act(async () => {
      pull.resolve({ data: { ok: true } });
    });

    expect(await screen.findByRole('button', { name: /^aplicar$/i })).toBeEnabled();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledTimes(2);
    expect(screen.getByText('$70')).toBeInTheDocument();
    expect(screen.queryByText(/no se pudo actualizar/i)).not.toBeInTheDocument();
  });

  it('a refresh that resolves ok:false keeps the "possibly stale" notice and unlocks the controls', async () => {
    const pull = deferred();
    promocionesAPI.refreshItemPromociones.mockReturnValue(pull.promise);
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: MIRROR });

    renderPanel();
    await screen.findByText('Deal promo');
    await act(async () => {
      pull.resolve({ data: { ok: false, motivo: 'ML no responde' } });
    });

    expect(await screen.findByText(/no se pudo actualizar desde mercadolibre: ml no responde/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^aplicar$/i })).toBeEnabled();
  });

  it('a refresh that rejects keeps the generic "possibly stale" notice', async () => {
    const pull = deferred();
    promocionesAPI.refreshItemPromociones.mockReturnValue(pull.promise);
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: MIRROR });

    renderPanel();
    await screen.findByText('Deal promo');
    await act(async () => {
      pull.reject(new Error('network'));
    });

    expect(await screen.findByText(/no se pudo actualizar desde mercadolibre/i)).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: /^aplicar$/i })).toBeEnabled();
  });

  it('does not wait for the refresh to confirm an empty mirror with ML', async () => {
    const pull = deferred();
    promocionesAPI.refreshItemPromociones.mockReturnValue(pull.promise);
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [] } });

    renderPanel();

    expect(await screen.findByRole('status')).toHaveTextContent(REFRESHING);
    expect(promocionesAPI.confirmarSinPromosML).not.toHaveBeenCalled();

    await act(async () => {
      pull.resolve({ data: { ok: true } });
    });
    await waitFor(() => expect(promocionesAPI.confirmarSinPromosML).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/sin promociones habilitadas/i)).toBeInTheDocument();
  });

  it('does not pull when the parent says not to, and the controls are enabled at once', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: MIRROR });

    renderPanel({ pullOnOpen: false });

    expect(await screen.findByRole('button', { name: /^aplicar$/i })).toBeEnabled();
    expect(promocionesAPI.refreshItemPromociones).not.toHaveBeenCalled();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('does not pull for a user without promos.ver', async () => {
    permisosMock.denied = ['promos.ver'];
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: MIRROR });

    renderPanel();

    expect(await screen.findByRole('button', { name: /^aplicar$/i })).toBeEnabled();
    expect(promocionesAPI.refreshItemPromociones).not.toHaveBeenCalled();
  });
});

describe('MlaPromocionesPanel - pointed at another MLA mid-pull', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    permisosMock.denied = [];
    usePromoFilterStore.setState({ selectedTypes: [], selectedNames: {} });
    promocionesAPI.confirmarSinPromosML.mockResolvedValue({ data: { sin_promos_confirmado: true, promos_en_ml: 0 } });
  });

  it('ignores the late result of the previous MLA pull and settles the new one', async () => {
    const slow = deferred();
    promocionesAPI.refreshItemPromociones.mockReturnValueOnce(slow.promise).mockResolvedValue({ data: { ok: true } });
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: MIRROR });
    const cache = { current: new Map() };

    const view = render(<MlaPromocionesPanel mla="MLA_A" promosCacheRef={cache} />);
    await screen.findByText('Deal promo');
    view.rerender(<MlaPromocionesPanel mla="MLA_B" promosCacheRef={cache} />);
    await act(async () => {
      slow.resolve({ data: { ok: true } });
    });

    expect(await screen.findByRole('button', { name: /^aplicar$/i })).toBeEnabled();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});

describe('MlaPromocionesPanel - only active publications are pulled from ML', () => {
  const MOTIVO = 'Publicación pausada: las promos se actualizan cuando se reactive';

  beforeEach(() => {
    vi.clearAllMocks();
    permisosMock.denied = [];
    usePromoFilterStore.setState({ selectedTypes: [], selectedNames: {} });
    promocionesAPI.confirmarSinPromosML.mockResolvedValue({ data: { sin_promos_confirmado: true, promos_en_ml: 0 } });
    promocionesAPI.refreshItemPromociones.mockResolvedValue({ data: { ok: true } });
  });

  it.each([
    ['paused', 'Publicación pausada: las promos se actualizan cuando se reactive'],
    ['under_review', 'Publicación en revisión: las promos se actualizan cuando vuelva a estar activa'],
    ['inactive', 'Publicación inactiva: las promos se actualizan cuando se reactive'],
    ['closed', 'Publicación cerrada: no se consultan promociones en ML'],
    ['gone', 'Publicación dada de baja en ML: no se consultan promociones'],
    ['never_existed', 'La publicación no existe en ML: no se consultan promociones'],
  ])('%s: never calls the refresh, shows the reason and the mirror read-only', async (_status, motivo) => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { ...MIRROR, motivo_sin_actualizacion: motivo } });

    renderPanel();

    expect(await screen.findByText('Deal promo')).toBeInTheDocument();
    expect(screen.getByText(new RegExp(motivo))).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^aplicar$/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /solo lectura/i })).toBeDisabled();
    expect(promocionesAPI.refreshItemPromociones).not.toHaveBeenCalled();
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
    expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledTimes(1);
  });

  it('an empty mirror of a not-active publication says so without asking ML anything', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({
      data: { promotions: [], motivo_sin_actualizacion: MOTIVO },
    });

    renderPanel();

    expect(await screen.findByText(new RegExp(MOTIVO))).toBeInTheDocument();
    expect(promocionesAPI.refreshItemPromociones).not.toHaveBeenCalled();
    expect(promocionesAPI.confirmarSinPromosML).not.toHaveBeenCalled();
  });

  it('an active publication (no reason) is pulled as usual', async () => {
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { ...MIRROR, motivo_sin_actualizacion: null } });

    renderPanel();

    await screen.findByText('Deal promo');
    await waitFor(() => expect(promocionesAPI.refreshItemPromociones).toHaveBeenCalledTimes(1));
  });
});
