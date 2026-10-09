/**
 * Historial tab (publicaciones-ml-vista P13b.T2, S58.x): what changed in the
 * publication, from `ml_change_log`. Business fields first; the technical ones
 * only behind "Ver todo".
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import HistorialTab from './HistorialTab';
import { publicacionesMlAPI } from '../../../services/api';
import { HISTORY_ENTRIES, HISTORY_RESPONSE } from '../../../test/visual/publicacionesMlFixtures';

vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  publicacionesMlAPI: { history: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

const httpError = (status) => Object.assign(new Error(`HTTP ${status}`), { response: { status } });
const renderTab = () => render(<HistorialTab itemId="MLA1100000001" />);
const verTodo = () => screen.getByRole('button', { name: 'Ver todo' });

beforeEach(() => {
  publicacionesMlAPI.history.mockReset();
  publicacionesMlAPI.history.mockResolvedValue({ data: HISTORY_RESPONSE });
});

describe('the business fields', () => {
  it('asks for the history of the selected publication', async () => {
    renderTab();
    await screen.findByText('Precio');
    expect(publicacionesMlAPI.history).toHaveBeenCalledWith('MLA1100000001', {});
  });

  it('shows one line per changed field, with the previous and the new value (S58.3)', async () => {
    renderTab();
    const entry = (await screen.findByText('Precio')).closest('li');
    const price = within(entry).getByText('Precio').closest('[data-line]');
    expect(price).toHaveTextContent(/55\.882/);
    expect(price).toHaveTextContent(/56\.382/);
    const status = within(entry).getByText('Estado').closest('[data-line]');
    expect(status).toHaveTextContent('active');
    expect(status).toHaveTextContent('paused');
    expect(within(entry).getAllByText(/→/)).toHaveLength(2);
  });

  it('says which resource changed and when', async () => {
    renderTab();
    const stock = (await screen.findByText('Stock por ubicación')).closest('li');
    expect(within(stock).getByText('Stock')).toBeInTheDocument();
    expect(within(stock).getByText(/\d{2}\/\d{2}\/\d{4}/)).toBeInTheDocument();
    expect(stock).toHaveTextContent('24');
    expect(stock).toHaveTextContent('20');
  });

  it('shows "—" on the side of a field that did not exist', async () => {
    publicacionesMlAPI.history.mockResolvedValue({
      data: {
        entries: [{ ...HISTORY_ENTRIES[1], business: [{ path: 'title', label_key: 'title', label: 'Título', old: null, new: 'Router nuevo' }] }],
        next_cursor: null,
      },
    });
    renderTab();
    const line = (await screen.findByText('Título')).closest('[data-line]');
    expect(line).toHaveTextContent('—');
    expect(line).toHaveTextContent('Router nuevo');
  });
});

describe('the technical fields (S58.1)', () => {
  it('are hidden until "Ver todo", and the price is visible from the start', async () => {
    renderTab();
    await screen.findByText('Precio');
    expect(screen.queryByText('last_updated')).not.toBeInTheDocument();
    expect(screen.queryByText('units_30d')).not.toBeInTheDocument();
    expect(verTodo()).toHaveAttribute('aria-pressed', 'false');
  });

  it('appear under the business ones with "Ver todo", and go away again', async () => {
    renderTab();
    await screen.findByText('Precio');

    await userEvent.click(verTodo());

    const mixed = screen.getByText('last_updated').closest('li');
    expect(within(mixed).getByText('Precio')).toBeInTheDocument();
    expect(verTodo()).toHaveAttribute('aria-pressed', 'true');
    // An entry with only technical fields exists now.
    expect(screen.getByText('units_30d').closest('li')).toHaveTextContent('Reposición');

    await userEvent.click(verTodo());
    expect(screen.queryByText('last_updated')).not.toBeInTheDocument();
  });

  it('collapse again when the selection moves to another publication, whatever the panel does around the tab', async () => {
    const { rerender } = renderTab();
    await screen.findByText('Precio');
    await userEvent.click(verTodo());
    expect(screen.getByText('last_updated')).toBeInTheDocument();

    rerender(<HistorialTab itemId="MLA1100000002" />);

    await screen.findByText('Precio');
    expect(publicacionesMlAPI.history).toHaveBeenLastCalledWith('MLA1100000002', {});
    expect(verTodo()).toHaveAttribute('aria-pressed', 'false');
    expect(screen.queryByText('last_updated')).not.toBeInTheDocument();
  });

  it('an entry with only technical fields stays out of the first view', async () => {
    renderTab();
    await screen.findByText('Precio');
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
    await userEvent.click(verTodo());
    expect(screen.getAllByRole('listitem')).toHaveLength(3);
  });

  it('says so when the page holds only technical changes', async () => {
    publicacionesMlAPI.history.mockResolvedValue({ data: { entries: [HISTORY_ENTRIES[2]], next_cursor: null } });
    renderTab();
    expect(await screen.findByText(/solo cambios técnicos/i)).toBeInTheDocument();
    await userEvent.click(verTodo());
    expect(screen.getByText('units_30d')).toBeInTheDocument();
  });
});

describe('an unknown resource', () => {
  it('gets a generic label, never its code', async () => {
    publicacionesMlAPI.history.mockResolvedValue({ data: { entries: [{ ...HISTORY_ENTRIES[1], resource_type: 'brand_new_resource' }], next_cursor: null } });
    renderTab();
    expect(await screen.findByText('Otro recurso')).toBeInTheDocument();
    expect(screen.queryByText('brand_new_resource')).not.toBeInTheDocument();
  });
});

describe('restored and gone entries', () => {
  it('marks a publication that disappeared from or came back to Mercado Libre', async () => {
    publicacionesMlAPI.history.mockResolvedValue({
      data: {
        entries: [
          { ...HISTORY_ENTRIES[0], id: 1, kind: 'gone', business: [], technical: [] },
          { ...HISTORY_ENTRIES[0], id: 2, kind: 'restored', business: [], technical: [] },
        ],
        next_cursor: null,
      },
    });
    renderTab();
    expect(await screen.findByText('Eliminada de Mercado Libre')).toBeInTheDocument();
    expect(screen.getByText('Restaurada en Mercado Libre')).toBeInTheDocument();
  });
});

describe('paging and honest states', () => {
  it('"Ver más" loads the next page with the cursor and appends it', async () => {
    const cursor = '2026-10-07T18:00:00.000000Z|7002';
    publicacionesMlAPI.history
      .mockResolvedValueOnce({ data: { entries: HISTORY_ENTRIES.slice(0, 1), next_cursor: cursor } })
      .mockResolvedValueOnce({ data: { entries: HISTORY_ENTRIES.slice(1, 2), next_cursor: null } });
    renderTab();
    await screen.findByText('Precio');

    await userEvent.click(screen.getByRole('button', { name: 'Ver más' }));

    await screen.findByText('Stock por ubicación');
    expect(publicacionesMlAPI.history).toHaveBeenLastCalledWith('MLA1100000001', { cursor });
    expect(screen.getByText('Precio')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Ver más' })).not.toBeInTheDocument();
  });

  it('shows the empty state when there are no changes (S58.2)', async () => {
    publicacionesMlAPI.history.mockResolvedValue({ data: { entries: [], next_cursor: null } });
    renderTab();
    expect(await screen.findByText(/no hay cambios registrados/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Ver todo' })).not.toBeInTheDocument();
  });

  it('shows an error with a retry that asks again', async () => {
    publicacionesMlAPI.history.mockRejectedValueOnce(httpError(500)).mockResolvedValueOnce({ data: HISTORY_RESPONSE });
    renderTab();
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo cargar el historial.');

    await userEvent.click(screen.getByRole('button', { name: 'Reintentar' }));

    expect(await screen.findByText('Precio')).toBeInTheDocument();
    expect(publicacionesMlAPI.history).toHaveBeenCalledTimes(2);
  });
});
