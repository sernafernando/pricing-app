/**
 * Eventos tab: the publication's real events, newest first, a page at a time,
 * grouped by day, each one a readable sentence with who caused it (origin tag)
 * and, for promotions, its state. Filter chips narrow what is shown. With the
 * events flag off the tab says so instead of showing an empty list.
 *
 * The bodies are real API responses (`fixtures/eventsHistory_MLA1402898289_20261016.json`).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import EventosTab from './EventosTab';
import { publicacionesMlAPI } from '../../../services/api';
import capture from './fixtures/eventsHistory_MLA1402898289_20261016.json';

vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  publicacionesMlAPI: { events: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

const RESPONSE = capture.events;
const EVENTS = RESPONSE.events;
const byId = (id) => EVENTS.find((event) => event.id === id);
const page = (events, nextCursor = null) => ({ data: { enabled: true, events, next_cursor: nextCursor } });
const httpError = (status) => Object.assign(new Error(`HTTP ${status}`), { response: { status } });
const renderTab = (itemId = 'MLA1402898289') => render(<EventosTab itemId={itemId} />);
const entries = () => screen.getAllByRole('listitem');
const entryOf = (text) => screen.getByText(text).closest('li');
const chip = (name) => screen.getByRole('button', { name: new RegExp(`^${name}`) });

beforeEach(() => {
  // The day after the newest captured event's evening: 16/10 is "Hoy" (Buenos Aires time, as the users).
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date('2026-10-16T18:00:00-03:00'));
  publicacionesMlAPI.events.mockReset();
  publicacionesMlAPI.events.mockResolvedValue({ data: RESPONSE });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('the events', () => {
  it('asks for the events of the selected publication and lists them, newest first, ML offers of one minute folded', async () => {
    renderTab();
    await screen.findByText('Publicación reactivada');
    expect(publicacionesMlAPI.events).toHaveBeenCalledWith('MLA1402898289', {});
    // 22 events; 3 + 2 + 2 same-minute offers fold into 3 lines
    expect(entries()).toHaveLength(18);
  });

  it('a folded line counts the offers, names them and keeps their tags', async () => {
    renderTab();
    const offers = (await screen.findByText('ML ofreció 3 campañas del vendedor')).closest('li');
    expect(offers).toHaveTextContent('A- PVP LYONN, PVP LYONN y A - PVP TP');
    expect(within(offers).getByText('Informativo de ML')).toBeInTheDocument();
    expect(within(offers).getByText('Disponible para activar')).toBeInTheDocument();
    expect(screen.getByText('ML ofreció Campaña co-fondeada y Oferta relámpago co-fondeada')).toBeInTheDocument();
    expect(screen.getByText('ML ofreció 2 cupones del vendedor')).toBeInTheDocument();
  });

  it('each line has the icon of its family', async () => {
    renderTab();
    await screen.findByText('Publicación reactivada');
    const icon = (text) => entryOf(text).querySelector('[data-icon]').getAttribute('data-icon');
    expect(icon('ML ofreció 3 campañas del vendedor')).toBe('promotion');
    expect(icon('Publicación reactivada')).toBe('play');
    expect(icon('Publicación pausada')).toBe('pause');
    expect(icon('Dejó de competir en el catálogo')).toBe('star');
    expect(icon('Volvió a tener stock')).toBe('stock');
    expect(icon('Cambió el precio de lista')).toBe('price');
  });

  it('groups them by day: Hoy, Ayer, then the weekday and the date', async () => {
    renderTab();
    await screen.findByText('Publicación reactivada');
    const days = screen.getAllByRole('heading', { level: 3 }).map((heading) => heading.textContent);
    expect(days).toEqual(['Hoy', 'Ayer', 'Martes 13/10', 'Sábado 10/10']);
    const today = screen.getByRole('heading', { name: 'Hoy' }).closest('section');
    expect(within(today).getAllByRole('listitem')).toHaveLength(1);
  });

  it('each event is a sentence with its detail and its time of day', async () => {
    renderTab();
    const offer = (await screen.findByText('ML ofreció 3 campañas del vendedor')).closest('li');
    expect(within(offer).getByText('00:11')).toHaveAttribute('dateTime', byId(71200).observed_at);
    const paused = entryOf('Publicación pausada');
    expect(within(paused).getByText('15:37')).toHaveAttribute('dateTime', byId(42330).observed_at);
  });

  it('a price change shows both prices and the percentage', async () => {
    renderTab();
    await screen.findByText('Publicación reactivada');
    const [latest, earlier] = screen.getAllByText('Cambió el precio de venta').map((title) => title.closest('li'));
    expect(latest).toHaveTextContent('$ 77.000→$ 88.913+15,5 %');
    expect(earlier).toHaveTextContent('$ 91.193→$ 77.000−15,6 %');
  });

  it('never shows raw JSON or an event code', async () => {
    renderTab();
    await screen.findByText('Publicación reactivada');
    const text = document.body.textContent;
    expect(text).not.toMatch(/[{}]/);
    expect(text).not.toMatch(/promotion_offered|SELLER_CAMPAIGN|candidate/);
  });
});

describe('the tags', () => {
  it('say who caused each event: ML (informative or a change) or unknown', async () => {
    renderTab();
    const offer = (await screen.findByText('ML ofreció 3 campañas del vendedor')).closest('li');
    expect(within(offer).getByText('Informativo de ML')).toBeInTheDocument();
    expect(within(entryOf('Dejó de competir en el catálogo')).getByText('Cambio de ML')).toBeInTheDocument();
    expect(within(entryOf('Publicación pausada')).getByText('Origen sin registrar')).toBeInTheDocument();
  });

  it('name our user when we did it, and say "Automático" for our processes', async () => {
    publicacionesMlAPI.events.mockResolvedValue(
      page([
        { ...byId(3689), origin: { kind: 'nosotros', user_name: 'Fernando S.' } },
        { ...byId(43638), origin: { kind: 'automatico', user_name: null } },
      ]),
    );
    renderTab();
    const applied = (await screen.findByText('Activamos la promoción A PVP TODO (Campaña del vendedor) a $ 77.000')).closest('li');
    expect(within(applied).getByText('Hecho por nosotros · Fernando S.')).toBeInTheDocument();
    expect(within(applied).getByText('Aplicada')).toBeInTheDocument();
    expect(within(entryOf('Publicación reactivada')).getByText('Automático')).toBeInTheDocument();
  });

  it('show the promotion state: offered, applied, finished, no longer offered', async () => {
    renderTab();
    await screen.findByText('Publicación reactivada');
    expect(screen.getAllByText('Disponible para activar')).toHaveLength(3);
    expect(within(entryOf('Se aplicó la promoción A PVP TODO (Campaña del vendedor) a $ 77.000')).getByText('Aplicada')).toBeInTheDocument();
    expect(within(entryOf('Terminó la promoción A PVP TODO (Campaña del vendedor)')).getByText('Finalizada')).toBeInTheDocument();
    expect(screen.getAllByText('Ya no se ofrece')).toHaveLength(2);
  });
});

describe('the filter chips', () => {
  it('count the lines each filter shows', async () => {
    publicacionesMlAPI.events.mockResolvedValue(page([{ ...byId(3689), origin: { kind: 'nosotros', user_name: 'Fernando S.' } }, ...EVENTS.filter((e) => e.id !== 3689)]));
    renderTab();
    await screen.findByText('Publicación reactivada');
    expect(chip('Todos')).toHaveTextContent('Todos18');
    expect(chip('Hechos por nosotros')).toHaveTextContent('1');
    expect(chip('Cambios de ML')).toHaveTextContent('7');
    expect(chip('Solo importantes')).toHaveTextContent('13');
    expect(chip('Todos')).toHaveAttribute('aria-pressed', 'true');
  });

  it('narrow the list, and "Todos" brings everything back', async () => {
    renderTab();
    await screen.findByText('Publicación reactivada');

    await userEvent.click(chip('Solo importantes'));
    expect(entries()).toHaveLength(13);
    expect(screen.queryByText('Informativo de ML')).not.toBeInTheDocument();
    expect(chip('Solo importantes')).toHaveAttribute('aria-pressed', 'true');

    await userEvent.click(chip('Cambios de ML'));
    expect(entries()).toHaveLength(7);
    expect(screen.queryByText('Origen sin registrar')).not.toBeInTheDocument();

    await userEvent.click(chip('Todos'));
    expect(entries()).toHaveLength(18);
  });

  it('say so when a filter leaves nothing', async () => {
    renderTab();
    await screen.findByText('Publicación reactivada');
    await userEvent.click(chip('Hechos por nosotros'));
    expect(screen.queryByRole('listitem')).not.toBeInTheDocument();
    expect(screen.getByText('Ningún evento de los cargados coincide con este filtro.')).toBeInTheDocument();
  });
});

describe('paging', () => {
  it('offers "Ver más" only while the backend has a next cursor, and asks for the next page with it', async () => {
    const cursor = '2026-10-13T18:37:02.240017Z|42330';
    publicacionesMlAPI.events.mockResolvedValueOnce(page(EVENTS.slice(0, 2), cursor)).mockResolvedValueOnce(page(EVENTS.slice(2)));
    renderTab();
    await screen.findByText('ML ofreció 2 campañas del vendedor');
    expect(entries()).toHaveLength(1);

    await userEvent.click(screen.getByRole('button', { name: 'Ver más' }));

    await screen.findByText('Publicación reactivada');
    expect(publicacionesMlAPI.events).toHaveBeenLastCalledWith('MLA1402898289', { cursor });
    // the third offer of the same minute, on the next page, joins the fold
    expect(screen.getByText('ML ofreció 3 campañas del vendedor')).toBeInTheDocument();
    expect(entries()).toHaveLength(18);
    expect(screen.queryByRole('button', { name: 'Ver más' })).not.toBeInTheDocument();
  });

  it('keeps what is shown and offers a retry when the next page fails', async () => {
    publicacionesMlAPI.events
      .mockResolvedValueOnce(page(EVENTS.slice(0, 2), 'c|1'))
      .mockRejectedValueOnce(httpError(500))
      .mockResolvedValueOnce(page(EVENTS.slice(2)));
    renderTab();
    await screen.findByText('ML ofreció 2 campañas del vendedor');
    await userEvent.click(screen.getByRole('button', { name: 'Ver más' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron cargar más eventos.');
    expect(entries()).toHaveLength(1);

    await userEvent.click(screen.getByRole('button', { name: 'Ver más' }));
    await screen.findByText('Publicación reactivada');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

describe('the honest states', () => {
  it('says the events are not being recorded when the flag is off', async () => {
    publicacionesMlAPI.events.mockResolvedValue({ data: { enabled: false, events: [], next_cursor: null } });
    renderTab();
    expect(await screen.findByText(/eventos están desactivados/i)).toHaveAttribute('role', 'status');
    expect(screen.queryByRole('listitem')).not.toBeInTheDocument();
  });

  it('says there are no events yet when the flag is on and the list is empty', async () => {
    publicacionesMlAPI.events.mockResolvedValue(page([]));
    renderTab();
    expect(await screen.findByText(/todavía no hay eventos/i)).toBeInTheDocument();
  });

  it('shows a loading note, then an error with a retry that asks again', async () => {
    publicacionesMlAPI.events.mockRejectedValueOnce(httpError(503)).mockResolvedValueOnce({ data: RESPONSE });
    renderTab();
    expect(screen.getByRole('status')).toHaveTextContent('Cargando eventos');
    expect(await screen.findByRole('alert')).toHaveTextContent('La consulta tardó demasiado');

    await userEvent.click(screen.getByRole('button', { name: 'Reintentar' }));

    expect(await screen.findByText('Publicación reactivada')).toBeInTheDocument();
    expect(publicacionesMlAPI.events).toHaveBeenCalledTimes(2);
  });

  it("never shows the previous publication's events under the next one", async () => {
    let resolveSecond;
    publicacionesMlAPI.events.mockResolvedValueOnce({ data: RESPONSE }).mockReturnValueOnce(new Promise((resolve) => (resolveSecond = resolve)));
    const { rerender } = renderTab('MLA1');
    await screen.findByText('Publicación reactivada');

    rerender(<EventosTab itemId="MLA2" />);

    expect(screen.queryByText('Publicación reactivada')).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Cargando eventos');
    resolveSecond(page([]));
    expect(await screen.findByText(/todavía no hay eventos/i)).toBeInTheDocument();
  });
});
