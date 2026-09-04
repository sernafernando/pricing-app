/**
 * Spec coverage for productos-acciones-masivas-scope (WU1 / PR1):
 * - Modal count from totalProductos (not page buffer)
 * - Resolve + apply full filtered set (200, not page 50)
 * - Unfiltered N → N
 * - confirm when >50; skip when ≤50
 * - fail-closed empty/mismatch (no catalog widen)
 * - chunks ≤ 100
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AplicarMarkupMasivoModal from './AplicarMarkupMasivoModal';
import api, { productosAPI } from '../services/api';
import {
  resolveFilteredItemIds,
  chunkIds,
  buildListarParamsFromFiltros,
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

const FILTROS_18 = {
  marcas: ['ACME'],
  con_stock: true,
  con_precio: true,
};

describe('buildListarParamsFromFiltros', () => {
  it('maps filtrosActivos to listar keys (tn_*, joined marcas)', () => {
    const params = buildListarParamsFromFiltros({
      marcas: ['A', 'B'],
      filtroTiendaNube: 'con_descuento',
      filtroPxq: 'con_pxq',
      promo_tipos: 'SMART',
      promo_estado: 'aplicada',
    });
    expect(params.marcas).toBe('A,B');
    expect(params.tn_con_descuento).toBe(true);
    expect(params.con_pxq).toBe(true);
    expect(params.promo_tipos).toBe('SMART');
    expect(params.promo_estado).toBe('aplicada');
  });
});

describe('resolveFilteredItemIds', () => {
  beforeEach(() => vi.clearAllMocks());

  it('pages until all filtered IDs are collected', async () => {
    const ids = makeIds(200);
    mockListarPages(ids, 100);
    const resolved = await resolveFilteredItemIds({
      listar: productosAPI.listar,
      filtrosActivos: FILTROS_18,
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
    });
  });

  it('fail-closed on empty resolve when filters are active', async () => {
    productosAPI.listar.mockResolvedValue({ data: { total: 0, productos: [] } });
    await expect(
      resolveFilteredItemIds({
        listar: productosAPI.listar,
        filtrosActivos: FILTROS_18,
        totalProductos: 18,
      }),
    ).rejects.toMatchObject({ code: 'empty' });
  });

  it('fail-closed on mismatch vs totalProductos when filters are active', async () => {
    mockListarPages(makeIds(10), 500);
    await expect(
      resolveFilteredItemIds({
        listar: productosAPI.listar,
        filtrosActivos: FILTROS_18,
        totalProductos: 18,
      }),
    ).rejects.toMatchObject({ code: 'mismatch' });
  });

  it('does not fail-closed empty when unfiltered (no page-buffer fallback needed)', async () => {
    productosAPI.listar.mockResolvedValue({ data: { total: 0, productos: [] } });
    const resolved = await resolveFilteredItemIds({
      listar: productosAPI.listar,
      filtrosActivos: {},
      totalProductos: 0,
    });
    expect(resolved).toEqual([]);
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
        filtrosActivos={FILTROS_18}
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
        filtrosActivos={FILTROS_18}
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
        filtrosActivos={{}}
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
        filtrosActivos={FILTROS_18}
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
        filtrosActivos={FILTROS_18}
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
        filtrosActivos={FILTROS_18}
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
        filtrosActivos={FILTROS_18}
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
