/**
 * The "Costos TP" toggle on the Métricas ML page: who sees it, what it asks every board request (and the CSV)
 * for, what it shows with the answer, and how a 403 / 503 turns it back off.
 */
import { describe, it, expect, vi, beforeEach, afterAll } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import MetricasML from './MetricasML';
import api, { productosAPI } from '../services/api';
import { BOARD_RESPONSE } from '../test/visual/metricasMlFixtures';
import { seedTiendasOficiales, resetTiendasOficiales } from '../test/tiendasOficialesFixtures';
import { withTp } from '../components/metricasMl/tpFixtures';

let granted;
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: (code) => granted.includes(code), cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));
vi.mock('../utils/ventasMlExport', async (importOriginal) => ({
  ...(await importOriginal()),
  exportMetricasCsv: vi.fn().mockResolvedValue(undefined),
}));
const { exportMetricasCsv } = await import('../utils/ventasMlExport');

// What a TP request answers: the TP board, or a rejection with this status.
let tpFailure;
// Only the publications request with TP costs fails with this status; and the board without TP costs fails
// (a 500, `'fails'`) or never answers (`'hangs'`) once `plainBoard` says so.
let pubsTpFailure;
let plainBoard;
const reject = (status) => Promise.reject({ response: { status, data: { detail: 'x' } } });
const tpAnswer = (data) => (tpFailure ? reject(tpFailure) : Promise.resolve({ data }));

beforeEach(() => {
  seedTiendasOficiales();
  granted = ['ml_metricas.ver', 'ml_metricas.ver_ganancia'];
  tpFailure = null;
  pubsTpFailure = null;
  plainBoard = 'ok';
  exportMetricasCsv.mockClear();
  api.get.mockReset();
  api.get.mockImplementation((url, config) => {
    const tp = config?.params?.costos_tp;
    if (url === '/ml-metricas/board') {
      if (tp) return tpAnswer(withTp());
      if (plainBoard === 'fails') return reject(500);
      if (plainBoard === 'hangs') return new Promise(() => {});
      return Promise.resolve({ data: BOARD_RESPONSE });
    }
    if (url === '/ml-metricas/board/products/4101/publications') {
      const rows = [{ ...BOARD_RESPONSE.rows[0], key: 'MLA1', mla: 'MLA1', total_tp: null, tp_incompletos: 2 }];
      if (tp && pubsTpFailure) return reject(pubsTpFailure);
      return tp ? tpAnswer({ rows, total: 1 }) : Promise.resolve({ data: { rows: [], total: 0 } });
    }
    return Promise.resolve({ data: {} });
  });
  productosAPI.marcas.mockResolvedValue({ data: { marcas: [] } });
  productosAPI.subcategorias.mockResolvedValue({ data: { categorias: [] } });
});

afterAll(resetTiendasOficiales);

const boardCalls = () => api.get.mock.calls.filter(([url]) => url === '/ml-metricas/board');
const lastBoardParams = () => boardCalls().at(-1)[1].params;
const toggle = () => screen.findByRole('switch', { name: 'Costos TP' });
const turnOn = async () => {
  await userEvent.click(await toggle());
  await waitFor(() => expect(lastBoardParams().costos_tp).toBe(true));
};

