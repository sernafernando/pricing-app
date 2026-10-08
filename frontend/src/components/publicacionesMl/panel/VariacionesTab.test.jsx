/**
 * Variaciones tab (publicaciones-ml-vista P13a.T3): the variations of one
 * publication, from the same endpoint the table's sub-rows use (P6c).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import VariacionesTab from './VariacionesTab';
import { readDetail } from './detailModel';
import { publicacionesMlAPI } from '../../../services/api';
import { DETAIL_RESPONSE, VARIATIONS_RESPONSE } from '../../../test/visual/publicacionesMlFixtures';

vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  publicacionesMlAPI: { variations: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

const httpError = (status) => Object.assign(new Error(`HTTP ${status}`), { response: { status } });
const renderTab = ({ canSeeMargin = false } = {}) => {
  const detail = readDetail(DETAIL_RESPONSE, { canSeeMargin });
  return render(<VariacionesTab detail={detail} itemId="MLA1100000005" canSeeMargin={canSeeMargin} />);
};
const card = async (id) => (await screen.findByText(`Variación ${id}`)).closest('li');

beforeEach(() => {
  publicacionesMlAPI.variations.mockReset();
  publicacionesMlAPI.variations.mockResolvedValue({ data: VARIATIONS_RESPONSE });
});

describe('the variations', () => {
  it('asks for the variations of the selected publication and lists one entry each (S53.1)', async () => {
    renderTab();
    await screen.findByText('Variación 9001');
    expect(publicacionesMlAPI.variations).toHaveBeenCalledWith('MLA1100000005');
    expect(screen.getAllByRole('listitem')).toHaveLength(3);
  });

  it('shows the attributes, the SKU, the product and the stock of each', async () => {
    renderTab();
    const first = await card(9001);
    expect(within(first).getByText('Color: Negro')).toBeInTheDocument();
    expect(within(first).getByText('SKU ARCHER-AX55')).toBeInTheDocument();
    expect(within(first).getByText('Router Archer AX55 negro')).toBeInTheDocument();
    expect(within(first).getByText('Disponible').nextElementSibling).toHaveTextContent('14');
    expect(within(first).getByText('Vendidas').nextElementSibling).toHaveTextContent('120');
  });

  it('says when the product is the publication\'s and not the variation\'s own', async () => {
    renderTab();
    expect(within(await card(9002)).getByText('producto de la publicación')).toBeInTheDocument();
    expect(within(await card(9001)).queryByText('producto de la publicación')).not.toBeInTheDocument();
  });

  it('a variation without product says so, and its missing figures are "—"', async () => {
    renderTab();
    const third = await card(9003);
    expect(within(third).getByText('Sin producto vinculado')).toBeInTheDocument();
    expect(within(third).getByText('Vendidas').nextElementSibling).toHaveTextContent('0');
  });

  it('an unknown quantity is "—", not 0', async () => {
    publicacionesMlAPI.variations.mockResolvedValue({
      data: { ...VARIATIONS_RESPONSE, variations: [{ ...VARIATIONS_RESPONSE.variations[0], available_quantity: null, sold_quantity: null }] },
    });
    renderTab();
    const only = await card(9001);
    expect(within(only).getByText('Disponible').nextElementSibling).toHaveTextContent('—');
    expect(within(only).getByText('Vendidas').nextElementSibling).toHaveTextContent('—');
  });
});

describe('cost and markup (ver_ganancia only)', () => {
  it('show the cost and the markup of each variation, the negative one flagged', async () => {
    renderTab({ canSeeMargin: true });
    const first = await card(9001);
    expect(within(first).getByText('Costo').nextElementSibling).toHaveTextContent('41.000,50');
    expect(within(first).getByText('Markup').nextElementSibling).toHaveTextContent('12,5%');
    const second = await card(9002);
    expect(within(second).getByText('Costo USD').nextElementSibling).toHaveTextContent('520,00');
    expect(second).toHaveAttribute('data-negative');
    expect(first).not.toHaveAttribute('data-negative');
  });

  it('a variation without cost has "—" and the reason on the markup', async () => {
    renderTab({ canSeeMargin: true });
    const third = await card(9003);
    expect(within(third).getByText('Costo').nextElementSibling).toHaveTextContent('—');
    expect(within(third).getByText('Markup').nextElementSibling.querySelector('[title]')).toHaveAttribute(
      'title',
      expect.stringContaining('no está vinculada'),
    );
  });

  it('without the permission there is neither cost nor markup, even if the payload had them', async () => {
    renderTab({ canSeeMargin: false });
    const first = await card(9001);
    expect(within(first).queryByText('Costo')).not.toBeInTheDocument();
    expect(within(first).queryByText('Markup')).not.toBeInTheDocument();
  });
});

describe('states', () => {
  it('shows loading while it asks', () => {
    publicacionesMlAPI.variations.mockReturnValue(new Promise(() => {}));
    renderTab();
    expect(screen.getByRole('status')).toHaveTextContent('Cargando variaciones');
  });

  it('a publication without variations says so (S52.1)', async () => {
    publicacionesMlAPI.variations.mockResolvedValue({ data: { ...VARIATIONS_RESPONSE, variations: [] } });
    renderTab();
    expect(await screen.findByText('Esta publicación no tiene variaciones')).toBeInTheDocument();
  });

  it('a failure can be retried', async () => {
    publicacionesMlAPI.variations.mockRejectedValueOnce(httpError(500));
    renderTab();
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron cargar las variaciones');
    await userEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
    expect(await screen.findByText('Variación 9001')).toBeInTheDocument();
    expect(publicacionesMlAPI.variations).toHaveBeenCalledTimes(2);
  });
});
