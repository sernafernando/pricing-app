import { describe, it, expect, vi } from 'vitest';
import { ANULAR_MASIVO_MAX, resolverIdsFiltrados } from './sellInAnularMasivo';

/** A paginated list API over `ids`, newest first, answering `total` (the list's own count) on every page. */
const listarDe = (ids, total = ids.length) =>
  vi.fn(async ({ page, page_size: size }) => ({ data: { items: ids.slice((page - 1) * size, page * size).map((id) => ({ id })), total } }));

describe('resolverIdsFiltrados — "todo lo filtrado" is fail-closed', () => {
  it('pages through the filtered list with the same filters and returns every id', async () => {
    const ids = Array.from({ length: 450 }, (_, i) => 1000 - i);
    const listar = listarDe(ids);

    await expect(resolverIdsFiltrados(listar, { marcas: 'TP-LINK' }, { total: 450, filtrosActivos: true })).resolves.toEqual(ids);
    expect(listar).toHaveBeenCalledTimes(3);
    expect(listar).toHaveBeenCalledWith({ marcas: 'TP-LINK', page: 1, page_size: 200 });
  });

  it('refuses when the ids it got differ from the list total', async () => {
    const listar = listarDe([3, 2, 1], 4);

    await expect(resolverIdsFiltrados(listar, {}, { total: 4, filtrosActivos: false })).rejects.toThrow(
      'La lista cambió mientras se seleccionaba (3 de 4). Volvé a intentarlo.',
    );
  });

  it('refuses when the total moved since the page was shown', async () => {
    await expect(resolverIdsFiltrados(listarDe([2, 1]), {}, { total: 3, filtrosActivos: false })).rejects.toThrow(
      'La lista cambió mientras se seleccionaba (2 de 3). Volvé a intentarlo.',
    );
  });

  it('refuses an empty answer with filters active', async () => {
    await expect(resolverIdsFiltrados(listarDe([]), { q: 'x' }, { total: 0, filtrosActivos: true })).rejects.toThrow(
      'No se pudo resolver lo filtrado: la lista vino vacía.',
    );
  });

  it('refuses more than the bulk limit before asking', async () => {
    const listar = listarDe([]);

    await expect(resolverIdsFiltrados(listar, {}, { total: ANULAR_MASIVO_MAX + 1, filtrosActivos: false })).rejects.toThrow(
      `Son ${ANULAR_MASIVO_MAX + 1}: se pueden anular hasta ${ANULAR_MASIVO_MAX} por vez. Filtrá más.`,
    );
    expect(listar).not.toHaveBeenCalled();
  });
});
