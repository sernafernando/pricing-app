/**
 * The detail panel's shell (publicaciones-ml-vista P13a.T1): what it asks the
 * backend for, how it shows loading / failure, and how its tab registry decides
 * which tabs exist. The content of each tab has its own test.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, render } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PublicationPanel from './PublicationPanel';
import { promocionesAPI, publicacionesMlAPI } from '../../services/api';
import { DETAIL_RESPONSE, DETAIL_RESPONSE_MARGIN, ITEMS, makeDetail, makeItem } from '../../test/visual/publicacionesMlFixtures';

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  publicacionesMlAPI: { detail: vi.fn(), variations: vi.fn(), enqueue: vi.fn() },
  promocionesAPI: {
    getPromocionesItem: vi.fn(() => Promise.resolve({ data: { promotions: [] } })),
    refreshItemPromociones: vi.fn(() => Promise.resolve({ data: { ok: true } })),
    confirmarSinPromosML: vi.fn(() => Promise.resolve({ data: { sin_promos_confirmado: true, promos_en_ml: 0 } })),
  },
  registerAuthFailureHandler: vi.fn(),
}));

// Everything is allowed except the margin, which each test grants on purpose.
let canSeeMargin = false;
let canManage = true;
let canSeePromos = true;
vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: (permiso) => {
      if (permiso === 'ml_metricas.ver_ganancia') return canSeeMargin;
      if (permiso === 'ml_ops.gestionar') return canManage;
      if (permiso === 'promos.ver') return canSeePromos;
      return true;
    },
    cargandoPermisos: false,
  }),
  PermisosProvider: ({ children }) => children,
}));

const httpError = (status, data = {}) => Object.assign(new Error(`HTTP ${status}`), { response: { status, data } });

const renderPanel = (props = {}) =>
  render(<PublicationPanel itemId="MLA1100000001" tab="" onTabChange={vi.fn()} onClose={vi.fn()} {...props} />);

beforeEach(() => {
  canSeeMargin = false;
  canManage = true;
  canSeePromos = true;
  promocionesAPI.getPromocionesItem.mockClear();
  promocionesAPI.refreshItemPromociones.mockClear();
  publicacionesMlAPI.detail.mockReset();
  publicacionesMlAPI.detail.mockResolvedValue({ data: DETAIL_RESPONSE });
});

describe('loading the detail', () => {
  it('asks for the detail of the selected publication, once', async () => {
    renderPanel();
    await screen.findByRole('heading', { name: /Router TP-Link Archer AX55/ });
    expect(publicacionesMlAPI.detail).toHaveBeenCalledTimes(1);
    expect(publicacionesMlAPI.detail).toHaveBeenCalledWith('MLA1100000001');
  });

  it('shows the MLA right away, while the detail is still loading', () => {
    publicacionesMlAPI.detail.mockReturnValue(new Promise(() => {}));
    renderPanel();
    expect(screen.getByRole('status', { name: 'Cargando publicación' })).toBeInTheDocument();
    expect(screen.getByText('MLA1100000001')).toBeInTheDocument();
  });

  it('a publication without a title still has a heading', async () => {
    publicacionesMlAPI.detail.mockResolvedValue({ data: makeDetail({ row: ITEMS[2] }) });
    renderPanel({ itemId: 'MLA1100000003' });
    expect(await screen.findByRole('heading', { name: 'Sin título' })).toBeInTheDocument();
  });

  it('selecting another publication swaps the content and never shows the old one meanwhile', async () => {
    const { rerender } = renderPanel();
    await screen.findByRole('heading', { name: /Router TP-Link Archer AX55/ });

    let resolveSecond;
    publicacionesMlAPI.detail.mockReturnValue(new Promise((resolve) => { resolveSecond = resolve; }));
    rerender(<PublicationPanel itemId="MLA1100000002" tab="" onTabChange={vi.fn()} onClose={vi.fn()} />);
    expect(screen.queryByRole('heading', { name: /Router TP-Link/ })).not.toBeInTheDocument();
    expect(screen.getByText('MLA1100000002')).toBeInTheDocument();

    resolveSecond({ data: makeDetail({ row: ITEMS[1] }) });
    expect(await screen.findByRole('heading', { name: /Cartucho Epson 544/ })).toBeInTheDocument();
  });

  it('going back to a publication whose answer is still pending shows loading, not its old content', async () => {
    const { rerender } = renderPanel();
    await screen.findByRole('heading', { name: /Router TP-Link Archer AX55/ });
    publicacionesMlAPI.detail.mockReturnValue(new Promise(() => {}));
    rerender(<PublicationPanel itemId="MLA1100000002" tab="" onTabChange={vi.fn()} onClose={vi.fn()} />);
    rerender(<PublicationPanel itemId="MLA1100000001" tab="" onTabChange={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByRole('status', { name: 'Cargando publicación' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: /Router TP-Link Archer AX55/ })).not.toBeInTheDocument();
  });

  it('a late answer for the previous publication never overwrites the current one', async () => {
    let resolveFirst;
    publicacionesMlAPI.detail.mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve; }));
    const { rerender } = renderPanel();
    publicacionesMlAPI.detail.mockResolvedValue({ data: makeDetail({ row: ITEMS[1] }) });
    rerender(<PublicationPanel itemId="MLA1100000002" tab="" onTabChange={vi.fn()} onClose={vi.fn()} />);
    await screen.findByRole('heading', { name: /Cartucho Epson 544/ });
    resolveFirst({ data: DETAIL_RESPONSE });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByRole('heading', { name: /Router TP-Link/ })).not.toBeInTheDocument();
  });
});

describe('failures', () => {
  it('an empty 200 body does not break the panel', async () => {
    publicacionesMlAPI.detail.mockResolvedValue({ data: null });
    renderPanel();
    expect(await screen.findByRole('heading', { name: 'Sin título' })).toBeInTheDocument();
  });

  it.each([
    [404, 'La publicación ya no existe'],
    [422, 'El identificador de la publicación no es válido'],
    [403, 'No tenés permiso'],
    [503, 'La consulta tardó demasiado'],
    [500, 'No se pudo cargar la publicación'],
  ])('a %i says what happened', async (status, message) => {
    publicacionesMlAPI.detail.mockRejectedValue(httpError(status));
    renderPanel();
    expect(await screen.findByRole('alert')).toHaveTextContent(message);
  });

  it('"Reintentar" asks again and recovers', async () => {
    publicacionesMlAPI.detail.mockRejectedValueOnce(httpError(503));
    renderPanel();
    await screen.findByRole('alert');
    await userEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
    expect(await screen.findByRole('heading', { name: /Router TP-Link Archer AX55/ })).toBeInTheDocument();
    expect(publicacionesMlAPI.detail).toHaveBeenCalledTimes(2);
  });

  it('a failure still leaves the panel closable', async () => {
    publicacionesMlAPI.detail.mockRejectedValue(httpError(404));
    const onClose = vi.fn();
    renderPanel({ onClose });
    await screen.findByRole('alert');
    await userEvent.click(screen.getByRole('button', { name: 'Cerrar panel' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe('tabs', () => {
  const tabs = [
    { key: 'uno', label: 'Uno', isVisible: () => true, Component: () => <p>contenido uno</p> },
    { key: 'dos', label: 'Dos', isVisible: ({ detail }) => detail.variationsCount > 0, Component: () => <p>contenido dos</p> },
    { key: 'ganancia', label: 'Ganancia', isVisible: ({ canSeeMargin: margin }) => margin, Component: () => <p>contenido ganancia</p> },
  ];

  it('shows only the tabs the registry says exist for this data and permission', async () => {
    renderPanel({ tabs });
    await screen.findByRole('tab', { name: 'Uno' });
    expect(screen.queryByRole('tab', { name: 'Dos' })).not.toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Ganancia' })).not.toBeInTheDocument();
  });

  it('data and permission make more tabs appear', async () => {
    canSeeMargin = true;
    publicacionesMlAPI.detail.mockResolvedValue({ data: makeDetail({ row: makeItem({ ...ITEMS[0], variations_count: 3 }) }) });
    renderPanel({ tabs });
    expect(await screen.findByRole('tab', { name: 'Dos' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Ganancia' })).toBeInTheDocument();
  });

  it('opens on the first tab and marks it selected', async () => {
    renderPanel({ tabs });
    const first = await screen.findByRole('tab', { name: 'Uno' });
    expect(first).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tabpanel')).toHaveTextContent('contenido uno');
  });

  it('opens on the tab in the URL', async () => {
    canSeeMargin = true;
    renderPanel({ tabs, tab: 'ganancia' });
    expect(await screen.findByRole('tabpanel')).toHaveTextContent('contenido ganancia');
    expect(screen.getByRole('tab', { name: 'Ganancia' })).toHaveAttribute('aria-selected', 'true');
  });

  it('a tab that does not exist for this publication falls back to the first one', async () => {
    renderPanel({ tabs, tab: 'dos' });
    expect(await screen.findByRole('tabpanel')).toHaveTextContent('contenido uno');
  });

  it('clicking a tab reports it, so the page keeps it in the URL', async () => {
    canSeeMargin = true;
    const onTabChange = vi.fn();
    renderPanel({ tabs, onTabChange });
    await userEvent.click(await screen.findByRole('tab', { name: 'Ganancia' }));
    expect(onTabChange).toHaveBeenCalledWith('ganancia');
  });

  it('the arrow keys move between tabs', async () => {
    canSeeMargin = true;
    const onTabChange = vi.fn();
    renderPanel({ tabs, onTabChange });
    const first = await screen.findByRole('tab', { name: 'Uno' });
    first.focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(onTabChange).toHaveBeenCalledWith('ganancia');
  });

  it('the default registry has Resumen', async () => {
    renderPanel();
    expect(await screen.findByRole('tab', { name: 'Resumen' })).toHaveAttribute('aria-selected', 'true');
  });

  it('the default registry shows Full for a Full publication and Variaciones for one with variations', async () => {
    publicacionesMlAPI.variations.mockResolvedValue({ data: { variations: [] } });
    publicacionesMlAPI.detail.mockResolvedValue({
      data: makeDetail({ row: makeItem({ ...ITEMS[0], is_full: true, variations_count: 2 }) }),
    });
    renderPanel();
    expect(await screen.findByRole('tab', { name: 'Full' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Variaciones' })).toBeInTheDocument();
  });

  it('the default registry hides both for a plain publication', async () => {
    publicacionesMlAPI.detail.mockResolvedValue({
      data: makeDetail({ row: makeItem({ ...ITEMS[1], is_full: false, variations_count: 0 }), replenishment: null }),
    });
    renderPanel();
    await screen.findByRole('tab', { name: 'Resumen' });
    expect(screen.queryByRole('tab', { name: 'Full' })).not.toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Variaciones' })).not.toBeInTheDocument();
  });
});

describe('the panel itself', () => {
  it('two panels on one page never share the id of their tab panel', async () => {
    render(
      <>
        <PublicationPanel itemId="MLA1100000001" tab="" onTabChange={vi.fn()} onClose={vi.fn()} />
        <PublicationPanel itemId="MLA1100000002" tab="" onTabChange={vi.fn()} onClose={vi.fn()} />
      </>,
    );
    const panels = await screen.findAllByRole('tabpanel');
    expect(new Set(panels.map((panel) => panel.id)).size).toBe(2);
  });

  it('"Cerrar panel" calls onClose', async () => {
    const onClose = vi.fn();
    renderPanel({ onClose });
    await userEvent.click(await screen.findByRole('button', { name: 'Cerrar panel' }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('links to the publication in Mercado Libre only when the permalink is a Mercado Libre one', async () => {
    renderPanel();
    const link = await screen.findByRole('link', { name: /Ver en Mercado Libre/ });
    expect(link).toHaveAttribute('href', ITEMS[0].permalink);
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
  });

  it('has no link when the publication has no usable permalink', async () => {
    publicacionesMlAPI.detail.mockResolvedValue({ data: makeDetail({ row: makeItem({ ...ITEMS[0], permalink: 'http://evil.example/x' }) }) });
    renderPanel();
    await screen.findByRole('heading', { name: /Router TP-Link Archer AX55/ });
    expect(screen.queryByRole('link', { name: /Ver en Mercado Libre/ })).not.toBeInTheDocument();
  });

  it('does not refetch when only the tab changes', async () => {
    const { rerender } = renderPanel();
    await screen.findByRole('heading', { name: /Router TP-Link Archer AX55/ });
    rerender(<PublicationPanel itemId="MLA1100000001" tab="resumen" onTabChange={vi.fn()} onClose={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole('tab', { name: 'Resumen' })).toBeInTheDocument());
    expect(publicacionesMlAPI.detail).toHaveBeenCalledTimes(1);
  });
});

describe('the Promociones tab', () => {
  it('is offered with promos.ver and asks ML for nothing until somebody opens it (the throttle is shared)', async () => {
    renderPanel();
    await screen.findByRole('tab', { name: 'Promos' });
    expect(promocionesAPI.refreshItemPromociones).not.toHaveBeenCalled();
    expect(promocionesAPI.getPromocionesItem).not.toHaveBeenCalled();
  });

  it('is not offered without promos.ver', async () => {
    canSeePromos = false;
    renderPanel();
    await screen.findByRole('tab', { name: 'Resumen' });
    expect(screen.queryByRole('tab', { name: 'Promos' })).not.toBeInTheDocument();
  });

  it('loads the promotions of the selected publication when it is the open tab', async () => {
    renderPanel({ tab: 'promociones' });
    await waitFor(() => expect(promocionesAPI.getPromocionesItem).toHaveBeenCalledWith('MLA1100000001'));
    expect(promocionesAPI.refreshItemPromociones).toHaveBeenCalledWith('MLA1100000001');
  });
});

describe('the tab strip', () => {
  it('scrolls the open tab into view, sideways only, so a tab past the edge of a narrow panel is never lost', async () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    try {
      renderPanel({ tab: 'promociones' });
      await screen.findByRole('tab', { name: 'Promos', selected: true });
      await waitFor(() => expect(scrollIntoView).toHaveBeenCalledWith({ block: 'nearest', inline: 'nearest' }));
      expect(scrollIntoView.mock.contexts.at(-1)).toBe(screen.getByRole('tab', { name: 'Promos' }));
    } finally {
      delete Element.prototype.scrollIntoView;
    }
  });
});

describe('the footer', () => {
  it('shows the freshness of the data', async () => {
    renderPanel();
    expect(await screen.findByRole('list', { name: 'Actualización de los datos' })).toBeInTheDocument();
  });

  it('offers "Resincronizar" when the caller may manage the store and the detail allows it', async () => {
    publicacionesMlAPI.detail.mockResolvedValue({ data: DETAIL_RESPONSE_MARGIN });
    renderPanel();
    expect(await screen.findByRole('button', { name: 'Resincronizar' })).toBeInTheDocument();
  });

  it('hides it without ml_ops.gestionar even when the detail allows it (S60.2)', async () => {
    canManage = false;
    publicacionesMlAPI.detail.mockResolvedValue({ data: DETAIL_RESPONSE_MARGIN });
    renderPanel();
    await screen.findByRole('heading', { name: /Router TP-Link Archer AX55/ });
    expect(screen.queryByRole('button', { name: 'Resincronizar' })).not.toBeInTheDocument();
  });

  it('is not there while loading or after a failure', async () => {
    publicacionesMlAPI.detail.mockRejectedValue(httpError(500));
    renderPanel();
    await screen.findByRole('alert');
    expect(screen.queryByRole('button', { name: 'Resincronizar' })).not.toBeInTheDocument();
  });
});
