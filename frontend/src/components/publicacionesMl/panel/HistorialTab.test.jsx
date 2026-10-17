/**
 * Historial tab: what changed in the publication, from `ml_change_log`, one
 * card per change named by its resource (Visitas, Promociones, ...), each line
 * a Spanish label with the value before and after, already formatted by the
 * backend. Technical lines stay hidden, counted in a footer, until "Mostrar
 * datos técnicos" asks the backend for them (`tecnicos=true`).
 *
 * The bodies are real API responses (`fixtures/eventsHistory_MLA1402898289_20261016.json`).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import HistorialTab from './HistorialTab';
import { publicacionesMlAPI } from '../../../services/api';
import capture from './fixtures/eventsHistory_MLA1402898289_20261016.json';

vi.mock('../../../services/api', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  publicacionesMlAPI: { history: vi.fn() },
  registerAuthFailureHandler: vi.fn(),
}));

const RESPONSE = capture.history;
const TECNICOS = capture.history_tecnicos;
const entry = (id, body = RESPONSE) => body.entries.find((found) => found.id === id);
const page = (entries, nextCursor = null) => ({ data: { entries, next_cursor: nextCursor, hidden_technical_count: entries.reduce((n, e) => n + e.hidden_technical_count, 0) } });
const httpError = (status) => Object.assign(new Error(`HTTP ${status}`), { response: { status } });
const renderTab = (itemId = 'MLA1402898289') => render(<HistorialTab itemId={itemId} />);
const cards = () => screen.getAllByRole('listitem');
const cardOf = (id) => document.querySelector(`[data-entry="${id}"]`);
const toggle = () => screen.getByRole('button', { name: 'Mostrar datos técnicos' });

beforeEach(() => {
  publicacionesMlAPI.history.mockReset();
  publicacionesMlAPI.history.mockImplementation((itemId, params) => Promise.resolve({ data: params?.tecnicos ? TECNICOS : RESPONSE }));
});

describe('the changes', () => {
  it('asks for the history of the selected publication, without the technical lines', async () => {
    renderTab();
    await screen.findAllByText('Visitas');
    expect(publicacionesMlAPI.history).toHaveBeenCalledTimes(1);
    expect(publicacionesMlAPI.history).toHaveBeenCalledWith('MLA1402898289', {});
  });

  it('one card per change, named by its resource, leaving out the changes with nothing to show', async () => {
    renderTab();
    await screen.findAllByText('Visitas');
    // 148600 (visits) holds only technical lines: hidden.
    expect(cards()).toHaveLength(RESPONSE.entries.length - 1);
    expect(cardOf(148600)).toBeNull();
    expect(within(cardOf(34965)).getByText('Visitas')).toBeInTheDocument();
    expect(within(cardOf(172543)).getByText('Ventas semanales (Full)')).toBeInTheDocument();
    expect(within(cardOf(6989)).getByText('Publicación y stock')).toBeInTheDocument();
    expect(within(cardOf(7672)).getByText('Promociones')).toBeInTheDocument();
    expect(screen.queryByText('Otro recurso')).not.toBeInTheDocument();
  });

  it('each line is its label with the value before and after, as the backend wrote them', async () => {
    renderTab();
    await screen.findAllByText('Visitas');
    const price = within(cardOf(6989)).getByText('Precio').closest('[data-line]');
    expect(price).toHaveTextContent('Precio$ 80.049→$ 91.193');
    const visits = within(cardOf(34965)).getByText('Visitas de los últimos 30 días').closest('[data-line]');
    expect(visits).toHaveTextContent('17→18');
  });

  it('a value that appears shows only the new one; one that goes away shows the dash after the arrow', async () => {
    renderTab();
    await screen.findAllByText('Visitas');
    const added = within(cardOf(7671)).getByText('Precio de promoción').closest('[data-line]');
    expect(added.textContent).toBe('Precio de promoción$ 77.000');
    const removed = within(cardOf(6989)).getByText('Subestado').closest('[data-line]');
    expect(removed.textContent).toBe('SubestadoSin stock→—');
  });

  it('groups the lines of one promotion under its name and shows its state as a tag', async () => {
    renderTab();
    await screen.findAllByText('Visitas');
    const promos = cardOf(123143);
    expect(within(promos).getAllByText('Tec Week').length).toBeGreaterThan(0);
    expect(within(promos).getAllByText('Disponible para activar')).toHaveLength(2);
    expect(within(cardOf(71677)).getByText('Finalizada')).toBeInTheDocument();
  });

  it('says who caused each change', async () => {
    renderTab();
    await screen.findAllByText('Visitas');
    expect(within(cardOf(34965)).getByText('Informativo de ML')).toBeInTheDocument();
    expect(within(cardOf(140177)).getByText('Cambio de ML')).toBeInTheDocument();
    expect(within(cardOf(6989)).getByText('Origen sin registrar')).toBeInTheDocument();
  });

  it('never shows raw JSON or a field path', async () => {
    renderTab();
    await screen.findAllByText('Visitas');
    const text = document.body.textContent;
    expect(text).not.toMatch(/[{}[\]]/);
    expect(text).not.toMatch(/available_quantity|sub_status|last_updated/);
  });
});

describe('the resource chips', () => {
  const chip = (name) => screen.getByRole('button', { name });
  const shownIds = () => cards().map((card) => Number(card.getAttribute('data-entry')));

  it('start on "Todo", with every card', async () => {
    renderTab();
    await screen.findAllByText('Visitas');
    expect(chip('Todo')).toHaveAttribute('aria-pressed', 'true');
    expect(cards()).toHaveLength(13);
  });

  it('narrow the cards by resource, and "Todo" brings them back', async () => {
    renderTab();
    await screen.findAllByText('Visitas');

    await userEvent.click(chip('Precio'));
    expect(chip('Precio')).toHaveAttribute('aria-pressed', 'true');
    expect(shownIds()).toEqual([140177, 70046, 7673, 7671, 7666, 6989]);

    await userEvent.click(chip('Stock'));
    expect(shownIds()).toEqual([175494, 70046, 7666, 6989]);

    await userEvent.click(chip('Promociones'));
    expect(shownIds()).toEqual([123143, 71677, 9282, 7672]);

    await userEvent.click(chip('Visitas y ventas'));
    expect(shownIds()).toEqual([172543, 34965]);

    await userEvent.click(chip('Todo'));
    expect(cards()).toHaveLength(13);
  });

  it('say so when a chip leaves nothing on the loaded page', async () => {
    publicacionesMlAPI.history.mockResolvedValue(page([entry(175494)]));
    renderTab();
    await screen.findByText('Stock disponible');
    await userEvent.click(chip('Promociones'));
    expect(screen.queryByRole('listitem')).not.toBeInTheDocument();
    expect(screen.getByText('Ningún cambio de los cargados coincide con este filtro.')).toBeInTheDocument();
  });
});

describe('the technical lines', () => {
  it('are hidden and counted in the footer', async () => {
    renderTab();
    await screen.findAllByText('Visitas');
    expect(screen.getByText(/^Ocultos 74 cambios técnicos/)).toBeInTheDocument();
    expect(screen.queryByText('Última actualización')).not.toBeInTheDocument();
  });

  it('"Mostrar datos técnicos" asks the backend for them and shows them; off again hides them', async () => {
    renderTab();
    await screen.findAllByText('Visitas');
    expect(toggle()).toHaveAttribute('aria-pressed', 'false');

    await userEvent.click(toggle());

    expect(await screen.findAllByText('Última actualización')).not.toHaveLength(0);
    expect(publicacionesMlAPI.history).toHaveBeenLastCalledWith('MLA1402898289', { tecnicos: true });
    expect(toggle()).toHaveAttribute('aria-pressed', 'true');
    expect(cardOf(148600)).not.toBeNull();
    expect(screen.queryByText(/^Ocultos/)).not.toBeInTheDocument();

    await userEvent.click(toggle());

    await screen.findByText(/^Ocultos 74 cambios técnicos/);
    expect(publicacionesMlAPI.history).toHaveBeenLastCalledWith('MLA1402898289', {});
    expect(screen.queryByText('Última actualización')).not.toBeInTheDocument();
  });

  it('the footer says one in singular, and is absent when nothing is hidden', async () => {
    publicacionesMlAPI.history.mockResolvedValue(page([entry(175494)]));
    const { unmount } = renderTab();
    expect(await screen.findByText(/^Oculto 1 cambio técnico/)).toBeInTheDocument();
    unmount();

    publicacionesMlAPI.history.mockResolvedValue(page([{ ...entry(175494), hidden_technical_count: 0 }]));
    renderTab();
    await screen.findByText('Stock disponible');
    expect(screen.queryByText(/^Oculto/)).not.toBeInTheDocument();
  });

  it('turn off again when the selection moves to another publication', async () => {
    const { rerender } = renderTab('MLA1');
    await screen.findAllByText('Visitas');
    await userEvent.click(toggle());
    await screen.findAllByText('Última actualización');

    rerender(<HistorialTab itemId="MLA2" />);

    await screen.findAllByText('Visitas');
    expect(publicacionesMlAPI.history).toHaveBeenLastCalledWith('MLA2', {});
    expect(toggle()).toHaveAttribute('aria-pressed', 'false');
  });

  it('says so when the page holds only technical changes', async () => {
    publicacionesMlAPI.history.mockResolvedValue(page([entry(148600)]));
    renderTab();
    expect(await screen.findByText('En esta página solo hay cambios técnicos.')).toBeInTheDocument();
    expect(screen.queryByRole('listitem')).not.toBeInTheDocument();
  });
});

describe('restored and gone entries', () => {
  it('marks a publication that disappeared from or came back to Mercado Libre, even without lines', async () => {
    const base = entry(6989);
    const empty = { business: [], technical: [], rows: [], hidden_technical_count: 0 };
    publicacionesMlAPI.history.mockResolvedValue(page([{ ...base, ...empty, id: 1, kind: 'gone' }, { ...base, ...empty, id: 2, kind: 'restored' }]));
    renderTab();
    expect(await screen.findByText('Eliminada de Mercado Libre')).toBeInTheDocument();
    expect(screen.getByText('Restaurada en Mercado Libre')).toBeInTheDocument();
  });
});

describe('paging and honest states', () => {
  it('"Ver más" loads the next page with the cursor, keeping the technical choice', async () => {
    const cursor = '2026-10-15T13:49:31.393877Z|123143';
    const first = TECNICOS.entries.slice(0, 4);
    publicacionesMlAPI.history.mockImplementation((itemId, params) =>
      Promise.resolve(params.cursor ? page(TECNICOS.entries.slice(4)) : page(params.tecnicos ? first : RESPONSE.entries.slice(0, 4), cursor)),
    );
    renderTab();
    await screen.findByText('Ventas semanales (Full)');
    await userEvent.click(toggle());
    await screen.findAllByText('Última actualización');

    await userEvent.click(screen.getByRole('button', { name: 'Ver más' }));

    expect(await screen.findAllByText('Publicación y stock')).not.toHaveLength(0);
    expect(publicacionesMlAPI.history).toHaveBeenLastCalledWith('MLA1402898289', { tecnicos: true, cursor });
    expect(screen.queryByRole('button', { name: 'Ver más' })).not.toBeInTheDocument();
  });

  it('shows the empty state when there are no changes', async () => {
    publicacionesMlAPI.history.mockResolvedValue(page([]));
    renderTab();
    expect(await screen.findByText(/no hay cambios registrados/i)).toBeInTheDocument();
  });

  it('shows an error with a retry that asks again', async () => {
    publicacionesMlAPI.history.mockRejectedValueOnce(httpError(500)).mockResolvedValueOnce({ data: RESPONSE });
    renderTab();
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo cargar el historial.');

    await userEvent.click(screen.getByRole('button', { name: 'Reintentar' }));

    expect(await screen.findAllByText('Visitas')).not.toHaveLength(0);
    expect(publicacionesMlAPI.history).toHaveBeenCalledTimes(2);
  });
});
