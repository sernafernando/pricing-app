/**
 * Bulk pause / activate of Publicaciones ML (publicaciones-ml-producto-propio T5): over every publication the
 * filters show that can take the status (`GET /ml-publications/view/status-item-ids`), after a confirmation that
 * says how many, written in batches (`POST /ml-publications/items/status-bulk`) with progress and a summary.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import BulkStatusActions, { BATCH_SIZE } from './BulkStatusActions';
import { publicacionesMlAPI } from '../../services/api';

vi.mock('../../services/api', () => ({
  default: { post: vi.fn(), get: vi.fn() },
  publicacionesMlAPI: { statusItemIds: vi.fn(), statusItemIdsChecked: vi.fn(), statusBulk: vi.fn() },
}));

let granted = new Set();
vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: (permiso) => granted.has(permiso) }),
}));

const FILTERS = {
  q: '', familia: '', evento_desde: '', markup_neg: '', markup_min: '', markup_max: '',
  estado: ['active'], estado_excluir: [], tiendas: [], marcas: [], categorias: [], subcategorias: [], pms: [],
  tipo: [], vinculo: [], stock: [], evento: [], rebate: '', oferta: '', webtransf: '', tiendanube: '', outofcards: '',
  vista: '', pagina: 1, limite: 50,
};

const REGION = 'Pausar o activar publicaciones';
const mlas = (n) => Array.from({ length: n }, (_, i) => `MLA${i + 1}`);
const resolved = (body) => publicacionesMlAPI.statusItemIds.mockResolvedValue({ data: body });
const httpError = (status, data) => Object.assign(new Error(`HTTP ${status}`), { response: { status, data } });

function renderBulk(onDone = vi.fn(), checked = undefined) {
  render(<BulkStatusActions filters={FILTERS} canSeeMargin={false} onDone={onDone} checked={checked} />);
  return onDone;
}

async function choose(user, label) {
  await user.click(screen.getByRole('button', { name: 'Pausar / activar' }));
  await user.click(screen.getByRole('menuitem', { name: label }));
}

beforeEach(() => {
  vi.clearAllMocks();
  granted = new Set(['ml_publicaciones.pausar']);
  publicacionesMlAPI.statusBulk.mockImplementation((body) =>
    Promise.resolve({ data: { results: body.item_ids.map((id) => ({ item_id: id, status: 'submitted', message: null })) } }),
  );
});

describe('who sees it', () => {
  it('nothing without ml_publicaciones.pausar', () => {
    granted = new Set();
    renderBulk();
    expect(screen.queryByRole('button', { name: 'Pausar / activar' })).not.toBeInTheDocument();
  });
});

describe('the confirmation', () => {
  it('resolves the filtered set for the chosen status and says how many, and how many are left alone', async () => {
    resolved({ item_ids: mlas(3), count: 3, no_aplican: 2 });
    const user = userEvent.setup();
    renderBulk();
    await choose(user, 'Pausar las del filtro');
    const dialog = await screen.findByRole('region', { name: REGION });
    expect(publicacionesMlAPI.statusItemIds).toHaveBeenCalledWith({ estado: 'active', target: 'paused' });
    expect(dialog).toHaveTextContent('Se van a pausar 3 publicaciones en Mercado Libre.');
    expect(dialog).toHaveTextContent('2 publicaciones del filtro no se tocan (otro estado).');
    expect(publicacionesMlAPI.statusBulk).not.toHaveBeenCalled();
  });

  it('Cancelar writes nothing', async () => {
    resolved({ item_ids: mlas(3), count: 3, no_aplican: 0 });
    const user = userEvent.setup();
    renderBulk();
    await choose(user, 'Activar las del filtro');
    await user.click(await screen.findByRole('button', { name: 'Cancelar' }));
    expect(publicacionesMlAPI.statusBulk).not.toHaveBeenCalled();
    expect(screen.queryByRole('region', { name: REGION })).not.toBeInTheDocument();
  });

  it('cancelling while the set resolves keeps it closed when the answer arrives late', async () => {
    let answer;
    publicacionesMlAPI.statusItemIds.mockReturnValue(new Promise((resolve) => (answer = resolve)));
    const user = userEvent.setup();
    renderBulk();
    await choose(user, 'Pausar las del filtro');
    await user.click(await screen.findByRole('button', { name: 'Cancelar' }));
    answer({ data: { item_ids: mlas(3), count: 3, no_aplican: 0 } });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByRole('region', { name: REGION })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Confirmar' })).not.toBeInTheDocument();
  });

  it('an empty set offers nothing to confirm', async () => {
    resolved({ item_ids: [], count: 0, no_aplican: 4 });
    const user = userEvent.setup();
    renderBulk();
    await choose(user, 'Pausar las del filtro');
    const dialog = await screen.findByRole('region', { name: REGION });
    expect(dialog).toHaveTextContent('Ninguna publicación del filtro se puede pausar.');
    expect(within(dialog).queryByRole('button', { name: 'Confirmar' })).not.toBeInTheDocument();
  });

  it('a set over the cap shows the server reason and offers nothing to confirm', async () => {
    publicacionesMlAPI.statusItemIds.mockRejectedValue(
      httpError(422, { error: { message: 'El filtro selecciona 900 publicaciones; una acción masiva admite hasta 500. Acotá el filtro.' } }),
    );
    const user = userEvent.setup();
    renderBulk();
    await choose(user, 'Pausar las del filtro');
    const dialog = await screen.findByRole('region', { name: REGION });
    expect(dialog).toHaveTextContent('El filtro selecciona 900 publicaciones');
    expect(within(dialog).queryByRole('button', { name: 'Confirmar' })).not.toBeInTheDocument();
  });
});

describe('the run', () => {
  it('writes the set in batches, in order, then summarizes and reloads the list', async () => {
    const ids = mlas(BATCH_SIZE + 5);
    resolved({ item_ids: ids, count: ids.length, no_aplican: 0 });
    publicacionesMlAPI.statusBulk.mockImplementation((body) =>
      Promise.resolve({
        data: {
          results: body.item_ids.map((id) =>
            id === 'MLA2'
              ? { item_id: id, status: 'rejected', message: 'item has no stock' }
              : { item_id: id, status: 'submitted', message: null },
          ),
        },
      }),
    );
    const user = userEvent.setup();
    const onDone = renderBulk();
    await choose(user, 'Pausar las del filtro');
    await user.click(await screen.findByRole('button', { name: 'Confirmar' }));
    await waitFor(() => expect(screen.getByRole('region', { name: REGION })).toHaveTextContent(`${ids.length - 1} pausadas.`));
    expect(publicacionesMlAPI.statusBulk.mock.calls.map(([body]) => body)).toEqual([
      { status: 'paused', item_ids: ids.slice(0, BATCH_SIZE) },
      { status: 'paused', item_ids: ids.slice(BATCH_SIZE) },
    ]);
    const dialog = screen.getByRole('region', { name: REGION });
    expect(dialog).toHaveTextContent('1 con error:');
    expect(dialog).toHaveTextContent('MLA2: item has no stock');
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it('a batch that fails stops the run and says how far it got', async () => {
    const ids = mlas(BATCH_SIZE + 5);
    resolved({ item_ids: ids, count: ids.length, no_aplican: 0 });
    publicacionesMlAPI.statusBulk
      .mockImplementationOnce((body) =>
        Promise.resolve({ data: { results: body.item_ids.map((id) => ({ item_id: id, status: 'submitted', message: null })) } }),
      )
      .mockRejectedValueOnce(new Error('Network Error'));
    const user = userEvent.setup();
    const onDone = renderBulk();
    await choose(user, 'Pausar las del filtro');
    await user.click(await screen.findByRole('button', { name: 'Confirmar' }));
    await waitFor(() =>
      expect(screen.getByRole('region', { name: REGION })).toHaveTextContent(`Se cortó después de ${BATCH_SIZE} de ${ids.length}.`),
    );
    expect(publicacionesMlAPI.statusBulk).toHaveBeenCalledTimes(2);
    expect(onDone).toHaveBeenCalledTimes(1); // what was written is re-read
  });

  it('ambiguous and unchanged outcomes are counted apart from errors', async () => {
    resolved({ item_ids: mlas(3), count: 3, no_aplican: 0 });
    publicacionesMlAPI.statusBulk.mockResolvedValue({
      data: {
        results: [
          { item_id: 'MLA1', status: 'submitted', message: null },
          { item_id: 'MLA2', status: 'unchanged', message: null },
          { item_id: 'MLA3', status: 'ambiguous', message: 'No se sabe si Mercado Libre aplicó el cambio: se vuelve a consultar.' },
        ],
      },
    });
    const user = userEvent.setup();
    renderBulk();
    await choose(user, 'Activar las del filtro');
    await user.click(await screen.findByRole('button', { name: 'Confirmar' }));
    const dialog = await screen.findByRole('region', { name: REGION });
    await waitFor(() => expect(dialog).toHaveTextContent('1 activadas.'));
    expect(dialog).toHaveTextContent('1 ya estaban activas.');
    expect(dialog).toHaveTextContent('1 sin confirmar: se vuelven a consultar.');
    expect(dialog).not.toHaveTextContent('con error');
  });
});

describe('over the checked rows (seleccion-por-publicacion S2)', () => {
  const resolvedChecked = (body) => publicacionesMlAPI.statusItemIdsChecked.mockResolvedValue({ data: body });
  const menu = async (user) => {
    await user.click(screen.getByRole('button', { name: 'Pausar / activar' }));
    return screen.getAllByRole('menuitem').map((item) => item.textContent);
  };

  it('one checked publication: the menu names it, and only that MLA is resolved and written, never the filter', async () => {
    resolvedChecked({ item_ids: ['MLA2'], count: 1, no_aplican: 0 });
    const user = userEvent.setup();
    const onDone = renderBulk(vi.fn(), { itemIds: ['MLA2'], productIds: [] });
    expect(await menu(user)).toEqual(['Pausar la marcada', 'Activar la marcada']);
    await user.click(screen.getByRole('menuitem', { name: 'Pausar la marcada' }));
    const dialog = await screen.findByRole('region', { name: REGION });
    expect(publicacionesMlAPI.statusItemIdsChecked).toHaveBeenCalledWith({ target: 'paused', item_ids: ['MLA2'], producto_ids: [] });
    expect(publicacionesMlAPI.statusItemIds).not.toHaveBeenCalled();
    expect(dialog).toHaveTextContent('Se van a pausar 1 publicación en Mercado Libre.');
    await user.click(within(dialog).getByRole('button', { name: 'Confirmar' }));
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(publicacionesMlAPI.statusBulk.mock.calls).toEqual([[{ status: 'paused', item_ids: ['MLA2'] }]]);
  });

  it('several checked publications, and product rows, are named by count and sent as they are', async () => {
    resolvedChecked({ item_ids: ['MLA2', 'MLA3', 'MLA7'], count: 3, no_aplican: 2 });
    const user = userEvent.setup();
    renderBulk(vi.fn(), { itemIds: ['MLA2', 'MLA3'], productIds: [77] });
    expect(await menu(user)).toEqual(['Pausar las de 3 filas marcadas', 'Activar las de 3 filas marcadas']);
    await user.click(screen.getByRole('menuitem', { name: 'Activar las de 3 filas marcadas' }));
    const dialog = await screen.findByRole('region', { name: REGION });
    expect(publicacionesMlAPI.statusItemIdsChecked).toHaveBeenCalledWith({ target: 'active', item_ids: ['MLA2', 'MLA3'], producto_ids: [77] });
    expect(dialog).toHaveTextContent('Se van a activar 3 publicaciones en Mercado Libre.');
    expect(dialog).toHaveTextContent('2 publicaciones marcadas no se tocan (otro estado).');
  });

  it('two checked publications read "las 2 marcadas"', async () => {
    const user = userEvent.setup();
    renderBulk(vi.fn(), { itemIds: ['MLA2', 'MLA3'], productIds: [] });
    expect(await menu(user)).toEqual(['Pausar las 2 marcadas', 'Activar las 2 marcadas']);
  });

  it('nothing checked keeps acting on the filter', async () => {
    const user = userEvent.setup();
    renderBulk(vi.fn(), { itemIds: [], productIds: [] });
    expect(await menu(user)).toEqual(['Pausar las del filtro', 'Activar las del filtro']);
  });

  it('fails closed: when the checked set cannot be resolved nothing is written', async () => {
    publicacionesMlAPI.statusItemIdsChecked.mockRejectedValue(httpError(500, {}));
    const user = userEvent.setup();
    renderBulk(vi.fn(), { itemIds: ['MLA2'], productIds: [] });
    await menu(user);
    await user.click(screen.getByRole('menuitem', { name: 'Pausar la marcada' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron resolver las publicaciones marcadas.');
    expect(screen.queryByRole('button', { name: 'Confirmar' })).not.toBeInTheDocument();
    expect(publicacionesMlAPI.statusBulk).not.toHaveBeenCalled();
  });

  it('a slow checked set asks to check fewer rows, not to narrow the filters', async () => {
    publicacionesMlAPI.statusItemIdsChecked.mockRejectedValue(httpError(503, {}));
    const user = userEvent.setup();
    renderBulk(vi.fn(), { itemIds: ['MLA2'], productIds: [] });
    await menu(user);
    await user.click(screen.getByRole('menuitem', { name: 'Pausar la marcada' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('La consulta tardó demasiado: marcá menos filas o reintentá.');
  });

  it('nothing checked can take the status: nothing to confirm', async () => {
    resolvedChecked({ item_ids: [], count: 0, no_aplican: 1 });
    const user = userEvent.setup();
    renderBulk(vi.fn(), { itemIds: ['MLA2'], productIds: [] });
    await menu(user);
    await user.click(screen.getByRole('menuitem', { name: 'Pausar la marcada' }));
    const dialog = await screen.findByRole('region', { name: REGION });
    expect(dialog).toHaveTextContent('Ninguna publicación marcada se puede pausar.');
    expect(within(dialog).queryByRole('button', { name: 'Confirmar' })).not.toBeInTheDocument();
  });
});
