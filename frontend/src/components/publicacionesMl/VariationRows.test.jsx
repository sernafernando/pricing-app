/**
 * VariationRows (publicaciones-ml-vista P11b.T3): the sub-rows of an expanded
 * publication. They fetch the variations when they mount (so a collapsed row
 * costs nothing) and show loading, error and empty states honestly.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import VariationRows from './VariationRows';
import { buildColumns } from './columns';
import { publicacionesMlAPI } from '../../services/api';
import { VARIATIONS_RESPONSE, VARIATION_ITEM, makeVariation } from '../../test/visual/publicacionesMlFixtures';

vi.mock('../../services/api', () => ({
  default: { get: vi.fn(), interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } } },
  publicacionesMlAPI: { variations: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

const httpError = (status) => Object.assign(new Error(`HTTP ${status}`), { response: { status } });

const mount = (canSeeMargin = true, item = VARIATION_ITEM) => {
  const columns = buildColumns({ eventsEnabled: false, canSeeMargin });
  return render(
    <table>
      <tbody>
        <VariationRows item={item} columns={columns} canSeeMargin={canSeeMargin} />
      </tbody>
    </table>,
  );
};

const rowOf = (text) => screen.getByText(text).closest('tr');

beforeEach(() => {
  publicacionesMlAPI.variations.mockReset();
  publicacionesMlAPI.variations.mockResolvedValue({ data: VARIATIONS_RESPONSE });
});

describe('VariationRows', () => {
  it('fetches the variations of the publication when it mounts, and says so while loading', async () => {
    mount();
    expect(publicacionesMlAPI.variations).toHaveBeenCalledWith('MLA1100000005');
    expect(screen.getByRole('status')).toHaveTextContent('Cargando variaciones');
    await screen.findByText('Router Archer AX55 negro');
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('shows SKU, EAN, product, cost and markup of each variation', async () => {
    mount();
    await screen.findByText('Router Archer AX55 negro');
    const first = rowOf('Router Archer AX55 negro');
    expect(within(first).getByText(/ARCHER-AX55/)).toBeInTheDocument();
    expect(within(first).getByText(/7501234567890/)).toBeInTheDocument();
    expect(within(first).getByText('41.000,50')).toBeInTheDocument();
    expect(within(first).getByText('12,5%')).toBeInTheDocument();
    expect(within(first).getByText('14')).toBeInTheDocument();
  });

  it('highlights a negative markup, and only that one', async () => {
    mount();
    await screen.findByText('Router Archer AX55 negro');
    expect(rowOf('Router Archer AX55 blanco')).toHaveAttribute('data-negative');
    expect(within(rowOf('Router Archer AX55 blanco')).getByText('-4,2%')).toHaveAttribute('data-negative');
    expect(rowOf('Router Archer AX55 negro')).not.toHaveAttribute('data-negative');
  });

  it('an unlinked variation says so and shows "—" with the reason, never a made-up 0', async () => {
    mount();
    await screen.findByText('Router Archer AX55 negro');
    const unlinked = rowOf('Variación 9003');
    expect(within(unlinked).getByText('Sin producto vinculado')).toBeInTheDocument();
    expect(within(unlinked).getAllByText('—').some((el) => el.title === 'La publicación no está vinculada a un producto')).toBe(true);
  });

  it('without ver_ganancia shows no cost and no markup', async () => {
    const variations = structuredClone(VARIATIONS_RESPONSE.variations);
    for (const variation of variations) {
      delete variation.cost;
      delete variation.markup;
    }
    publicacionesMlAPI.variations.mockResolvedValue({ data: { ...VARIATIONS_RESPONSE, variations } });
    mount(false);
    await screen.findByText('Router Archer AX55 negro');
    expect(screen.queryByText('41.000,50')).not.toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it('even if the payload carried them, cost and markup are not rendered without ver_ganancia', async () => {
    mount(false);
    await screen.findByText('Router Archer AX55 negro');
    expect(screen.queryByText('41.000,50')).not.toBeInTheDocument();
    expect(screen.queryByText('12,5%')).not.toBeInTheDocument();
  });

  it('empty: says the publication has no variations', async () => {
    publicacionesMlAPI.variations.mockResolvedValue({ data: { item_id: 'MLA1100000005', variations: [] } });
    mount();
    expect(await screen.findByText('Esta publicación no tiene variaciones')).toBeInTheDocument();
  });

  it('error: says what failed and retries on demand', async () => {
    publicacionesMlAPI.variations.mockRejectedValueOnce(httpError(500));
    mount();
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron cargar las variaciones');
    await userEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
    expect(await screen.findByText('Router Archer AX55 negro')).toBeInTheDocument();
    expect(publicacionesMlAPI.variations).toHaveBeenCalledTimes(2);
  });

  it.each([
    [404, 'La publicación ya no existe'],
    [403, 'No tenés permiso para ver las variaciones'],
    [503, 'La consulta tardó demasiado'],
  ])('error %s has its own message', async (status, text) => {
    publicacionesMlAPI.variations.mockRejectedValue(httpError(status));
    mount();
    expect(await screen.findByRole('alert')).toHaveTextContent(text);
  });

  it('spans every visible column in its state rows', async () => {
    publicacionesMlAPI.variations.mockResolvedValue({ data: { item_id: 'x', variations: [] } });
    mount();
    const cell = (await screen.findByText('Esta publicación no tiene variaciones')).closest('td');
    expect(cell).toHaveAttribute('colspan', String(buildColumns({ eventsEnabled: false, canSeeMargin: true }).length));
  });

  it('drops the answer if it unmounts first (no update after collapse)', async () => {
    let resolve;
    publicacionesMlAPI.variations.mockReturnValue(new Promise((r) => (resolve = r)));
    const { unmount } = mount();
    unmount();
    resolve({ data: VARIATIONS_RESPONSE });
    await waitFor(() => expect(publicacionesMlAPI.variations).toHaveBeenCalledTimes(1));
  });

  it('a variation without any datum still renders a row', async () => {
    publicacionesMlAPI.variations.mockResolvedValue({ data: { item_id: 'x', variations: [makeVariation({ variation_id: 7 })] } });
    mount();
    expect(await screen.findByText('Variación 7')).toBeInTheDocument();
  });
});
