/**
 * The detail panel's shell (publicaciones-ml-vista P13a.T1): what it asks the
 * backend for, how it shows loading / failure, and how its tab registry decides
 * which tabs exist. The content of each tab has its own test.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { cleanup, screen, waitFor, render, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PublicationPanel from './PublicationPanel';
import { MARKUP_REASONS } from './markupReasons';
import { resetPromoPulls } from '../promociones/promoPullTtl';
import { preciosAPI, promocionesAPI, publicacionesMlAPI } from '../../services/api';
import { DETAIL_LINKED, DETAIL_RESPONSE, DETAIL_RESPONSE_MARGIN, ITEM_LINK, ITEMS, makeDetail, makeItem } from '../../test/visual/publicacionesMlFixtures';

vi.mock('../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  publicacionesMlAPI: {
    detail: vi.fn(),
    variations: vi.fn(),
    enqueue: vi.fn(),
    productLinks: vi.fn(() => Promise.resolve({ data: { units: [] } })),
    setProductLink: vi.fn(),
    setProductLinkNone: vi.fn(),
    revertProductLinkAuto: vi.fn(),
    searchProducts: vi.fn(),
  },
  promocionesAPI: {
    getPromocionesItem: vi.fn(() => Promise.resolve({ data: { promotions: [] } })),
    getMarkupParaPrecio: vi.fn(() => Promise.resolve({ data: { nuestro_markup: 12 } })),
    refreshItemPromociones: vi.fn(() => Promise.resolve({ data: { ok: true } })),
    postPromocionItem: vi.fn(),
    descartarHayMejores: vi.fn(() => Promise.resolve({ data: { ok: true } })),
    confirmarSinPromosML: vi.fn(() => Promise.resolve({ data: { sin_promos_confirmado: true, promos_en_ml: 0 } })),
  },
  preciosAPI: { obtenerProducto: vi.fn(), tipoCambioActual: vi.fn(), calcularMarkup: vi.fn(), calcularPorMarkup: vi.fn(), setRapido: vi.fn(), setCuota: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

// Everything is allowed except the margin, which each test grants on purpose.
let canSeeMargin = false;
let canManage = true;
let canSeePromos = true;
let canWritePromos = true;
let canSeeProducts = true;
let canSeeSales = true;
// The price-edit codes the user holds (every other code is granted).
let priceEditCodes = [];
const PRICE_EDIT_CODES = [
  'productos.editar_precio_clasica',
  'productos.editar_precio_cuotas',
  'productos.toggle_rebate',
  'productos.toggle_web_transferencia',
  'tienda.editar_precio_gremio',
  'tienda.editar_precio_web_transf',
];
vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: (permiso) => {
      if (permiso === 'ml_metricas.ver_ganancia') return canSeeMargin;
      if (permiso === 'ml_metricas.ver') return canSeeSales;
      if (permiso === 'ml_ops.gestionar') return canManage;
      if (permiso === 'promos.ver') return canSeePromos;
      if (permiso === 'promos.escribir') return canWritePromos;
      if (permiso === 'productos.ver') return canSeeProducts;
      if (PRICE_EDIT_CODES.includes(permiso)) return priceEditCodes.includes(permiso);
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
  // Promos opens first and pulls; the pull TTL is module-wide, so each test starts with none.
  resetPromoPulls();
  canSeeMargin = false;
  canManage = true;
  canSeePromos = true;
  canWritePromos = true;
  canSeeProducts = true;
  canSeeSales = true;
  priceEditCodes = [];
  promocionesAPI.getPromocionesItem.mockClear();
  promocionesAPI.getMarkupParaPrecio.mockReset().mockResolvedValue({ data: { nuestro_markup: 12 } });
  promocionesAPI.descartarHayMejores.mockReset().mockResolvedValue({ data: { ok: true } });
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

  it('links the header to the ML seller panel and its promotions, even while loading', () => {
    publicacionesMlAPI.detail.mockReturnValue(new Promise(() => {}));
    renderPanel();
    expect(screen.getByRole('link', { name: 'Ver en el panel de ML' })).toHaveAttribute(
      'href',
      'https://vendedores.mercadolibre.com.ar/publicaciones?page=1&sort=DEFAULT&search=1100000001',
    );
    expect(screen.getByRole('link', { name: 'Ver promociones en ML' })).toHaveAttribute(
      'href',
      'https://vendedores.mercadolibre.com.ar/publicaciones/listado/promos?page=1&search=1100000001',
    );
  });

  it('shows the listing type badge between copy MLA and the seller-panel links once detail is ready', async () => {
    renderPanel();
    await screen.findByRole('heading', { name: /Router TP-Link Archer AX55/ });
    const copy = screen.getByRole('button', { name: 'Copiar MLA' });
    const seller = screen.getByRole('link', { name: 'Ver en el panel de ML' });
    const meta = copy.parentElement;
    const tipo = within(meta).getByText('6 cuotas');
    expect(copy.compareDocumentPosition(tipo) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(tipo.compareDocumentPosition(seller) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
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

describe('going back to the product', () => {
  it('without onBack there is no way back', async () => {
    renderPanel();
    await screen.findByRole('heading', { name: /Router TP-Link Archer AX55/ });
    expect(screen.queryByRole('button', { name: /^Volver/ })).not.toBeInTheDocument();
  });

  it('"Volver a <producto>" goes back, even while the detail is loading', async () => {
    publicacionesMlAPI.detail.mockReturnValue(new Promise(() => {}));
    const onBack = vi.fn();
    const user = userEvent.setup();
    renderPanel({ onBack, backLabel: 'Router Archer AX55' });
    await user.click(screen.getByRole('button', { name: 'Volver a Router Archer AX55' }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it('without the product name it reads "Volver al producto"', async () => {
    renderPanel({ onBack: vi.fn() });
    expect(screen.getByRole('button', { name: 'Volver al producto' })).toBeInTheDocument();
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

  it('the default registry opens on Promos (S1)', async () => {
    renderPanel();
    expect(await screen.findByRole('tab', { name: 'Promos' })).toHaveAttribute('aria-selected', 'true');
  });

  it('opens on Precios without promos.ver, for a linked product (S1)', async () => {
    canSeePromos = false;
    publicacionesMlAPI.detail.mockResolvedValue({ data: DETAIL_LINKED });
    renderPanel();
    expect(await screen.findByRole('tab', { name: 'Precios' })).toHaveAttribute('aria-selected', 'true');
  });

  it('opens on Resumen without promos.ver and without a price permission (S1)', async () => {
    canSeePromos = false;
    canSeeProducts = false;
    publicacionesMlAPI.detail.mockResolvedValue({ data: DETAIL_LINKED });
    renderPanel();
    expect(await screen.findByRole('tab', { name: 'Resumen' })).toHaveAttribute('aria-selected', 'true');
  });

  it('leaves the promotion out of Resumen for whoever has the Promos tab, and keeps it for whoever has not', async () => {
    renderPanel({ tab: 'resumen' });
    const data = await screen.findByRole('region', { name: 'Datos de la publicación' });
    expect(within(data).queryByText('Promoción')).not.toBeInTheDocument();
    cleanup();
    canSeePromos = false;
    renderPanel({ tab: 'resumen' });
    expect(within(await screen.findByRole('region', { name: 'Datos de la publicación' })).getByText('Promoción')).toBeInTheDocument();
  });

  it('a tab in the URL keeps winning over the default (S1)', async () => {
    renderPanel({ tab: 'resumen' });
    expect(await screen.findByRole('tab', { name: 'Resumen' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Promos' })).toHaveAttribute('aria-selected', 'false');
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
  it('is offered with promos.ver and asks ML for nothing while another tab is open (the throttle is shared)', async () => {
    renderPanel({ tab: 'resumen' });
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

describe('after applying a promotion', () => {
  it('re-reads the detail silently and asks the list to reload its row, without remounting the tab', async () => {
    const user = userEvent.setup();
    const onListReload = vi.fn();
    promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [{ promotion_id: 'D1', promotion_type: 'DEAL', name: 'Deal promo', price: 80, status: 'candidate' }] } });
    promocionesAPI.postPromocionItem.mockResolvedValue({ data: { submitted: true, status: 'submitted' } });
    renderPanel({ tab: 'promociones', onListReload });
    await user.click(await screen.findByRole('button', { name: /^aplicar$/i }));
    await user.click(screen.getByRole('button', { name: /sí, aplicar/i }));
    await waitFor(() => expect(publicacionesMlAPI.detail).toHaveBeenCalledTimes(2));
    expect(onListReload).toHaveBeenCalledTimes(1);
    // The tab never went through "loading": its feedback is still there and so is its content.
    expect(screen.getByText(/puede tardar en reflejarse/i)).toBeInTheDocument();
    expect(screen.queryByRole('status', { name: 'Cargando publicación' })).not.toBeInTheDocument();
    expect(promocionesAPI.refreshItemPromociones).toHaveBeenCalledTimes(1);
  });
});

describe('the tab strip', () => {
  // jsdom has no layout: give the strip a 240px window and the open tab a place past its edge.
  const stubLayout = () => {
    const names = ['clientWidth', 'offsetLeft', 'offsetWidth'];
    const originals = names.map((name) => [name, Object.getOwnPropertyDescriptor(HTMLElement.prototype, name)]);
    const define = (name, get) => Object.defineProperty(HTMLElement.prototype, name, { configurable: true, get });
    define('clientWidth', function width() {
      return this.getAttribute('role') === 'tablist' ? 240 : 0;
    });
    define('offsetLeft', function left() {
      return this.getAttribute('role') === 'tab' && this.textContent === 'Promos' ? 300 : 0;
    });
    define('offsetWidth', function width() {
      return this.getAttribute('role') === 'tab' ? 60 : 0;
    });
    return () =>
      originals.forEach(([name, descriptor]) => {
        if (descriptor) Object.defineProperty(HTMLElement.prototype, name, descriptor);
        else delete HTMLElement.prototype[name];
      });
  };

  it('scrolls the strip sideways to the open tab, without moving anything else, so a tab past the edge is never lost', async () => {
    const restore = stubLayout();
    try {
      renderPanel({ tab: 'promociones' });
      const strip = await screen.findByRole('tablist');
      await waitFor(() => expect(strip.scrollLeft).toBe(300 + 60 - 240));
    } finally {
      restore();
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

describe('the Precios tab', () => {
  beforeEach(() => {
    publicacionesMlAPI.detail.mockResolvedValue({ data: DETAIL_LINKED });
    preciosAPI.obtenerProducto.mockReset();
    preciosAPI.obtenerProducto.mockResolvedValue({ data: { item_id: 4101, codigo: 'ARCHER-AX55', descripcion: 'Router Archer AX55', precio_lista_ml: 98500.5, markup: 18.4 } });
  });

  it('shows the prices of the linked product to who can see products', async () => {
    renderPanel({ tab: 'precios' });
    expect(await screen.findByRole('tab', { name: 'Precios' })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByRole('row', { name: /^Clásica\b/ })).toHaveTextContent('98.500,50');
    expect(preciosAPI.obtenerProducto).toHaveBeenCalledWith(4101);
  });

  it.each(['productos.editar_precio_clasica', 'tienda.editar_precio_gremio', 'tienda.editar_precio_web_transf'])(
    'shows them without productos.ver to who can edit them (%s)',
    async (code) => {
      canSeeProducts = false;
      priceEditCodes = [code];
      renderPanel({ tab: 'precios' });
      expect(await screen.findByRole('tab', { name: 'Precios' })).toHaveAttribute('aria-selected', 'true');
      expect(preciosAPI.obtenerProducto).toHaveBeenCalledWith(4101);
    },
  );

  it('a price write re-reads the detail and asks the page to reload its list', async () => {
    const user = userEvent.setup();
    const onListReload = vi.fn();
    priceEditCodes = ['productos.editar_precio_clasica'];
    preciosAPI.calcularMarkup.mockResolvedValue({ data: { markup: 12 } });
    preciosAPI.setRapido.mockResolvedValue({ data: { item_id: 4101 } });
    renderPanel({ tab: 'precios', onListReload });

    await user.click(await screen.findByRole('button', { name: 'Editar Clásica' }));
    await user.type(screen.getByRole('textbox', { name: 'Clásica' }), '{Enter}');

    await waitFor(() => expect(onListReload).toHaveBeenCalledTimes(1));
    expect(preciosAPI.setRapido).toHaveBeenCalledWith(expect.objectContaining({ item_id: 4101 }));
    expect(publicacionesMlAPI.detail).toHaveBeenCalledTimes(2);
  });

  it('shows the product cost only with ml_metricas.ver_ganancia, the IVA rate always', async () => {
    preciosAPI.obtenerProducto.mockResolvedValue({ data: { item_id: 4101, codigo: 'ARCHER-AX55', moneda_costo: 'ARS', costo: 64000, costo_ars: 64000, iva: 21 } });
    const { unmount } = renderPanel({ tab: 'precios' });
    const hidden = await screen.findByRole('group', { name: 'Referencias del producto' });
    expect(hidden).toHaveTextContent('21%');
    expect(hidden).not.toHaveTextContent('64.000');
    unmount();

    canSeeMargin = true;
    renderPanel({ tab: 'precios' });
    expect(await screen.findByRole('group', { name: 'Referencias del producto' })).toHaveTextContent('$ 64.000,00');
  });

  it('who only sees products gets no edit control', async () => {
    renderPanel({ tab: 'precios' });
    await screen.findByRole('row', { name: /^Clásica\b/ });
    expect(screen.queryByRole('button', { name: /^Editar / })).not.toBeInTheDocument();
  });

  it('does not exist without productos.ver nor a price-edit code', async () => {
    canSeeProducts = false;
    renderPanel({ tab: 'precios' });
    await screen.findByRole('tab', { name: 'Resumen' });
    expect(screen.queryByRole('tab', { name: 'Precios' })).not.toBeInTheDocument();
    expect(preciosAPI.obtenerProducto).not.toHaveBeenCalled();
  });
});

describe('a link write in the Producto tab', () => {
  it('re-reads the detail and asks the page to reload the list, so the card shows the new state', async () => {
    const user = userEvent.setup();
    const onListReload = vi.fn();
    publicacionesMlAPI.setProductLinkNone.mockResolvedValue({ data: { changed: true } });
    publicacionesMlAPI.detail
      .mockResolvedValueOnce({ data: makeDetail({ links: [ITEM_LINK] }) })
      .mockResolvedValue({
        data: makeDetail({
          links: [{ ...ITEM_LINK, state: 'sin_producto', source: 'manual_none', match_status: 'unmatched', producto_item_id: null, codigo: null, descripcion: null, marca: null, note: 'Combo' }],
        }),
      });
    renderPanel({ tab: 'producto', onListReload });

    const card = within(await screen.findByRole('region', { name: 'Vínculos' })).getByRole('listitem');
    expect(card).toHaveTextContent('Automático');
    await user.click(within(card).getByRole('button', { name: 'Marcar sin producto' }));
    await user.click(within(card).getByRole('button', { name: 'Confirmar' }));

    await waitFor(() => expect(publicacionesMlAPI.detail).toHaveBeenCalledTimes(2));
    expect(onListReload).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(within(screen.getByRole('region', { name: 'Vínculos' })).getByRole('listitem')).toHaveTextContent('Sin producto'));
    expect(within(screen.getByRole('region', { name: 'Vínculos' })).getByRole('listitem')).toHaveTextContent('Combo');
  });
});


describe('header figures (S1)', () => {
  const SALES = { sales_30d: { units: 12, gross: 1500 }, metrics: { units_30d: 12, gross_30d: 1500 } };
  const MARKUP = { min: 15, max: 15, worst: 15, any_negative: false, reason: 'ok', partial: 0 };
  const withRow = (row) => makeDetail({ row: { ...ITEMS[0], ...row } });

  const figures = () => screen.getByRole('region', { name: 'Cifras de la publicación' });
  /** The value and the note of one figure, by its label. */
  const figure = (name) => {
    const term = within(figures()).getByText(name, { selector: 'dt' });
    return term.nextElementSibling.textContent;
  };
  const labels = () => within(figures()).queryAllByRole('term').map((dt) => dt.textContent);

  it('has no Ventas 30 días figure while the detail does not send its sales (an older backend)', async () => {
    const { sales_30d: _omitted, ...row } = { ...ITEMS[0], ...SALES };
    publicacionesMlAPI.detail.mockResolvedValue({ data: makeDetail({ row }) });
    renderPanel({ tab: 'resumen' });
    await screen.findByRole('region', { name: 'Cifras de la publicación' });
    expect(labels()).toEqual(['Precio', 'Stock']);
  });

  it('says the markup range is partial when some variations have no cost, as the table does', async () => {
    canSeeMargin = true;
    publicacionesMlAPI.detail.mockResolvedValue({
      data: { ...withRow({ markup: { ...MARKUP, partial: 2 } }), markup_breakdown: null },
    });
    renderPanel({ tab: 'resumen' });
    await screen.findByRole('region', { name: 'Cifras de la publicación' });
    expect(within(figures()).getByTitle('2 variaciones sin costo no entran en el rango')).toHaveTextContent('(parcial)');
  });

  it('with ver_ganancia and no markup, a dash under the price that says why; a range reads as one', async () => {
    canSeeMargin = true;
    publicacionesMlAPI.detail.mockResolvedValue({
      data: { ...withRow({ markup: { min: null, max: null, reason: 'sin_costo', partial: 0 } }), markup_breakdown: null },
    });
    const { unmount } = renderPanel({ tab: 'resumen' });
    await screen.findByRole('region', { name: 'Cifras de la publicación' });
    const empty = within(figures()).getByText('—', { exact: false, selector: 'span[title]' });
    expect(empty).toHaveAttribute('title', MARKUP_REASONS.sin_costo);
    expect(figure('Precio')).not.toMatch(/\b0(,0)?%/);
    unmount();
    publicacionesMlAPI.detail.mockResolvedValue({
      data: { ...withRow({ markup: { min: 8.5, max: 21, worst: 8.5, any_negative: false, reason: 'ok', partial: 0 } }), markup_breakdown: null },
    });
    renderPanel({ tab: 'resumen' });
    await screen.findByRole('region', { name: 'Cifras de la publicación' });
    expect(figure('Precio')).toContain('8,5% – 21,0%');
  });

  it('shows the price, Stock and Ventas 30 días from the row; without ver_ganancia, no markup under the price', async () => {
    publicacionesMlAPI.detail.mockResolvedValue({ data: withRow(SALES) });
    renderPanel({ tab: 'resumen' });
    await screen.findByRole('region', { name: 'Cifras de la publicación' });
    expect(labels()).toEqual(['Precio', 'Stock', 'Ventas 30 días']);
    expect(figure('Precio')).toBe('$ 98.500,50');
    // The total only: Full and propio are the Resumen's stock breakdown, not repeated here.
    expect(figure('Stock')).toBe('34unidades');
    expect(figure('Ventas 30 días')).toContain('12');
    expect(figure('Ventas 30 días')).toContain('1.500,00');
  });

  it('shows each figure under its visible label, as the approved design: Precio with its markup under it, only with ver_ganancia', async () => {
    canSeeMargin = true;
    publicacionesMlAPI.detail.mockResolvedValue({ data: { ...withRow({ ...SALES, markup: MARKUP }), markup_breakdown: null } });
    renderPanel({ tab: 'resumen' });
    await screen.findByRole('region', { name: 'Cifras de la publicación' });
    expect(labels()).toEqual(['Precio', 'Stock', 'Ventas 30 días']);
    // Owner (P3): the labels show, once per card; none is for screen readers only.
    for (const term of within(figures()).getAllByRole('term')) expect(term.className).not.toMatch(/visuallyHidden/);
    expect(figure('Precio')).toBe('$ 98.500,50Markup 15,0%');
    expect(within(figures()).getByTitle('Markup')).not.toHaveAttribute('data-negative');
  });

  it('colours a negative markup apart', async () => {
    canSeeMargin = true;
    const negative = { ...MARKUP, min: -4, max: -4, worst: -4, any_negative: true };
    publicacionesMlAPI.detail.mockResolvedValue({ data: { ...withRow({ markup: negative }), markup_breakdown: null } });
    renderPanel({ tab: 'resumen' });
    await screen.findByRole('region', { name: 'Cifras de la publicación' });
    expect(within(figures()).getByTitle('Markup')).toHaveAttribute('data-negative');
  });

  it('has no Ventas 30 días without ml_metricas.ver', async () => {
    canSeeSales = false;
    publicacionesMlAPI.detail.mockResolvedValue({ data: withRow({}) });
    renderPanel({ tab: 'resumen' });
    await screen.findByRole('region', { name: 'Cifras de la publicación' });
    expect(labels()).toEqual(['Precio', 'Stock']);
  });

  it('shows a dash, never 0, when the detail has no sales figure for a viewer who may see it', async () => {
    publicacionesMlAPI.detail.mockResolvedValue({ data: withRow({ sales_30d: { units: null, gross: null } }) });
    renderPanel({ tab: 'resumen' });
    await screen.findByRole('region', { name: 'Cifras de la publicación' });
    expect(figure('Ventas 30 días')).toBe('—');
  });

  it('keeps the publication status in the header, since Resumen no longer lists it', async () => {
    publicacionesMlAPI.detail.mockResolvedValue({ data: withRow(SALES) });
    renderPanel({ tab: 'resumen' });
    await screen.findByRole('region', { name: 'Cifras de la publicación' });
    expect(within(figures().closest('header')).getByText('Activa')).toBeInTheDocument();
  });

  it.each(['promociones', 'resumen'])('stays in the header on the %s tab', async (tab) => {
    publicacionesMlAPI.detail.mockResolvedValue({ data: withRow(SALES) });
    renderPanel({ tab });
    await screen.findByRole('region', { name: 'Cifras de la publicación' });
    expect(figures().closest('header')).not.toBeNull();
  });
});

