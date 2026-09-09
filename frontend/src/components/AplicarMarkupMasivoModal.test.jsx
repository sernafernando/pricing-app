/**
 * Spec coverage for productos-acciones-masivas-scope (WU1 / PR1):
 * - Modal count from totalProductos (not page buffer)
 * - Resolve + apply full filtered set (200, not page 50)
 * - Unfiltered N → N
 * - confirm when >50; skip when ≤50
 * - fail-closed empty/mismatch (no catalog widen)
 * - chunks ≤ 100
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AplicarMarkupMasivoModal from './AplicarMarkupMasivoModal';
import api, { productosAPI } from '../services/api';
import {
  resolveFilteredItemIds,
  chunkIds,
  withStableListarOrder,
} from './resolveFilteredItemIds';

vi.mock('../services/api', () => ({
  default: { post: vi.fn(), get: vi.fn() },
  productosAPI: { listar: vi.fn() },
}));

function makeIds(n, prefix = 'ID') {
  return Array.from({ length: n }, (_, i) => `${prefix}${i + 1}`);
}

function mockListarPages(ids, pageSize = 500) {
  productosAPI.listar.mockImplementation(async ({ page = 1, page_size = pageSize }) => {
    const start = (page - 1) * page_size;
    const slice = ids.slice(start, start + page_size);
    return {
      data: {
        total: ids.length,
        productos: slice.map((item_id) => ({ item_id })),
      },
    };
  });
}

function markupOkResponse(itemIds) {
  return {
    data: {
      total: itemIds.length,
      ok: itemIds.length,
      errores: 0,
      resultados: itemIds.map((item_id) => ({
        item_id,
        codigo: item_id,
        descripcion: item_id,
        precio_antes: 100,
        precio_nuevo: 110,
        markup_real: 5,
        ok: true,
      })),
    },
  };
}

const LISTAR_18 = {
  marcas: 'ACME',
  con_stock: true,
  con_precio: true,
};

describe('withStableListarOrder', () => {
  it('adds stable item_id order without altering filter params', () => {
    const params = withStableListarOrder({
      marcas: 'A,B',
      tn_con_descuento: true,
      con_pxq: true,
      promo_tipos: 'SMART',
      promo_estado: 'aplicada',
    });
    expect(params.marcas).toBe('A,B');
    expect(params.tn_con_descuento).toBe(true);
    expect(params.con_pxq).toBe(true);
    expect(params.promo_tipos).toBe('SMART');
    expect(params.promo_estado).toBe('aplicada');
    expect(params.orden_campos).toBe('item_id');
    expect(params.orden_direcciones).toBe('asc');
  });

  it('adds stable item_id order even when unfiltered', () => {
    const params = withStableListarOrder({});
    expect(params).toEqual({
      orden_campos: 'item_id',
      orden_direcciones: 'asc',
    });
  });
});

describe('resolveFilteredItemIds', () => {
  beforeEach(() => vi.clearAllMocks());

  it('pages until all filtered IDs are collected', async () => {
    const ids = makeIds(200);
    mockListarPages(ids, 100);
    const resolved = await resolveFilteredItemIds({
      listar: productosAPI.listar,
      listarParams: LISTAR_18,
      totalProductos: 200,
      pageSize: 100,
    });
    expect(resolved).toHaveLength(200);
    expect(productosAPI.listar).toHaveBeenCalledTimes(2);
    expect(productosAPI.listar.mock.calls[0][0]).toMatchObject({
      marcas: 'ACME',
      con_stock: true,
      page: 1,
      page_size: 100,
      orden_campos: 'item_id',
      orden_direcciones: 'asc',
    });
  });

  it('fail-closed on empty resolve when filters are active', async () => {
    productosAPI.listar.mockResolvedValue({ data: { total: 0, productos: [] } });
    await expect(
      resolveFilteredItemIds({
        listar: productosAPI.listar,
        listarParams: LISTAR_18,
        totalProductos: 18,
      }),
    ).rejects.toMatchObject({ code: 'empty' });
  });

  it('fail-closed on mismatch vs totalProductos when filters are active', async () => {
    mockListarPages(makeIds(10), 500);
    await expect(
      resolveFilteredItemIds({
        listar: productosAPI.listar,
        listarParams: LISTAR_18,
        totalProductos: 18,
      }),
    ).rejects.toMatchObject({ code: 'mismatch' });
  });

  it('fail-closed on mismatch when unfiltered but Total is finite', async () => {
    mockListarPages(makeIds(9), 500);
    await expect(
      resolveFilteredItemIds({
        listar: productosAPI.listar,
        listarParams: {},
        totalProductos: 10,
      }),
    ).rejects.toMatchObject({ code: 'mismatch' });
  });

  it('dedupes duplicated page rows so mismatch is detectable', async () => {
    // Unique size 2 but claimed Total 3 — classic OFFSET reshuffle compensation case.
    productosAPI.listar.mockImplementation(async ({ page = 1 }) => {
      if (page === 1) {
        return { data: { total: 3, productos: [{ item_id: 'A' }, { item_id: 'B' }] } };
      }
      return { data: { total: 3, productos: [{ item_id: 'A' }] } };
    });
    await expect(
      resolveFilteredItemIds({
        listar: productosAPI.listar,
        listarParams: LISTAR_18,
        totalProductos: 3,
        pageSize: 2,
      }),
    ).rejects.toMatchObject({ code: 'mismatch' });
  });

  it('stops with api error when page ceiling is exceeded', async () => {
    productosAPI.listar.mockResolvedValue({
      data: { productos: [{ item_id: 'X1' }, { item_id: 'X2' }] },
    });
    await expect(
      resolveFilteredItemIds({
        listar: productosAPI.listar,
        listarParams: {},
        totalProductos: 2,
        pageSize: 2,
      }),
    ).rejects.toMatchObject({ code: 'api' });
  });

  it('does not fail-closed empty when unfiltered (no page-buffer fallback needed)', async () => {
    productosAPI.listar.mockResolvedValue({ data: { total: 0, productos: [] } });
    const resolved = await resolveFilteredItemIds({
      listar: productosAPI.listar,
      listarParams: {},
      totalProductos: 0,
    });
    expect(resolved).toEqual([]);
  });

  it('maps HTTP 403 to forbidden fail-closed', async () => {
    productosAPI.listar.mockRejectedValue({ response: { status: 403 } });
    await expect(
      resolveFilteredItemIds({
        listar: productosAPI.listar,
        listarParams: LISTAR_18,
        totalProductos: 18,
      }),
    ).rejects.toMatchObject({ code: 'forbidden' });
  });
});

describe('chunkIds', () => {
  it('splits 200 IDs into chunks of at most 100', () => {
    const chunks = chunkIds(makeIds(200), 100);
    expect(chunks).toHaveLength(2);
    expect(chunks.every((c) => c.length <= 100)).toBe(true);
  });
});

async function confirmarSiAparece(user) {
  const confirmar = await screen.findByRole('button', { name: /^Confirmar$/i });
  await user.click(confirmar);
}

describe('AplicarMarkupMasivoModal', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.post.mockImplementation(async (url, body) => {
      if (url.includes('aplicar-markup-masivo')) {
        return markupOkResponse(body.item_ids);
      }
      return { data: { ok: true } };
    });
  });

  it('shows filtered totalProductos (18), not a page-buffer length', () => {
    render(
      <AplicarMarkupMasivoModal
        onClose={() => {}}
        onSuccess={() => {}}
        listarParams={LISTAR_18}
        totalProductos={18}
        showToast={() => {}}
      />,
    );
    expect(screen.getByText(/Acciones masivas — 18 productos/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Aplicar a 18 productos/i })).toBeInTheDocument();
    expect(screen.queryByText(/página actual/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/visibles/i)).not.toBeInTheDocument();
  });

  it('applies full filtered set of 200 IDs (not page buffer 50) in ≤100 chunks', async () => {
    const ids = makeIds(200);
    mockListarPages(ids, 100);
    const showToast = vi.fn();
    const onSuccess = vi.fn();
    const user = userEvent.setup();

    render(
      <AplicarMarkupMasivoModal
        onClose={() => {}}
        onSuccess={onSuccess}
        listarParams={LISTAR_18}
        totalProductos={200}
        showToast={showToast}
      />,
    );

    expect(screen.getByText(/Acciones masivas — 200 productos/i)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Aplicar a 200 productos/i }));
    await confirmarSiAparece(user);

    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    const markupCalls = api.post.mock.calls.filter(([url]) =>
      url.includes('aplicar-markup-masivo'),
    );
    expect(markupCalls).toHaveLength(2);
    expect(markupCalls.every(([, body]) => body.item_ids.length <= 100)).toBe(true);
    const applied = markupCalls.flatMap(([, body]) => body.item_ids);
    expect(applied).toHaveLength(200);
    expect(applied).toEqual(ids);
  });

  it('unfiltered total N applies N IDs', async () => {
    const ids = makeIds(7, 'U');
    mockListarPages(ids, 500);
    const onSuccess = vi.fn();
    const user = userEvent.setup();

    render(
      <AplicarMarkupMasivoModal
        onClose={() => {}}
        onSuccess={onSuccess}
        listarParams={{}}
        totalProductos={7}
        showToast={() => {}}
      />,
    );

    await user.click(screen.getByRole('button', { name: /Aplicar a 7 productos/i }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(screen.queryByRole('button', { name: /^Confirmar$/i })).not.toBeInTheDocument();
    const markupCalls = api.post.mock.calls.filter(([url]) =>
      url.includes('aplicar-markup-masivo'),
    );
    expect(markupCalls).toHaveLength(1);
    expect(markupCalls[0][1].item_ids).toEqual(ids);
  });

  it('requires confirm before writes when count > 50', async () => {
    const ids = makeIds(200);
    mockListarPages(ids, 100);
    const user = userEvent.setup();

    render(
      <AplicarMarkupMasivoModal
        onClose={() => {}}
        onSuccess={() => {}}
        listarParams={LISTAR_18}
        totalProductos={200}
        showToast={() => {}}
      />,
    );

    await user.click(screen.getByRole('button', { name: /Aplicar a 200 productos/i }));
    expect(await screen.findByRole('button', { name: /^Confirmar$/i })).toBeInTheDocument();
    expect(screen.getByText(/Confirmar acciones masivas/i)).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: /^Volver$/i }));
    expect(screen.queryByRole('button', { name: /^Confirmar$/i })).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('skips confirm gate when count ≤ 50', async () => {
    const ids = makeIds(18);
    mockListarPages(ids, 500);
    const onSuccess = vi.fn();
    const user = userEvent.setup();

    render(
      <AplicarMarkupMasivoModal
        onClose={() => {}}
        onSuccess={onSuccess}
        listarParams={LISTAR_18}
        totalProductos={18}
        showToast={() => {}}
      />,
    );

    await user.click(screen.getByRole('button', { name: /Aplicar a 18 productos/i }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(screen.queryByRole('button', { name: /^Confirmar$/i })).not.toBeInTheDocument();
    expect(api.post).toHaveBeenCalled();
  });

  it('fail-closed mismatch: toast error and no write (no catalog widen)', async () => {
    mockListarPages(makeIds(5), 500);
    const showToast = vi.fn();
    const user = userEvent.setup();

    render(
      <AplicarMarkupMasivoModal
        onClose={() => {}}
        onSuccess={() => {}}
        listarParams={LISTAR_18}
        totalProductos={18}
        showToast={showToast}
      />,
    );

    await user.click(screen.getByRole('button', { name: /Aplicar a 18 productos/i }));
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith(expect.stringMatching(/no coincide/i), 'error'),
    );
    expect(api.post).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: /^Confirmar$/i })).not.toBeInTheDocument();
  });

  it('fail-closed empty resolve: toast and no write', async () => {
    productosAPI.listar.mockResolvedValue({ data: { total: 0, productos: [] } });
    const showToast = vi.fn();
    const user = userEvent.setup();

    render(
      <AplicarMarkupMasivoModal
        onClose={() => {}}
        onSuccess={() => {}}
        listarParams={LISTAR_18}
        totalProductos={18}
        showToast={showToast}
      />,
    );

    await user.click(screen.getByRole('button', { name: /Aplicar a 18 productos/i }));
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith(expect.stringMatching(/no resolvió/i), 'error'),
    );
    expect(api.post).not.toHaveBeenCalled();
  });
});

async function setMarkupObjetivo(user, value) {
  const input = screen.getByRole('textbox');
  await user.clear(input);
  await user.type(input, value);
}

function renderModal({
  totalProductos = 18,
  listarParams = LISTAR_18,
  showToast = () => {},
  onSuccess = () => {},
  onClose = () => {},
} = {}) {
  return render(
    <AplicarMarkupMasivoModal
      onClose={onClose}
      onSuccess={onSuccess}
      listarParams={listarParams}
      totalProductos={totalProductos}
      showToast={showToast}
    />,
  );
}

describe('AplicarMarkupMasivoModal markup 0 and negative', () => {
  let confirmSpy;

  beforeEach(() => {
    vi.clearAllMocks();
    confirmSpy = vi.spyOn(window, 'confirm').mockImplementation(() => true);
    api.post.mockImplementation(async (url, body) => {
      if (url.includes('aplicar-markup-masivo')) {
        return markupOkResponse(body.item_ids);
      }
      return { data: { ok: true } };
    });
  });

  afterEach(() => {
    confirmSpy.mockRestore();
  });

  it('markup 0 shows CS-4 Tesla pane then writes after confirm when count ≤ 50', async () => {
    const ids = makeIds(18);
    mockListarPages(ids, 500);
    const onSuccess = vi.fn();
    const user = userEvent.setup();
    renderModal({ onSuccess });

    await setMarkupObjetivo(user, '0');
    await user.click(screen.getByRole('button', { name: /Aplicar a 18 productos/i }));

    expect(await screen.findByText('MarkUp Negativo')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Guardar de todas formas/i })).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
    expect(confirmSpy).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: /Guardar de todas formas/i }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    const markupCalls = api.post.mock.calls.filter(([url]) =>
      url.includes('aplicar-markup-masivo'),
    );
    expect(markupCalls).toHaveLength(1);
    expect(markupCalls[0][1].markup_objetivo).toBe(0);
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it('blur keeps 0 and -3 instead of resetting to 5.0', async () => {
    const user = userEvent.setup();
    renderModal();

    await setMarkupObjetivo(user, '0');
    await user.tab();
    expect(screen.getByRole('textbox')).toHaveValue('0');

    await setMarkupObjetivo(user, '-3');
    await user.tab();
    expect(screen.getByRole('textbox')).toHaveValue('-3');
  });

  it('rejects NaN/empty markup with toast and no write', async () => {
    mockListarPages(makeIds(18), 500);
    const showToast = vi.fn();
    renderModal({ showToast });

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'abc' } });
    fireEvent.click(screen.getByRole('button', { name: /Aplicar a 18 productos/i }));

    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith('Ingresá un markup válido', 'error'),
    );
    expect(api.post).not.toHaveBeenCalled();
    expect(screen.queryByText(/MarkUp Negativo/i)).not.toBeInTheDocument();
    expect(confirmSpy).not.toHaveBeenCalled();

    fireEvent.change(screen.getByRole('textbox'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: /Aplicar a 18 productos/i }));
    await waitFor(() => expect(showToast).toHaveBeenCalledTimes(2));
    expect(showToast).toHaveBeenLastCalledWith('Ingresá un markup válido', 'error');
    expect(api.post).not.toHaveBeenCalled();
  });

  it('rejects markup below -100 with toast naming the floor (no resolve/write)', async () => {
    mockListarPages(makeIds(18), 500);
    const showToast = vi.fn();
    const user = userEvent.setup();
    renderModal({ showToast });

    await setMarkupObjetivo(user, '-500');
    await user.click(screen.getByRole('button', { name: /Aplicar a 18 productos/i }));

    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith(
        'El markup no puede ser menor a -100',
        'error',
      ),
    );
    expect(productosAPI.listar).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
    expect(screen.queryByText(/MarkUp Negativo/i)).not.toBeInTheDocument();
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it('negative markup shows CS-4 Tesla pane then writes after confirm', async () => {
    const ids = makeIds(18);
    mockListarPages(ids, 500);
    const onSuccess = vi.fn();
    const user = userEvent.setup();
    renderModal({ onSuccess });

    await setMarkupObjetivo(user, '-3');
    await user.click(screen.getByRole('button', { name: /Aplicar a 18 productos/i }));

    expect(await screen.findByText('MarkUp Negativo')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Guardar de todas formas/i })).toBeInTheDocument();
    expect(screen.getByText(/costo \+ comisiones/i)).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
    expect(confirmSpy).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: /Guardar de todas formas/i }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    const markupCalls = api.post.mock.calls.filter(([url]) =>
      url.includes('aplicar-markup-masivo'),
    );
    expect(markupCalls).toHaveLength(1);
    expect(markupCalls[0][1].markup_objetivo).toBe(-3);
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it('Volver on negative pane aborts write and keeps the value', async () => {
    mockListarPages(makeIds(18), 500);
    const user = userEvent.setup();
    renderModal();

    await setMarkupObjetivo(user, '-3');
    await user.click(screen.getByRole('button', { name: /Aplicar a 18 productos/i }));
    expect(await screen.findByText('MarkUp Negativo')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /^Volver$/i }));
    expect(screen.queryByText('MarkUp Negativo')).not.toBeInTheDocument();
    expect(screen.getByRole('textbox')).toHaveValue('-3');
    expect(screen.getByRole('button', { name: /Aplicar a 18 productos/i })).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it('stacks negative pane then >50 before writes', async () => {
    const ids = makeIds(51);
    mockListarPages(ids, 500);
    const onSuccess = vi.fn();
    const user = userEvent.setup();
    renderModal({ totalProductos: 51, onSuccess });

    await setMarkupObjetivo(user, '-3');
    await user.click(screen.getByRole('button', { name: /Aplicar a 51 productos/i }));

    expect(await screen.findByText('MarkUp Negativo')).toBeInTheDocument();
    expect(screen.queryByText(/Confirmar acciones masivas/i)).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: /Guardar de todas formas/i }));
    expect(await screen.findByText(/Confirmar acciones masivas/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Confirmar$/i })).toBeInTheDocument();
    expect(screen.queryByText('MarkUp Negativo')).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: /^Confirmar$/i }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    const markupCalls = api.post.mock.calls.filter(([url]) =>
      url.includes('aplicar-markup-masivo'),
    );
    expect(markupCalls).toHaveLength(1);
    expect(markupCalls[0][1].markup_objetivo).toBe(-3);
    expect(markupCalls[0][1].item_ids).toHaveLength(51);
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it('stacks zero pane then >50 before writes', async () => {
    const ids = makeIds(51);
    mockListarPages(ids, 500);
    const onSuccess = vi.fn();
    const user = userEvent.setup();
    renderModal({ totalProductos: 51, onSuccess });

    await setMarkupObjetivo(user, '0');
    await user.click(screen.getByRole('button', { name: /Aplicar a 51 productos/i }));

    expect(await screen.findByText('MarkUp Negativo')).toBeInTheDocument();
    expect(screen.queryByText(/Confirmar acciones masivas/i)).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: /Guardar de todas formas/i }));
    expect(await screen.findByText(/Confirmar acciones masivas/i)).toBeInTheDocument();
    expect(screen.queryByText('MarkUp Negativo')).not.toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: /^Confirmar$/i }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    const markupCalls = api.post.mock.calls.filter(([url]) =>
      url.includes('aplicar-markup-masivo'),
    );
    expect(markupCalls).toHaveLength(1);
    expect(markupCalls[0][1].markup_objetivo).toBe(0);
    expect(confirmSpy).not.toHaveBeenCalled();
  });
});