describe('MetricasML Costos TP toggle', () => {
  it('starts off and asks for no TP costs', async () => {
    await renderWithRouter(<MetricasML />);
    expect(await toggle()).toHaveAttribute('aria-checked', 'false');
    await waitFor(() => expect(boardCalls().length).toBeGreaterThan(0));
    expect(lastBoardParams()).not.toHaveProperty('costos_tp');
    expect(screen.queryByRole('columnheader', { name: 'Total TP' })).not.toBeInTheDocument();
  });

  it('hides the toggle without ver_ganancia, and never asks for TP costs', async () => {
    granted = ['ml_metricas.ver'];
    await renderWithRouter(<MetricasML />);
    await waitFor(() => expect(boardCalls().length).toBeGreaterThan(0));
    expect(screen.queryByRole('switch', { name: 'Costos TP' })).not.toBeInTheDocument();
    expect(lastBoardParams()).not.toHaveProperty('costos_tp');
  });

  it('on: the Total TP card and column next to Total Gauss, which stays', async () => {
    await renderWithRouter(<MetricasML />);
    await turnOn();
    expect(await screen.findByRole('columnheader', { name: 'Total TP' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /Total Gauss/ })).toBeInTheDocument();
    const headers = screen.getAllByRole('columnheader').map((th) => th.textContent);
    expect(headers.indexOf('Total TP')).toBe(headers.indexOf('Total Gauss') + 1);
    expect(screen.getByText('$ 3.125.400,50')).toBeInTheDocument();
    expect(screen.getByText('$ 9.850.000,25')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /Markup act\./ })).toHaveAttribute(
      'title',
      'Usa el costo TP en las operaciones de la tienda TP-Link',
    );
  });

  it('on: an unknown Total TP reads as an incomplete dash and lines without a TP cost get a warning count', async () => {
    await renderWithRouter(<MetricasML />);
    await turnOn();
    const cells = await screen.findAllByTestId('total-tp-cell');
    const partial = cells[1];
    expect(within(partial).getByText('$ 1.240.000,00')).toBeInTheDocument();
    expect(within(partial).getByTitle('2 ventas de la tienda TP-Link sin costo TP: el Total TP está incompleto')).toHaveTextContent('2');
    const unknown = cells[2];
    expect(within(unknown).getByText('—')).toBeInTheDocument();
    expect(within(unknown).getByText('incompleto')).toBeInTheDocument();
    // A row without any TP-store sale: a plain dash, never "incompleto" and never 0.
    const none = cells[3];
    expect(within(none).getByText('—')).toBeInTheDocument();
    expect(within(none).queryByText('incompleto')).not.toBeInTheDocument();
  });

  it('on: a product opens into publications asked with TP costs, showing their Total TP', async () => {
    await renderWithRouter(<MetricasML />);
    await turnOn();
    await userEvent.click(await screen.findByRole('button', { name: /publicaciones de Impresora Multifunción Epson/ }));
    const call = api.get.mock.calls.find(([url]) => url === '/ml-metricas/board/products/4101/publications');
    expect(call[1].params.costos_tp).toBe(true);
    await waitFor(() => expect(document.querySelector('tr[data-depth="1"] [data-testid="total-tp-cell"]')).not.toBeNull());
    expect(within(document.querySelector('tr[data-depth="1"] [data-testid="total-tp-cell"]')).getByText('incompleto')).toBeInTheDocument();
  });

  it('on: the group tree asks its nodes with TP costs', async () => {
    await renderWithRouter(<MetricasML />);
    await turnOn();
    await userEvent.click(within(screen.getByRole('group', { name: 'Agrupar por' })).getByRole('button', { name: 'Agrupado' }));
    await waitFor(() => expect(lastBoardParams().group_by).toBe('group'));
    expect(lastBoardParams().costos_tp).toBe(true);
  });

  it('on: sorts by Total TP from its column header', async () => {
    await renderWithRouter(<MetricasML />);
    await turnOn();
    await userEvent.click(await screen.findByRole('button', { name: 'Total TP' }));
    await waitFor(() => expect(lastBoardParams().sort).toBe('total_tp'));
    expect(lastBoardParams().costos_tp).toBe(true);
  });

  it('turning it off while sorted by Total TP falls back to Facturado', async () => {
    await renderWithRouter(<MetricasML />);
    await turnOn();
    await userEvent.click(await screen.findByRole('button', { name: 'Total TP' }));
    await waitFor(() => expect(lastBoardParams().sort).toBe('total_tp'));
    await userEvent.click(await toggle());
    await waitFor(() => expect(lastBoardParams()).not.toHaveProperty('costos_tp'));
    expect(lastBoardParams().sort).toBe('gross');
    expect(boardCalls().filter(([, config]) => !config.params.costos_tp).map(([, c]) => c.params.sort)).not.toContain('total_tp');
  });

  it('a TP refusal while sorted by Total TP also falls back to Facturado', async () => {
    await renderWithRouter(<MetricasML />);
    await turnOn();
    await userEvent.click(await screen.findByRole('button', { name: 'Total TP' }));
    await waitFor(() => expect(lastBoardParams().sort).toBe('total_tp'));
    tpFailure = 503;
    // The next TP request (the other sort direction) is refused.
    await userEvent.click(screen.getByRole('button', { name: 'Total TP' }));
    await waitFor(() => expect(screen.getByRole('switch', { name: 'Costos TP' })).toHaveAttribute('aria-checked', 'false'));
    await waitFor(() => expect(lastBoardParams()).not.toHaveProperty('costos_tp'));
    expect(lastBoardParams().sort).toBe('gross');
  });

  it('exports the CSV with TP costs while the toggle is on', async () => {
    await renderWithRouter(<MetricasML />);
    await turnOn();
    await userEvent.click(screen.getByRole('button', { name: /Exportar CSV/ }));
    await waitFor(() => expect(exportMetricasCsv).toHaveBeenCalled());
    expect(exportMetricasCsv.mock.calls[0][0].costos_tp).toBe(true);
  });

  it.each([
    [403, 'No tenés permiso para ver los costos TP. Se desactivó "Costos TP".'],
    [503, 'Los costos TP no están disponibles: no hay una tienda TP-Link configurada. Se desactivó "Costos TP".'],
  ])('a %s says why and turns the toggle back off', async (status, message) => {
    tpFailure = status;
    await renderWithRouter(<MetricasML />);
    await userEvent.click(await toggle());
    expect(await screen.findByText(message)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('switch', { name: 'Costos TP' })).toHaveAttribute('aria-checked', 'false'));
    await waitFor(() => expect(lastBoardParams()).not.toHaveProperty('costos_tp'));
    // The board reloads without TP costs: not the generic "no permission for Métricas ML".
    expect(screen.queryByText('No tenés permiso para ver Métricas ML.')).not.toBeInTheDocument();
    expect(await screen.findByRole('columnheader', { name: /Total Gauss/ })).toBeInTheDocument();
  });

  const TP_MESSAGES = {
    403: 'No tenés permiso para ver los costos TP. Se desactivó "Costos TP".',
    503: 'Los costos TP no están disponibles: no hay una tienda TP-Link configurada. Se desactivó "Costos TP".',
  };
  const openWithTpFailure = async (status, reload) => {
    await renderWithRouter(<MetricasML />);
    await turnOn();
    await screen.findByRole('columnheader', { name: 'Total TP' });
    pubsTpFailure = status;
    plainBoard = reload;
    await userEvent.click(await screen.findByRole('button', { name: /publicaciones de Impresora Multifunción Epson/ }));
    expect(await screen.findByText(TP_MESSAGES[status])).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('switch', { name: 'Costos TP' })).toHaveAttribute('aria-checked', 'false'));
    await waitFor(() => expect(lastBoardParams()).not.toHaveProperty('costos_tp'));
  };

  it.each([403, 503])('a %s on an opened product turns it off and the failed board reload says so', async (status) => {
    await openWithTpFailure(status, 'fails');
    expect(await screen.findByText('Error al cargar las métricas.')).toBeInTheDocument();
    expect(screen.queryByText('Cargando publicaciones…')).not.toBeInTheDocument();
  });

  it.each([403, 503])('a %s on an opened product never leaves its row loading while the reload is pending', async (status) => {
    await openWithTpFailure(status, 'hangs');
    // The old board stays on screen until the reload answers: the opened row ends in its error note.
    expect(await screen.findByText('No se pudieron cargar las publicaciones.')).toBeInTheDocument();
    expect(screen.queryByText('Cargando publicaciones…')).not.toBeInTheDocument();
  });
});