describe('hay_mejores chooser outside MODO', () => {
  const flaggedDetail = () =>
    makeDetail({
      row: {
        ...DETAIL_RESPONSE.row,
        hay_mejores_ofertas: true,
        price: { ...(DETAIL_RESPONSE.row.price || {}), amount: 80000 },
      },
    });

  it('keeps tabs and footer while showing the chooser block', async () => {
    publicacionesMlAPI.detail.mockResolvedValue({ data: flaggedDetail() });
    renderPanel({ tab: 'resumen' });
    await screen.findByRole('region', { name: 'Candidatas mejores' });
    expect(screen.getByRole('tablist', { name: 'Secciones de la publicación' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Nuevo precio')).not.toBeInTheDocument();
  });

  it('hides the chooser after Descartar and keeps tabs', async () => {
    const user = userEvent.setup();
    publicacionesMlAPI.detail.mockResolvedValue({ data: flaggedDetail() });
    renderPanel({ tab: 'resumen' });
    await screen.findByRole('region', { name: 'Candidatas mejores' });
    await user.click(screen.getByRole('button', { name: 'Descartar sugerencia' }));
    await waitFor(() => expect(promocionesAPI.descartarHayMejores).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Candidatas mejores' })).not.toBeInTheDocument());
    expect(screen.getByRole('tablist', { name: 'Secciones de la publicación' })).toBeInTheDocument();
  });

  describe('with a suggested SMART', () => {
    const smart = {
      promotion_id: 'P-SUG',
      promotion_type: 'SMART',
      status: 'candidate',
      name: 'Potencia tus ventas',
      price: 70000,
      nuestro_markup: 15,
    };

    beforeEach(() => {
      promocionesAPI.getPromocionesItem.mockResolvedValue({ data: { promotions: [smart] } });
      promocionesAPI.postPromocionItem.mockReset().mockResolvedValue({ data: { status: 'submitted', precio_difiere: false } });
    });

    it('applies the suggestion through the confirmation and keeps the panel open', async () => {
      const user = userEvent.setup();
      const onClose = vi.fn();
      publicacionesMlAPI.detail.mockResolvedValue({ data: flaggedDetail() });
      renderPanel({ tab: 'resumen', onClose });
      await user.click(await screen.findByRole('button', { name: 'Aplicar sugerencia' }));
      expect(promocionesAPI.postPromocionItem).not.toHaveBeenCalled();
      await user.click(screen.getByRole('button', { name: 'Sí, aplicar' }));
      await waitFor(() =>
        expect(promocionesAPI.postPromocionItem).toHaveBeenCalledWith(
          'MLA1100000001',
          expect.objectContaining({ promotion_id: 'P-SUG', precio_visto: 70000 }),
        ),
      );
      expect(onClose).not.toHaveBeenCalled();
    });

    it('marks the suggested row in the Promos tab instead of repeating the banner', async () => {
      publicacionesMlAPI.detail.mockResolvedValue({ data: flaggedDetail() });
      renderPanel({ tab: 'promociones' });
      await screen.findByRole('button', { name: 'Aplicar sugerencia' });
      const tabRow = (await screen.findAllByText('Potencia tus ventas'))
        .map((el) => el.closest('li'))
        .find((li) => li && within(li).queryByRole('button', { name: /^Aplicar$/ }));
      await waitFor(() => expect(within(tabRow).getByText('Sugerida')).toBeInTheDocument());
      expect(screen.getAllByText(/Hay candidatas mejores/)).toHaveLength(1);
    });
  });

  it('does not mount the chooser without promos.escribir', async () => {
    canWritePromos = false;
    publicacionesMlAPI.detail.mockResolvedValue({ data: flaggedDetail() });
    renderPanel({ tab: 'resumen' });
    await screen.findByRole('tablist', { name: 'Secciones de la publicación' });
    expect(screen.queryByRole('region', { name: 'Candidatas mejores' })).not.toBeInTheDocument();
  });
});
