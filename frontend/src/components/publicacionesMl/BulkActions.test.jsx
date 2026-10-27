/**
 * Bulk pricing actions of Publicaciones ML: they act on PRODUCTS, the products of the publications the filter
 * selects (`GET /ml-publications/view/product-ids`), or on the products the operator checked. Fail closed: no
 * resolved set, no action.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import BulkActions from './BulkActions';
import api, { publicacionesMlAPI } from '../../services/api';

vi.mock('../../services/api', () => ({
  default: { post: vi.fn(), get: vi.fn() },
  productosAPI: { listar: vi.fn() },
  publicacionesMlAPI: { productIds: vi.fn() },
}));

let granted = new Set();
vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: (permiso) => granted.has(permiso) }),
}));

const ALL = ['productos.calcular_web_masivo', 'productos.calcular_pvp_masivo', 'productos.aplicar_markup_masivo'];
const FILTERS = {
  q: '', familia: '', evento_desde: '', markup_neg: '', markup_min: '', markup_max: '',
  estado: ['active'], estado_excluir: [], tiendas: [], marcas: [], categorias: [], subcategorias: [], pms: [],
  tipo: [], vinculo: [], stock: [], evento: [], rebate: '', oferta: '', webtransf: '', tiendanube: '', outofcards: '',
  vista: '', pagina: 1, limite: 50,
};

const resolved = (body) => publicacionesMlAPI.productIds.mockResolvedValue({ data: body });

function renderBulk(props = {}) {
  return render(
    <BulkActions filters={FILTERS} checkedIds={new Set()} onClearChecked={() => {}} canSeeMargin={false} {...props} />,
  );
}

const openMenu = async (user) => user.click(await screen.findByRole('button', { name: /acciones masivas/i }));

describe('BulkActions', () => {
  // The bulk modals confirm in an in-app dialog; the browser's confirm() must never run.
  let nativeConfirm;

  beforeEach(() => {
    vi.clearAllMocks();
    granted = new Set(ALL);
    nativeConfirm = vi.fn(() => true);
    vi.stubGlobal('confirm', nativeConfirm);
    api.post.mockResolvedValue({ data: { procesados: 2 } });
  });

  afterEach(() => vi.unstubAllGlobals());

  it('shows how many products the filter selects, and the publications left out', async () => {
    resolved({ item_ids: [4101, 4102], count: 2, sin_producto: 3 });
    renderBulk();
    expect(await screen.findByRole('button', { name: /acciones masivas \(2 productos\)/i })).toBeEnabled();
    expect(publicacionesMlAPI.productIds).toHaveBeenCalledWith({ estado: 'active' }, expect.anything());
    await openMenu(userEvent.setup());
    expect(screen.getByText(/3 publicaciones sin producto quedan afuera/i)).toBeInTheDocument();
  });

  it('runs a bulk calculation over exactly the resolved products', async () => {
    resolved({ item_ids: [4101, 4102], count: 2, sin_producto: 0 });
    const user = userEvent.setup();
    renderBulk();
    await openMenu(user);
    await user.click(screen.getByRole('menuitem', { name: /calcular web transf/i }));
    await user.click(screen.getByRole('button', { name: /calcular precios/i }));
    await user.click(await screen.findByRole('button', { name: 'Confirmar' }));
    await waitFor(() => expect(api.post).toHaveBeenCalled());
    const [url, body] = api.post.mock.calls[0];
    expect(url).toBe('/productos/calcular-web-masivo');
    expect(body.item_ids).toEqual([4101, 4102]);
    expect(body).not.toHaveProperty('filtros');
    expect(nativeConfirm).not.toHaveBeenCalled();
  });

  it('acts on the checked products when there are any', async () => {
    resolved({ item_ids: [4101, 4102, 4103], count: 3, sin_producto: 0 });
    const user = userEvent.setup();
    renderBulk({ checkedIds: new Set([4103]) });
    expect(await screen.findByRole('button', { name: /acciones masivas \(1 producto seleccionado\)/i })).toBeEnabled();
    await openMenu(user);
    await user.click(screen.getByRole('menuitem', { name: /calcular pvp/i }));
    await user.click(screen.getByRole('button', { name: /calcular precios pvp/i }));
    await user.click(await screen.findByRole('button', { name: 'Confirmar' }));
    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(api.post.mock.calls[0][1].item_ids).toEqual([4103]);
    expect(nativeConfirm).not.toHaveBeenCalled();
  });

  it('fails closed when the resolver refuses (over the cap)', async () => {
    publicacionesMlAPI.productIds.mockRejectedValue({
      response: { status: 422, data: { error: { code: 'demasiados_productos', message: 'El filtro selecciona 12000 productos' } } },
    });
    renderBulk();
    const button = await screen.findByRole('button', { name: /acciones masivas/i });
    await waitFor(() => expect(button).toBeDisabled());
    expect(button).toHaveAttribute('title', expect.stringMatching(/12000 productos/));
  });

  it('fails closed when the filter selects no product', async () => {
    resolved({ item_ids: [], count: 0, sin_producto: 4 });
    renderBulk();
    const button = await screen.findByRole('button', { name: /acciones masivas/i });
    await waitFor(() => expect(button).toBeDisabled());
  });

  it('a markup filter of the publication list reaches the resolver: the set is the products of what the list shows', async () => {
    resolved({ item_ids: [4101], count: 1, sin_producto: 0, fuera_de_catalogo: 0 });
    renderBulk({ filters: { ...FILTERS, markup_neg: '1', markup_min: '-5,5' }, canSeeMargin: true });
    expect(await screen.findByRole('button', { name: /acciones masivas \(1 producto\)/i })).toBeEnabled();
    expect(publicacionesMlAPI.productIds).toHaveBeenCalledWith(
      { estado: 'active', markup_neg: true, markup_min: '-5.5' },
      expect.anything(),
    );
  });

  it('the markup filters are not sent where the list does not apply them (Producto view, no permission)', async () => {
    resolved({ item_ids: [4101], count: 1, sin_producto: 0, fuera_de_catalogo: 0 });
    const markup = { ...FILTERS, markup_neg: '1' };
    const { unmount } = renderBulk({ filters: { ...markup, vista: 'producto' }, canSeeMargin: true });
    await screen.findByRole('button', { name: /acciones masivas \(1 producto\)/i });
    expect(publicacionesMlAPI.productIds).toHaveBeenLastCalledWith({ estado: 'active' }, expect.anything());
    unmount();
    renderBulk({ filters: markup, canSeeMargin: false });
    await screen.findByRole('button', { name: /acciones masivas \(1 producto\)/i });
    expect(publicacionesMlAPI.productIds).toHaveBeenLastCalledWith({ estado: 'active' }, expect.anything());
  });

  it('says how many linked products are gone from the catalog and left out', async () => {
    resolved({ item_ids: [4101], count: 1, sin_producto: 0, fuera_de_catalogo: 2 });
    renderBulk();
    await openMenu(userEvent.setup());
    expect(screen.getByText(/2 productos fuera del catálogo quedan afuera/i)).toBeInTheDocument();
  });

  it('an open modal keeps the set it opened with while the set re-resolves after a run', async () => {
    granted = new Set([...ALL, 'productos.editar_precio_cuotas']);
    publicacionesMlAPI.productIds
      .mockResolvedValueOnce({ data: { item_ids: [4101, 4102, 4103], count: 3, sin_producto: 0 } })
      .mockResolvedValue({ data: { item_ids: [9001, 9002], count: 2, sin_producto: 0 } });
    // The cuotas config lands and the markup fails: the run counts as done (the set re-resolves) and the form stays open.
    api.post.mockResolvedValueOnce({ data: {} }).mockRejectedValueOnce(new Error('lote caído'));
    const user = userEvent.setup();
    renderBulk();
    await openMenu(user);
    await user.click(screen.getByRole('menuitem', { name: /markup y cuotas/i }));
    await user.click(screen.getByRole('checkbox', { name: /config de cuotas/i }));
    await user.type(screen.getByPlaceholderText('No cambiar'), '1');
    await user.click(screen.getByRole('button', { name: /aplicar a 3 productos/i }));
    await waitFor(() => expect(publicacionesMlAPI.productIds).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByRole('button', { name: /acciones masivas \(2 productos\)/i })).toBeEnabled());

    expect(screen.getByText(/opera sobre 3 productos/i)).toBeInTheDocument();
    api.post.mockClear();
    api.post.mockResolvedValue({ data: { total: 3, ok: 3, errores: 0, resultados: [] } });
    await user.click(screen.getByRole('button', { name: /aplicar a 3 productos/i }));
    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(2));
    for (const [, body] of api.post.mock.calls) expect(body.item_ids).toEqual([4101, 4102, 4103]);
  });

  it('offers only the actions the user may run, and nothing without any', async () => {
    resolved({ item_ids: [4101], count: 1, sin_producto: 0 });
    granted = new Set(['productos.calcular_pvp_masivo']);
    const user = userEvent.setup();
    const { unmount } = renderBulk();
    await openMenu(user);
    expect(screen.getAllByRole('menuitem').map((item) => item.textContent)).toEqual(['Calcular PVP']);
    unmount();
    granted = new Set();
    renderBulk();
    expect(screen.queryByRole('button', { name: /acciones masivas/i })).not.toBeInTheDocument();
  });

  describe('recalcular cuotas (Productos\' "Recalcular Cuotas Web/PVP")', () => {
    const CUOTAS = 'productos.editar_precio_cuotas';

    it('recalculates the web cuotas of exactly the resolved products, after an in-app confirmation', async () => {
      resolved({ item_ids: [4101, 4102], count: 2, sin_producto: 0 });
      granted = new Set([CUOTAS]);
      api.post.mockResolvedValue({ data: { procesados: 2, errores: 0, lista_tipo: 'web' } });
      const user = userEvent.setup();
      renderBulk();
      await openMenu(user);
      await user.click(screen.getByRole('menuitem', { name: 'Recalcular cuotas Web' }));
      const title = await screen.findByRole('heading', { name: 'Recalcular cuotas Web' });
      const dialog = title.closest('.modal-tesla');
      expect(dialog).toHaveTextContent('2 productos');
      expect(dialog).toHaveTextContent('No cambia el precio Web');
      expect(api.post).not.toHaveBeenCalled();
      await user.click(screen.getByRole('button', { name: 'Confirmar' }));
      await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
      expect(api.post).toHaveBeenCalledWith('/productos/recalcular-cuotas-masivo', {
        lista_tipo: 'web',
        item_ids: [4101, 4102],
      });
      expect(await screen.findByText('Cuotas WEB recalculadas: 2 productos')).toBeInTheDocument();
      expect(nativeConfirm).not.toHaveBeenCalled();
    });

    it('recalculates the PVP cuotas of the checked products and reports the ones that failed', async () => {
      resolved({ item_ids: [4101, 4102, 4103], count: 3, sin_producto: 0 });
      granted = new Set([CUOTAS]);
      api.post.mockResolvedValue({ data: { procesados: 1, errores: 1, lista_tipo: 'pvp' } });
      const user = userEvent.setup();
      renderBulk({ checkedIds: new Set([4103, 4101]) });
      await openMenu(user);
      await user.click(screen.getByRole('menuitem', { name: 'Recalcular cuotas PVP' }));
      await user.click(await screen.findByRole('button', { name: 'Confirmar' }));
      await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
      expect(api.post.mock.calls[0][1]).toEqual({ lista_tipo: 'pvp', item_ids: [4103, 4101] });
      expect(await screen.findByText('Cuotas PVP recalculadas: 1 producto (1 con errores)')).toBeInTheDocument();
    });

    it('cancelling the confirmation writes nothing', async () => {
      resolved({ item_ids: [4101], count: 1, sin_producto: 0 });
      granted = new Set([CUOTAS]);
      const user = userEvent.setup();
      renderBulk();
      await openMenu(user);
      await user.click(screen.getByRole('menuitem', { name: 'Recalcular cuotas Web' }));
      await user.click(await screen.findByRole('button', { name: 'Cancelar' }));
      await waitFor(() => expect(screen.queryByRole('heading', { name: 'Recalcular cuotas Web' })).not.toBeInTheDocument());
      expect(api.post).not.toHaveBeenCalled();
    });

    it('says why when the run fails, and keeps the dialog for a retry', async () => {
      resolved({ item_ids: [4101], count: 1, sin_producto: 0 });
      granted = new Set([CUOTAS]);
      api.post.mockRejectedValue({ response: { data: { detail: '1 producto(s) fuera del catálogo ERP (4101); no se aplicó nada' } } });
      const user = userEvent.setup();
      renderBulk();
      await openMenu(user);
      await user.click(screen.getByRole('menuitem', { name: 'Recalcular cuotas Web' }));
      await user.click(await screen.findByRole('button', { name: 'Confirmar' }));
      expect(await screen.findByText(/fuera del catálogo ERP \(4101\); no se aplicó nada/)).toBeInTheDocument();
      expect(screen.getByRole('heading', { name: 'Recalcular cuotas Web' })).toBeInTheDocument();
    });

    it('a validation error (a list of field errors) shows as text, never as an object', async () => {
      resolved({ item_ids: [4101], count: 1, sin_producto: 0 });
      granted = new Set([CUOTAS]);
      api.post.mockRejectedValue({ response: { data: { detail: [{ loc: ['body', 'item_ids'], msg: 'too many' }] } } });
      const user = userEvent.setup();
      renderBulk();
      await openMenu(user);
      await user.click(screen.getByRole('menuitem', { name: 'Recalcular cuotas Web' }));
      await user.click(await screen.findByRole('button', { name: 'Confirmar' }));
      expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron recalcular las cuotas');
    });

    it('is offered only with the cuotas permission', async () => {
      resolved({ item_ids: [4101], count: 1, sin_producto: 0 });
      const user = userEvent.setup();
      renderBulk();
      await openMenu(user);
      expect(screen.queryByRole('menuitem', { name: /recalcular cuotas/i })).not.toBeInTheDocument();
    });
  });
});
