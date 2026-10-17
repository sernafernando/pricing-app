import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import { productosAPI } from '../services/api';
import { sellInAPI } from '../services/sellInAPI';
import { LISTA, RESUMEN } from '../components/sellIn/sellInFixtures';
import SellIn from './SellIn';

vi.mock('../services/sellInAPI', () => ({
  sellInAPI: {
    listar: vi.fn(),
    resumen: vi.fn(),
    detalle: vi.fn(),
    preview: vi.fn(),
    crear: vi.fn(),
    anular: vi.fn(),
  },
}));

const mockTienePermiso = vi.fn();
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: (codigo) => mockTienePermiso(codigo), cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

const lastParams = (fn) => fn.mock.calls[fn.mock.calls.length - 1][0];

beforeEach(() => {
  vi.clearAllMocks();
  mockTienePermiso.mockReturnValue(true);
  sellInAPI.listar.mockResolvedValue({ data: LISTA });
  sellInAPI.resumen.mockResolvedValue({ data: RESUMEN });
  productosAPI.marcas.mockResolvedValue({ data: { marcas: ['Mercusys', 'TP-Link'] } });
});

describe('SellIn page — list', () => {
  it('opens on the sell ins that apply, and asks the summary for the same filters', async () => {
    renderWithRouter(<SellIn />);
    expect(await screen.findByText('Bonificación Q4 switches')).toBeInTheDocument();
    expect(lastParams(sellInAPI.listar)).toEqual({ aplica: 'si', page: 1, page_size: 50 });
    expect(lastParams(sellInAPI.resumen)).toEqual({ aplica: 'si' });
  });

  it('counts the Aplican / No aplican / Todas chips from resumen.conteo and filters by aplica', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    const chips = await screen.findByRole('group', { name: 'Aplicación' });
    expect(within(chips).getByRole('button', { name: 'Aplican · 3' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(chips).getByRole('button', { name: 'No aplican · 1' })).toBeInTheDocument();
    await user.click(within(chips).getByRole('button', { name: 'Todas · 4' }));
    await waitFor(() => expect(lastParams(sellInAPI.listar)).toEqual({ aplica: 'todas', page: 1, page_size: 50 }));
    await user.click(within(chips).getByRole('button', { name: 'No aplican · 1' }));
    await waitFor(() => expect(lastParams(sellInAPI.listar).aplica).toBe('no'));
  });

  it('shows the summary cards from resumen', async () => {
    renderWithRouter(<SellIn />);
    const cards = await screen.findByRole('region', { name: 'Resumen' });
    await waitFor(() => expect(within(cards).getByText('USD 5,50')).toBeInTheDocument());
    expect(within(cards).getByText('$ 3.000,00')).toBeInTheDocument();
    expect(within(cards).getByText('32')).toBeInTheDocument();
    expect(within(cards).getByText('3')).toBeInTheDocument();
  });

  it('renders supplier, amount, units and only the Activa / Anulada states', async () => {
    renderWithRouter(<SellIn />);
    const fila = (await screen.findByText('Bonificación Q4 switches')).closest('tr');
    expect(within(fila).getByText('TP-Link')).toBeInTheDocument();
    expect(within(fila).getByText('$ 1.000,00')).toBeInTheDocument();
    expect(within(fila).getByText('20 / 20')).toBeInTheDocument();
    expect(within(fila).getByText('Activa')).toBeInTheDocument();
    expect(within(fila).getByText('Aplica')).toBeInTheDocument();

    const anulada = screen.getByText('Descuento access points').closest('tr');
    expect(within(anulada).getByText('USD 2,00')).toBeInTheDocument();
    expect(within(anulada).getByText('TC 1.250,50')).toBeInTheDocument();
    expect(within(anulada).getByText('Anulada')).toBeInTheDocument();
    expect(within(anulada).getByText('No aplica')).toBeInTheDocument();
  });

  it('expands a row into its lines with the cost before and after the sell in', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    await user.click(screen.getAllByRole('button', { name: 'Ver ítems' })[0]);
    const linea = screen.getByText('Switch 8 bocas').closest('tr');
    expect(within(linea).getByText('SW-8')).toBeInTheDocument();
    expect(within(linea).getByText('$ 250,00')).toBeInTheDocument();
    expect(within(linea).getByText('$ 100,00')).toBeInTheDocument();
    expect(within(linea).getByText('$ 75,00')).toBeInTheDocument();
    expect(screen.getByText(/Reparto proporcional/)).toBeInTheDocument();
  });

  it('sends search, brand, currency and estado filters and resets to page 1', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    await user.selectOptions(screen.getByLabelText('Moneda'), 'USD');
    await user.selectOptions(screen.getByLabelText('Estado'), 'anulada');
    await waitFor(() => expect(screen.getByRole('option', { name: 'TP-Link' })).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText('Marca'), 'TP-Link');
    await waitFor(() =>
      expect(lastParams(sellInAPI.listar)).toEqual({
        aplica: 'si',
        moneda: 'USD',
        estado: 'anulada',
        marcas: 'TP-Link',
        page: 1,
        page_size: 50,
      }),
    );
    expect(lastParams(sellInAPI.resumen)).toEqual({ aplica: 'si', moneda: 'USD', estado: 'anulada', marcas: 'TP-Link' });
  });

  it('"Nuevo sell in" opens the create panel beside the list, never a modal', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    await user.click(screen.getByRole('button', { name: /Nuevo sell in/ }));
    const panel = screen.getByRole('complementary', { name: 'Nuevo sell in' });
    expect(within(panel).getByRole('heading', { name: 'Nuevo sell in · Por compra' })).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByText('Bonificación Q4 switches')).toBeInTheDocument();
  });

  it('"Detalle" opens the purchase in the side panel', async () => {
    const user = userEvent.setup();
    sellInAPI.detalle.mockResolvedValue({ data: LISTA.items[0] });
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    await user.click(screen.getAllByRole('button', { name: 'Detalle' })[0]);
    const panel = screen.getByRole('complementary', { name: 'Detalle del sell in' });
    expect(await within(panel).findByRole('heading', { name: 'Bonificación Q4 switches' })).toBeInTheDocument();
    expect(sellInAPI.detalle).toHaveBeenCalledWith(1);
  });

  it('offers "Nuevo sell in" only with sell_in.gestionar', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo === 'sell_in.ver');
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    expect(screen.queryByRole('button', { name: /Nuevo sell in/ })).not.toBeInTheDocument();
  });

  it('without sell_in.ver it says so and asks nothing', () => {
    mockTienePermiso.mockReturnValue(false);
    renderWithRouter(<SellIn />);
    expect(screen.getByText(/No tenés permiso para ver sell in/)).toBeInTheDocument();
    expect(sellInAPI.listar).not.toHaveBeenCalled();
  });

  it('shows the API message when the list fails', async () => {
    sellInAPI.listar.mockRejectedValue({ response: { status: 500, data: { detail: 'boom' } } });
    renderWithRouter(<SellIn />);
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudieron cargar los sell in.');
  });
});
