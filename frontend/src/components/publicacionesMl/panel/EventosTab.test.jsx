/**
 * Eventos tab (publicaciones-ml-vista P13b.T1, S55.x/S57.1): the publication's
 * real events, newest first, a page at a time. With the events flag off the
 * tab says so instead of showing an empty list as if nothing happened.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import EventosTab from './EventosTab';
import { publicacionesMlAPI } from '../../../services/api';
import { EVENTS, EVENTS_DISABLED_RESPONSE, EVENTS_RESPONSE, makeEvent } from '../../../test/visual/publicacionesMlFixtures';

vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  publicacionesMlAPI: { events: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

const httpError = (status) => Object.assign(new Error(`HTTP ${status}`), { response: { status } });
const renderTab = (itemId = 'MLA1100000001') => render(<EventosTab itemId={itemId} />);
const entries = () => screen.getAllByRole('listitem');

beforeEach(() => {
  publicacionesMlAPI.events.mockReset();
  publicacionesMlAPI.events.mockResolvedValue({ data: EVENTS_RESPONSE });
});

describe('the events', () => {
  it('asks for the events of the selected publication and lists them in the order received', async () => {
    renderTab();
    await screen.findByText('Precio modificado');
    expect(publicacionesMlAPI.events).toHaveBeenCalledTimes(1);
    expect(publicacionesMlAPI.events).toHaveBeenCalledWith('MLA1100000001', {});
    expect(entries().map((li) => li.textContent)).toEqual([
      expect.stringContaining('Precio modificado'),
      expect.stringContaining('Pausada'),
      expect.stringContaining('Precio de promoción modificado'),
    ]);
  });

  it('labels each event from its type, in Spanish, not from the label the backend sent', async () => {
    publicacionesMlAPI.events.mockResolvedValue({
      data: { ...EVENTS_RESPONSE, events: [makeEvent({ id: 1, event_type: 'title_changed', label: 'BACKEND LABEL', old_value: 'a', new_value: 'b' })] },
    });
    renderTab();
    expect(await screen.findByText('Título modificado')).toBeInTheDocument();
    expect(screen.queryByText('BACKEND LABEL')).not.toBeInTheDocument();
  });

  it('shows a generic Spanish label for a type nobody labelled', async () => {
    publicacionesMlAPI.events.mockResolvedValue({ data: { ...EVENTS_RESPONSE, events: [makeEvent({ id: 1, event_type: 'brand_new_type' })] } });
    renderTab();
    expect(await screen.findByText('Evento')).toBeInTheDocument();
    expect(screen.queryByText('brand_new_type')).not.toBeInTheDocument();
  });

  it('shows what changed: a price as money, a status as text, and when it happened', async () => {
    renderTab();
    const price = (await screen.findByText('Precio modificado')).closest('li');
    expect(within(price).getByText(/55\.882/)).toBeInTheDocument();
    expect(within(price).getByText(/56\.382/)).toBeInTheDocument();
    expect(within(price).getByText(/\d{2}\/\d{2}\/\d{4}/)).toBeInTheDocument();
    const status = screen.getByText('Pausada').closest('li');
    expect(within(status).getByText(/active/)).toBeInTheDocument();
    expect(within(status).getByText(/paused/)).toBeInTheDocument();
  });

  it('names the promotion type of a promotion event', async () => {
    renderTab();
    const promo = (await screen.findByText('Precio de promoción modificado')).closest('li');
    expect(within(promo).getByText(/DEAL/)).toBeInTheDocument();
  });

  it('shows an event without values as just its label and date', async () => {
    publicacionesMlAPI.events.mockResolvedValue({
      data: { ...EVENTS_RESPONSE, events: [makeEvent({ id: 1, event_type: 'item_gone', price_kind: null, old_value: null, new_value: null })] },
    });
    renderTab();
    const gone = (await screen.findByText('Eliminada de ML')).closest('li');
    expect(gone.textContent).not.toMatch(/→/);
  });
});

describe('paging', () => {
  it('offers "Ver más" only while the backend has a next cursor, and asks for the next page with it', async () => {
    const cursor = '2026-10-06T12:00:00.000000Z|8999';
    publicacionesMlAPI.events
      .mockResolvedValueOnce({ data: { ...EVENTS_RESPONSE, events: EVENTS.slice(0, 2), next_cursor: cursor } })
      .mockResolvedValueOnce({ data: { ...EVENTS_RESPONSE, events: EVENTS.slice(2), next_cursor: null } });
    renderTab();
    await screen.findByText('Precio modificado');
    expect(entries()).toHaveLength(2);

    await userEvent.click(screen.getByRole('button', { name: 'Ver más' }));

    await screen.findByText('Precio de promoción modificado');
    expect(publicacionesMlAPI.events).toHaveBeenLastCalledWith('MLA1100000001', { cursor });
    expect(entries()).toHaveLength(3);
    expect(screen.queryByRole('button', { name: 'Ver más' })).not.toBeInTheDocument();
  });

  it('keeps what is shown and offers a retry when the next page fails', async () => {
    publicacionesMlAPI.events
      .mockResolvedValueOnce({ data: { ...EVENTS_RESPONSE, events: EVENTS.slice(0, 2), next_cursor: 'c|1' } })
      .mockRejectedValueOnce(httpError(500))
      .mockResolvedValueOnce({ data: { ...EVENTS_RESPONSE, events: EVENTS.slice(2), next_cursor: null } });
    renderTab();
    await screen.findByText('Precio modificado');
    await userEvent.click(screen.getByRole('button', { name: 'Ver más' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron cargar más eventos.');
    expect(entries()).toHaveLength(2);

    await userEvent.click(screen.getByRole('button', { name: 'Ver más' }));
    await screen.findByText('Precio de promoción modificado');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

describe('the honest states', () => {
  it('says the events are not being recorded when the flag is off (S55.4)', async () => {
    publicacionesMlAPI.events.mockResolvedValue({ data: EVENTS_DISABLED_RESPONSE });
    renderTab();
    expect(await screen.findByText(/eventos están desactivados/i)).toHaveAttribute('role', 'status');
    expect(screen.queryByText(/todavía no hay eventos/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('listitem')).not.toBeInTheDocument();
  });

  it('says there are no events yet when the flag is on and the list is empty', async () => {
    publicacionesMlAPI.events.mockResolvedValue({ data: { enabled: true, events: [], next_cursor: null } });
    renderTab();
    expect(await screen.findByText(/todavía no hay eventos/i)).toBeInTheDocument();
  });

  it('shows a loading note, then an error with a retry that asks again', async () => {
    publicacionesMlAPI.events.mockRejectedValueOnce(httpError(503)).mockResolvedValueOnce({ data: EVENTS_RESPONSE });
    renderTab();
    expect(screen.getByRole('status')).toHaveTextContent('Cargando eventos');
    expect(await screen.findByRole('alert')).toHaveTextContent('La consulta tardó demasiado');

    await userEvent.click(screen.getByRole('button', { name: 'Reintentar' }));

    expect(await screen.findByText('Precio modificado')).toBeInTheDocument();
    expect(publicacionesMlAPI.events).toHaveBeenCalledTimes(2);
  });

  it('never shows the previous publication\'s events under the next one', async () => {
    let resolveSecond;
    publicacionesMlAPI.events
      .mockResolvedValueOnce({ data: EVENTS_RESPONSE })
      .mockReturnValueOnce(new Promise((resolve) => (resolveSecond = resolve)));
    const { rerender } = renderTab('MLA1');
    await screen.findByText('Precio modificado');

    rerender(<EventosTab itemId="MLA2" />);

    expect(screen.queryByText('Precio modificado')).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Cargando eventos');
    resolveSecond({ data: { enabled: true, events: [], next_cursor: null } });
    expect(await screen.findByText(/todavía no hay eventos/i)).toBeInTheDocument();
  });
});
