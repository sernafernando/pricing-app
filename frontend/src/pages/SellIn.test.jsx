import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useLocation } from 'react-router-dom';
import { renderWithRouter } from '../test/renderWithRouter';
import { productosAPI } from '../services/api';
import { sellInAPI, sellInBonosAPI } from '../services/sellInAPI';
import { ALCANCE, BONO, BONOS_LISTA, COMPRA_BONO, LISTA, RESUMEN } from '../components/sellIn/sellInFixtures';
import { sellOutAPI } from '../services/sellOutAPI';
import { CAMPANA_MIGRADA, CAMPANAS_LISTA, CONSUMOS_USD } from '../components/sellOut/sellOutFixtures';
import SellIn from './SellIn';

vi.mock('../services/sellInAPI', () => ({
  sellInAPI: {
    listar: vi.fn(),
    resumen: vi.fn(),
    detalle: vi.fn(),
    preview: vi.fn(),
    crear: vi.fn(),
    anular: vi.fn(),
    anularMasivo: vi.fn(),
  },
  sellInBonosAPI: {
    listar: vi.fn(),
    detalle: vi.fn(),
    alcance: vi.fn(),
    crear: vi.fn(),
    editar: vi.fn(),
    anular: vi.fn(),
    anularMasivo: vi.fn(),
  },
}));

vi.mock('../services/sellOutAPI', () => ({
  sellOutAPI: {
    listar: vi.fn(),
    detalle: vi.fn(),
    crear: vi.fn(),
    editar: vi.fn(),
    grupos: vi.fn(),
    consumos: vi.fn(),
    anularVarias: vi.fn(),
  },
}));

const mockTienePermiso = vi.fn();
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ permisos: [], tienePermiso: (codigo) => mockTienePermiso(codigo), cargandoPermisos: false }),
  PermisosProvider: ({ children }) => children,
}));

const lastParams = (fn) => fn.mock.calls[fn.mock.calls.length - 1][0];
// The bonus list's own requests, leaving out the active bonuses the summary cards ask for.
const listadosDeBonos = () => sellInBonosAPI.listar.mock.calls.filter(([params]) => params?.estado !== 'activa').length;

beforeEach(() => {
  vi.clearAllMocks();
  mockTienePermiso.mockReturnValue(true);
  sellInAPI.listar.mockResolvedValue({ data: LISTA });
  sellInAPI.resumen.mockResolvedValue({ data: RESUMEN });
  productosAPI.marcas.mockResolvedValue({ data: { marcas: ['Mercusys', 'TP-Link'] } });
  sellInBonosAPI.listar.mockResolvedValue({ data: BONOS_LISTA });
  sellInBonosAPI.detalle.mockResolvedValue({ data: BONO });
  sellInBonosAPI.alcance.mockResolvedValue({ data: ALCANCE });
  sellOutAPI.listar.mockResolvedValue({ data: CAMPANAS_LISTA });
  sellOutAPI.detalle.mockResolvedValue({ data: CAMPANA_MIGRADA });
  sellOutAPI.consumos.mockResolvedValue({ data: CONSUMOS_USD });
  sellOutAPI.grupos.mockResolvedValue({ data: [{ id: 1, nombre: 'TP-Link redes', descripcion: null, filtros: [] }] });
});

/** Prints where the router is, so a test can read the tab the URL keeps. */
function Ubicacion() {
  const { search } = useLocation();
  return <output data-testid="ubicacion">{search}</output>;
}

const bonosPorEstado = (params) =>
  params?.estado === 'activa' ? { data: { items: [BONO], total: 1, page: 1, page_size: 200 } } : { data: BONOS_LISTA };

describe('SellIn page — Sell in / Sell out tabs (Stitch 01 and 04)', () => {
  it('is one "Sell in / Sell out" page with both tabs counted, Sell in selected and no campaigns in it', async () => {
    renderWithRouter(<SellIn />);
    expect(screen.getByRole('heading', { name: 'Sell in / Sell out', level: 1 })).toBeInTheDocument();
    const tabs = screen.getByRole('tablist', { name: 'Sell in / Sell out' });
    expect(await within(tabs).findByRole('tab', { name: 'Sell in · 4' })).toHaveAttribute('aria-selected', 'true');
    expect(await within(tabs).findByRole('tab', { name: 'Sell out · 2' })).toHaveAttribute('aria-selected', 'false');
    const panel = screen.getByRole('tabpanel', { name: /Sell in/ });
    expect(await within(panel).findByText('Bonificación Q4 switches')).toBeInTheDocument();
    expect(within(panel).getByRole('region', { name: 'Bonos de marca' })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Campañas de sell out' })).not.toBeInTheDocument();
  });

  it('the Sell out tab shows the campaigns, hides the sell ins and keeps itself in the URL', async () => {
    const user = userEvent.setup();
    renderWithRouter(
      <>
        <SellIn />
        <Ubicacion />
      </>,
      { initialEntries: ['/sell-in'] },
    );
    await screen.findByText('Bonificación Q4 switches');
    await user.click(screen.getByRole('tab', { name: /Sell out/ }));
    expect(screen.getByRole('tab', { name: /Sell out/ })).toHaveAttribute('aria-selected', 'true');
    const panel = screen.getByRole('tabpanel', { name: /Sell out/ });
    expect(await within(panel).findByText('RB 8180')).toBeInTheDocument();
    expect(screen.queryByText('Bonificación Q4 switches')).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Bonos de marca' })).not.toBeInTheDocument();
    expect(screen.getByTestId('ubicacion')).toHaveTextContent('?tab=sell-out');
    await user.click(screen.getByRole('tab', { name: /Sell in/ }));
    expect(await screen.findByText('Bonificación Q4 switches')).toBeInTheDocument();
    expect(screen.getByTestId('ubicacion')).toHaveTextContent(/^$/);
  });

  it('opens on the Sell out tab when the URL says so (a reload keeps the tab)', async () => {
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    expect(screen.getByRole('tab', { name: /Sell out/ })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByText('RB 8180')).toBeInTheDocument();
  });

  it('without sell_out.ver there is no Sell out tab, and ?tab=sell-out falls back to Sell in', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'sell_out.ver');
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    expect(await screen.findByText('Bonificación Q4 switches')).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: /Sell out/ })).not.toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Sell in/ })).toHaveAttribute('aria-selected', 'true');
  });

  it('moves between tabs with the arrow keys, and only the selected tab is in the Tab order', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    const sellIn = screen.getByRole('tab', { name: /Sell in/ });
    expect(sellIn).toHaveAttribute('tabindex', '0');
    expect(sellIn).toHaveAttribute('aria-controls', 'sell-in-panel');
    expect(screen.getByRole('tab', { name: /Sell out/ })).toHaveAttribute('tabindex', '-1');
    expect(screen.getByRole('tab', { name: /Sell out/ })).not.toHaveAttribute('aria-controls');
    sellIn.focus();
    await user.keyboard('{ArrowRight}');
    const sellOut = screen.getByRole('tab', { name: /Sell out/ });
    expect(sellOut).toHaveAttribute('aria-selected', 'true');
    expect(sellOut).toHaveFocus();
    expect(await screen.findByText('RB 8180')).toBeInTheDocument();
    await user.keyboard('{ArrowLeft}');
    expect(screen.getByRole('tab', { name: /Sell in/ })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: /Sell in/ })).toHaveFocus();
  });

  it('the Tipo chips say what each count covers', async () => {
    renderWithRouter(<SellIn />);
    const chips = await screen.findByRole('group', { name: 'Tipo' });
    expect(await within(chips).findByRole('button', { name: 'Bono de marca · 2' })).toHaveAttribute(
      'title',
      'Todos los bonos de marca cargados: los filtros de arriba no los cuentan',
    );
    expect(within(chips).getByRole('button', { name: 'Por compra · 2' })).toHaveAttribute('title', 'Los sell in por compra con los filtros de arriba');
  });

  it('a tab whose list failed shows "—" instead of waiting forever', async () => {
    sellOutAPI.listar.mockRejectedValue(new Error('boom'));
    sellInAPI.resumen.mockRejectedValue(new Error('boom'));
    renderWithRouter(<SellIn />);
    expect(await screen.findByRole('tab', { name: 'Sell out · —' })).toBeInTheDocument();
    expect(await screen.findByRole('tab', { name: 'Sell in · —' })).toBeInTheDocument();
  });

  it('the header action follows the tab: "Nuevo sell in" on Sell in, "Nueva campaña" on Sell out', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    expect(screen.getByRole('button', { name: /Nuevo sell in/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Nueva campaña/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: /Sell out/ }));
    expect(screen.getByRole('button', { name: /Nueva campaña/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Nuevo sell in/ })).not.toBeInTheDocument();
  });

  it('the Tipo chips count purchases and brand bonuses and show one list or both', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    const chips = await screen.findByRole('group', { name: 'Tipo' });
    expect(await within(chips).findByRole('button', { name: 'Todos · 4' })).toHaveAttribute('aria-pressed', 'true');
    expect(within(chips).getByRole('button', { name: 'Por compra · 2' })).toBeInTheDocument();
    expect(within(chips).getByRole('button', { name: 'Bono de marca · 2' })).toBeInTheDocument();
    await screen.findByText('Bonificación Q4 switches');

    await user.click(within(chips).getByRole('button', { name: 'Bono de marca · 2' }));
    expect(screen.queryByText('Bonificación Q4 switches')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Bonos de marca' })).toBeInTheDocument();

    await user.click(within(chips).getByRole('button', { name: 'Por compra · 2' }));
    expect(screen.getByText('Bonificación Q4 switches')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Bonos de marca' })).not.toBeInTheDocument();
  });

  it('when the active bonuses cannot be read, their cards say so instead of disappearing', async () => {
    sellInBonosAPI.listar.mockImplementation(async (params) => {
      if (params?.estado === 'activa') throw new Error('boom');
      return { data: BONOS_LISTA };
    });
    renderWithRouter(<SellIn />);
    const cards = await screen.findByRole('region', { name: 'Resumen' });
    const vigentes = (await within(cards).findByText('Bonos de marca vigentes')).parentElement;
    expect(vigentes).toHaveTextContent('—');
    expect(vigentes).toHaveTextContent('No se pudieron cargar');
    expect(within(cards).getByText('Compras alcanzadas').parentElement).toHaveTextContent('—');
  });

  it('saving a brand bonus asks the active bonuses again, so its cards follow the list', async () => {
    const user = userEvent.setup();
    const vigentesPedidos = () => sellInBonosAPI.listar.mock.calls.filter(([params]) => params?.estado === 'activa').length;
    sellInBonosAPI.crear.mockResolvedValue({ data: BONO });
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    await waitFor(() => expect(vigentesPedidos()).toBe(1));
    await waitFor(() => expect(screen.getByRole('option', { name: 'TP-Link' })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /Nuevo sell in/ }));
    const panel = screen.getByRole('complementary', { name: 'Nuevo sell in' });
    await user.click(within(panel).getByRole('button', { name: 'Bono de marca' }));
    await user.selectOptions(within(panel).getByLabelText('Marca'), 'TP-Link');
    await user.type(within(panel).getByLabelText('Monto por unidad'), '3');
    await user.type(within(panel).getByLabelText('Factura desde'), '2026-09-01');
    await user.type(within(panel).getByLabelText('Factura hasta'), '2026-11-30');
    await user.click(within(panel).getByRole('button', { name: 'Guardar bono' }));
    await waitFor(() => expect(vigentesPedidos()).toBe(2));
  });

  it('the summary adds the active brand bonuses, their brands and the purchases they reached', async () => {
    sellInBonosAPI.listar.mockImplementation(async (params) => bonosPorEstado(params));
    renderWithRouter(<SellIn />);
    const cards = await screen.findByRole('region', { name: 'Resumen' });
    await waitFor(() => expect(sellInBonosAPI.listar).toHaveBeenCalledWith({ estado: 'activa', page: 1, page_size: 200 }));
    const vigentes = (await within(cards).findByText('Bonos de marca vigentes')).parentElement;
    expect(vigentes).toHaveTextContent('1');
    expect(vigentes).toHaveTextContent('1 marca');
    const alcanzadas = within(cards).getByText('Compras alcanzadas').parentElement;
    expect(alcanzadas).toHaveTextContent('18');
    expect(alcanzadas).toHaveTextContent('por bonos de marca');
  });
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
    // The chips render with 0 before resumen answers: wait for its counts.
    expect(await within(chips).findByRole('button', { name: 'Aplican · 3' })).toHaveAttribute('aria-pressed', 'true');
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

describe('SellIn page — brand bonuses', () => {
  it('"Actualizar" reloads the brand bonuses too', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    await screen.findByRole('region', { name: 'Bonos de marca' });
    await waitFor(() => expect(listadosDeBonos()).toBe(1));
    await user.click(screen.getByRole('button', { name: /Actualizar/ }));
    await waitFor(() => expect(listadosDeBonos()).toBe(2));
  });

  it('lists the brand bonuses with what they generated, and opens one in the side panel', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    const bonos = await screen.findByRole('region', { name: 'Bonos de marca' });
    const fila = (await within(bonos).findByText('Bono TP-Link USD 3/u')).closest('tr');
    expect(sellInBonosAPI.listar).toHaveBeenCalledWith({ page: 1, page_size: 10 });
    expect(within(fila).getByText('Marca TP-LINK')).toBeInTheDocument();
    expect(within(fila).getByText('USD 3,00 / u')).toBeInTheDocument();
    expect(within(fila).getByText('18 compras · 1.040 u')).toBeInTheDocument();
    expect(within(fila).getByText('Activo')).toBeInTheDocument();
    await user.click(within(fila).getByRole('button', { name: 'Ver bono' }));
    const panel = screen.getByRole('complementary', { name: 'Bono de marca' });
    expect(await within(panel).findByRole('heading', { name: 'Bono TP-Link USD 3/u' })).toBeInTheDocument();
    expect(sellInBonosAPI.detalle).toHaveBeenCalledWith(3);
  });

  it('marks a purchase generated by a bonus and links to that bonus', async () => {
    const user = userEvent.setup();
    sellInAPI.listar.mockResolvedValue({ data: { ...LISTA, items: [COMPRA_BONO], total: 1 } });
    renderWithRouter(<SellIn />);
    const fila = (await screen.findByText('Bono de marca TP-LINK (bono 3)')).closest('tr');
    expect(within(fila).getByText('Bono de marca')).toBeInTheDocument();
    await user.click(within(fila).getByRole('button', { name: 'Ver bono #3' }));
    expect(screen.getByRole('complementary', { name: 'Bono de marca' })).toBeInTheDocument();
    await waitFor(() => expect(sellInBonosAPI.detalle).toHaveBeenCalledWith(3));
  });

  it('a bonus created from the switch opens in the panel and the bonus list reloads', async () => {
    const user = userEvent.setup();
    sellInBonosAPI.crear.mockResolvedValue({ data: BONO });
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    await waitFor(() => expect(screen.getByRole('option', { name: 'TP-Link' })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /Nuevo sell in/ }));
    const panel = screen.getByRole('complementary', { name: 'Nuevo sell in' });
    await user.click(within(panel).getByRole('button', { name: 'Bono de marca' }));
    await user.selectOptions(within(panel).getByLabelText('Marca'), 'TP-Link');
    await user.type(within(panel).getByLabelText('Monto por unidad'), '3');
    await user.type(within(panel).getByLabelText('Factura desde'), '2026-09-01');
    await user.type(within(panel).getByLabelText('Factura hasta'), '2026-11-30');
    await user.click(within(panel).getByRole('button', { name: 'Guardar bono' }));
    expect(await screen.findByRole('complementary', { name: 'Bono de marca' })).toBeInTheDocument();
    await waitFor(() => expect(listadosDeBonos()).toBe(2));
  });
});

describe('SellIn page — purchases generated by a brand bonus', () => {
  it('leaves manual purchases without the badge', async () => {
    renderWithRouter(<SellIn />);
    const fila = (await screen.findByText('Bonificación Q4 switches')).closest('tr');
    expect(within(fila).queryByText('Bono de marca')).not.toBeInTheDocument();
  });
});

describe('SellIn page — sell-out campaigns (T8)', () => {
  it('lists the campaigns with their benefit, validity, credit and state', async () => {
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    const seccion = await screen.findByRole('region', { name: 'Campañas de sell out' });
    const fila = (await within(seccion).findByText('RB 8180')).closest('tr');
    expect(fila).toHaveTextContent('USD 36,00 por unidad');
    expect(fila).toHaveTextContent('01/01/2026 – 31/12/2026');
    expect(fila).toHaveTextContent('30 u');
    expect(fila).toHaveTextContent('Activa');
    expect(within(seccion).getByText('TP-Link 2% noviembre').closest('tr')).toHaveTextContent('Anulada');
    expect(lastParams(sellOutAPI.listar)).toEqual({ page: 1, page_size: 10 });
  });

  it('searches the campaigns by name and goes back to page 1', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    const seccion = await screen.findByRole('region', { name: 'Campañas de sell out' });
    await user.type(within(seccion).getByPlaceholderText('Buscar campaña por nombre…'), 'RB');
    await waitFor(() => expect(lastParams(sellOutAPI.listar)).toEqual({ q: 'RB', page: 1, page_size: 10 }));
  });

  it('"Ver campaña" opens it in the side panel', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    const seccion = await screen.findByRole('region', { name: 'Campañas de sell out' });
    const fila = (await within(seccion).findByText('RB 8180')).closest('tr');
    await user.click(within(fila).getByRole('button', { name: 'Ver campaña' }));
    expect(await screen.findByRole('heading', { name: 'RB 8180', level: 2 })).toBeInTheDocument();
    expect(sellOutAPI.detalle).toHaveBeenCalledWith(55);
  });

  it('a bulk void of the campaign open in the side panel reads it again, so the panel shows it voided', async () => {
    const user = userEvent.setup();
    sellOutAPI.anularVarias.mockResolvedValue({ data: { anuladas: [55], omitidas: [] } });
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    const seccion = await screen.findByRole('region', { name: 'Campañas de sell out' });
    const fila = (await within(seccion).findByText('RB 8180')).closest('tr');
    await user.click(within(fila).getByRole('button', { name: 'Ver campaña' }));
    await screen.findByRole('heading', { name: 'RB 8180', level: 2 });
    expect(sellOutAPI.detalle).toHaveBeenCalledTimes(1);

    sellOutAPI.detalle.mockResolvedValue({ data: { ...CAMPANA_MIGRADA, estado: 'anulada' } });
    await user.click(within(fila).getByRole('checkbox', { name: 'Seleccionar RB 8180' }));
    await user.click(within(seccion).getByRole('button', { name: 'Anular seleccionados' }));
    await user.click(within(seccion).getByRole('button', { name: 'Confirmar anulación' }));

    await waitFor(() => expect(sellOutAPI.detalle).toHaveBeenCalledTimes(2));
    expect(sellOutAPI.detalle).toHaveBeenLastCalledWith(55);
  });

  it('a bulk void that answers after the panel was closed does not reopen it', async () => {
    const user = userEvent.setup();
    let responder;
    sellOutAPI.anularVarias.mockReturnValue(new Promise((resolve) => (responder = resolve)));
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    const seccion = await screen.findByRole('region', { name: 'Campañas de sell out' });
    const fila = (await within(seccion).findByText('RB 8180')).closest('tr');
    await user.click(within(fila).getByRole('button', { name: 'Ver campaña' }));
    await screen.findByRole('heading', { name: 'RB 8180', level: 2 });
    await user.click(within(fila).getByRole('checkbox', { name: 'Seleccionar RB 8180' }));
    await user.click(within(seccion).getByRole('button', { name: 'Anular seleccionados' }));
    await user.click(within(seccion).getByRole('button', { name: 'Confirmar anulación' }));

    await user.click(screen.getByRole('button', { name: 'Cerrar' })); // while the bulk void is in flight
    expect(screen.queryByRole('heading', { name: 'RB 8180', level: 2 })).not.toBeInTheDocument();
    responder({ data: { anuladas: [55], omitidas: [] } });

    await waitFor(() => expect(sellOutAPI.listar).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole('heading', { name: 'RB 8180', level: 2 })).not.toBeInTheDocument();
  });

  it('a bulk void that answers after a new search reloads the current search, not the old one', async () => {
    const user = userEvent.setup();
    let responder;
    sellOutAPI.anularVarias.mockReturnValue(new Promise((resolve) => (responder = resolve)));
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    const seccion = await screen.findByRole('region', { name: 'Campañas de sell out' });
    const fila = (await within(seccion).findByText('RB 8180')).closest('tr');
    await user.click(within(fila).getByRole('checkbox', { name: 'Seleccionar RB 8180' }));
    await user.click(within(seccion).getByRole('button', { name: 'Anular seleccionados' }));
    await user.click(within(seccion).getByRole('button', { name: 'Confirmar anulación' }));

    await user.type(screen.getByPlaceholderText('Buscar campaña por nombre…'), 'Epson'); // while it is in flight
    await waitFor(() => expect(sellOutAPI.listar).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'Epson' })));
    const antes = sellOutAPI.listar.mock.calls.length;
    responder({ data: { anuladas: [55], omitidas: [] } });

    await waitFor(() => expect(sellOutAPI.listar.mock.calls.length).toBeGreaterThan(antes));
    expect(sellOutAPI.listar).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'Epson' }));
  });

  it('"Actualizar" reloads the campaigns too', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    await screen.findByRole('region', { name: 'Campañas de sell out' });
    await waitFor(() => expect(sellOutAPI.listar).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole('button', { name: /Actualizar/ }));
    await waitFor(() => expect(sellOutAPI.listar).toHaveBeenCalledTimes(2));
  });

  it('"Nueva campaña" opens the form with the offset groups; saving shows the new campaign and reloads the list', async () => {
    const user = userEvent.setup();
    sellOutAPI.crear.mockResolvedValue({ data: { ...CAMPANA_MIGRADA, id: 95, nombre: 'Epson diciembre' } });
    sellOutAPI.detalle.mockResolvedValue({ data: { ...CAMPANA_MIGRADA, id: 95, nombre: 'Epson diciembre' } });
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    await screen.findByRole('region', { name: 'Campañas de sell out' });
    await waitFor(() => expect(sellOutAPI.listar).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole('button', { name: /Nueva campaña/ }));

    expect(await screen.findByRole('heading', { name: 'Nueva campaña de sell out' })).toBeInTheDocument();
    await user.type(screen.getByLabelText('Nombre'), 'Epson diciembre');
    await user.type(screen.getByLabelText('Monto por unidad'), '12');
    await user.type(screen.getByLabelText('Desde'), '2026-12-01');
    await user.type(screen.getByLabelText('Hasta'), '2026-12-31');
    await user.click(await screen.findByRole('checkbox', { name: 'TP-Link redes' }));
    await user.click(screen.getByRole('button', { name: 'Guardar campaña' }));

    expect(await screen.findByRole('heading', { name: 'Epson diciembre', level: 2 })).toBeInTheDocument();
    expect(sellOutAPI.detalle).toHaveBeenCalledWith(95);
    await waitFor(() => expect(sellOutAPI.listar).toHaveBeenCalledTimes(2));
  });

  it('without sell_out.gestionar there is no "Nueva campaña" and the groups are not asked', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'sell_out.gestionar');
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    const seccion = await screen.findByRole('region', { name: 'Campañas de sell out' });
    await within(seccion).findByText('RB 8180');
    expect(screen.queryByRole('button', { name: /Nueva campaña/ })).not.toBeInTheDocument();
    expect(sellOutAPI.grupos).not.toHaveBeenCalled();
  });

  it('without sell_out.ver the section is not shown and nothing is asked', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'sell_out.ver');
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=sell-out'] });
    expect(await screen.findByText('Bonificación Q4 switches')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Campañas de sell out' })).not.toBeInTheDocument();
    expect(sellOutAPI.listar).not.toHaveBeenCalled();
  });
});

describe('SellIn page — bulk void (anular masivo)', () => {
  it('voids the selected purchases after confirming, then reloads the list and says what happened', async () => {
    const user = userEvent.setup();
    sellInAPI.anularMasivo.mockResolvedValue({ data: { anuladas: [1], ya_anuladas: [2] } });
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    const listados = sellInAPI.listar.mock.calls.length;

    await user.click(screen.getByRole('checkbox', { name: 'Seleccionar la página de sell in' }));
    expect(screen.getByRole('checkbox', { name: 'Seleccionar compra #1' })).toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Anular seleccionados' }));
    const pane = screen.getByRole('dialog', { name: 'Anular 2 compras' });
    expect(pane).toHaveTextContent('Se liberan sus unidades');
    await user.click(within(pane).getByRole('button', { name: 'Sí, anular 2' }));

    expect(sellInAPI.anularMasivo).toHaveBeenCalledWith([1, 2], '');
    expect(await screen.findByRole('status')).toHaveTextContent('Se anuló 1 compra. 1 ya estaba anulada.');
    expect(sellInAPI.listar.mock.calls.length).toBeGreaterThan(listados);
    expect(screen.getByRole('checkbox', { name: 'Seleccionar compra #1' })).not.toBeChecked();
  });

  it('goes back to page 1 after a bulk void: what it voided leaves the list, so the page it was on may no longer exist', async () => {
    const user = userEvent.setup();
    sellInAPI.listar.mockResolvedValue({ data: { ...LISTA, total: 500 } });
    sellInAPI.anularMasivo.mockResolvedValue({ data: { anuladas: [1, 2], ya_anuladas: [] } });
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    await user.click(screen.getAllByRole('button', { name: 'Página 2' })[0]);
    await waitFor(() => expect(lastParams(sellInAPI.listar)).toEqual(expect.objectContaining({ page: 2 })));

    await user.click(screen.getByRole('checkbox', { name: 'Seleccionar la página de sell in' }));
    await user.click(screen.getByRole('button', { name: 'Anular seleccionados' }));
    await user.click(screen.getByRole('button', { name: 'Sí, anular 2' }));

    await waitFor(() => expect(lastParams(sellInAPI.listar)).toEqual(expect.objectContaining({ page: 1 })));
  });

  it('reloads with the page on screen when the void ends, not the one it started on', async () => {
    const user = userEvent.setup();
    let soltar;
    sellInAPI.listar.mockResolvedValue({ data: { ...LISTA, total: 500 } });
    sellInAPI.anularMasivo.mockImplementation(() => new Promise((resolve) => (soltar = () => resolve({ data: { anuladas: [1, 2], ya_anuladas: [] } }))));
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    await user.click(screen.getAllByRole('button', { name: 'Página 2' })[0]);
    await waitFor(() => expect(lastParams(sellInAPI.listar)).toEqual(expect.objectContaining({ page: 2 })));
    await user.click(screen.getByRole('checkbox', { name: 'Seleccionar la página de sell in' }));
    await user.click(screen.getByRole('button', { name: 'Anular seleccionados' }));
    await user.click(screen.getByRole('button', { name: 'Sí, anular 2' }));

    await user.click(screen.getAllByRole('button', { name: 'Página 1' })[0]);
    await waitFor(() => expect(lastParams(sellInAPI.listar)).toEqual(expect.objectContaining({ page: 1 })));
    const listados = sellInAPI.listar.mock.calls.length;
    soltar();

    await screen.findByRole('status');
    await waitFor(() => expect(sellInAPI.listar.mock.calls.length).toBeGreaterThan(listados));
    expect(lastParams(sellInAPI.listar)).toEqual(expect.objectContaining({ page: 1 }));
  });

  it('the bonus list also goes back to page 1 after a bulk void', async () => {
    const user = userEvent.setup();
    sellInBonosAPI.listar.mockResolvedValue({ data: { ...BONOS_LISTA, total: 500 } });
    sellInBonosAPI.anularMasivo.mockResolvedValue({ data: { anuladas: [BONO.id], ya_anuladas: [] } });
    // The list's own reads, not the active-bonus ones the purchase form takes (`estado: 'activa'`).
    const paginaDeLaLista = () => sellInBonosAPI.listar.mock.calls.map(([p]) => p).filter((p) => !p?.estado).at(-1)?.page;
    renderWithRouter(<SellIn />);
    const bonos = await screen.findByRole('region', { name: 'Bonos de marca' });
    await user.click(await within(bonos).findByRole('button', { name: 'Página 2' }));
    await waitFor(() => expect(paginaDeLaLista()).toBe(2));

    await user.click(within(bonos).getByRole('checkbox', { name: `Seleccionar bono #${BONO.id}` }));
    await user.click(within(bonos).getByRole('button', { name: 'Anular seleccionados' }));
    await user.click(within(bonos).getByRole('button', { name: 'Sí, anular 1' }));

    await screen.findByRole('status');
    await waitFor(() => expect(paginaDeLaLista()).toBe(1));
  });

  it('"Seleccionar todo lo filtrado" asks every page with the filters on screen', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');

    await user.click(screen.getAllByRole('button', { name: 'Seleccionar todo lo filtrado (2)' })[0]);

    expect(lastParams(sellInAPI.listar)).toEqual(expect.objectContaining({ aplica: 'si', page: 1, page_size: 200 }));
    expect(await screen.findByText('2 seleccionados')).toBeInTheDocument();
  });

  it('voids the selected brand bonuses through their own bulk endpoint', async () => {
    const user = userEvent.setup();
    sellInBonosAPI.anularMasivo.mockResolvedValue({ data: { anuladas: [BONO.id], ya_anuladas: [] } });
    renderWithRouter(<SellIn />);
    await user.click(await screen.findByRole('checkbox', { name: `Seleccionar bono #${BONO.id}` }));
    const bonos = screen.getByRole('region', { name: 'Bonos de marca' });
    await user.click(within(bonos).getByRole('button', { name: 'Anular seleccionados' }));
    await user.click(within(bonos).getByRole('button', { name: 'Sí, anular 1' }));

    expect(sellInBonosAPI.anularMasivo).toHaveBeenCalledWith([BONO.id], '');
    expect(await screen.findByRole('status')).toHaveTextContent('Se anuló 1 bono.');
  });

  it('without sell_in.gestionar there is nothing to select', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo === 'sell_in.ver');
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    expect(screen.queryByRole('checkbox', { name: /Seleccionar/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Seleccionar todo lo filtrado/ })).not.toBeInTheDocument();
  });

  it('says what happened even when only the bonus list is shown', async () => {
    const user = userEvent.setup();
    sellInBonosAPI.anularMasivo.mockResolvedValue({ data: { anuladas: [BONO.id], ya_anuladas: [] } });
    renderWithRouter(<SellIn />);
    const chips = await screen.findByRole('group', { name: 'Tipo' });
    await user.click(await within(chips).findByRole('button', { name: 'Bono de marca · 2' }));
    await user.click(screen.getByRole('checkbox', { name: `Seleccionar bono #${BONO.id}` }));
    await user.click(screen.getByRole('button', { name: 'Anular seleccionados' }));
    await user.click(screen.getByRole('button', { name: 'Sí, anular 1' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Se anuló 1 bono.');
  });

  it('drops "todo lo filtrado" when the filters changed while it was read', async () => {
    const user = userEvent.setup();
    let soltar;
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    sellInAPI.listar.mockImplementationOnce(() => new Promise((resolve) => (soltar = () => resolve({ data: LISTA }))));
    await user.click(screen.getAllByRole('button', { name: 'Seleccionar todo lo filtrado (2)' })[0]);
    await user.click(screen.getByRole('button', { name: /No aplican/ }));
    soltar();

    expect(await screen.findByRole('alert')).toHaveTextContent('Los filtros cambiaron mientras se seleccionaba. Volvé a intentarlo.');
    expect(screen.queryByText('2 seleccionados')).not.toBeInTheDocument();
  });

  it('closes the side panel of a purchase it voided, and the notice goes away on the next selection', async () => {
    const user = userEvent.setup();
    sellInAPI.detalle.mockResolvedValue({ data: LISTA.items[0] });
    sellInAPI.anularMasivo.mockResolvedValue({ data: { anuladas: [1], ya_anuladas: [] } });
    renderWithRouter(<SellIn />);
    await screen.findByText('Bonificación Q4 switches');
    await user.click(screen.getAllByRole('button', { name: 'Detalle' })[0]);
    expect(screen.getByRole('complementary', { name: 'Detalle del sell in' })).toBeInTheDocument();

    await user.click(screen.getByRole('checkbox', { name: 'Seleccionar compra #1' }));
    await user.click(screen.getByRole('button', { name: 'Anular seleccionados' }));
    await user.click(screen.getByRole('button', { name: 'Sí, anular 1' }));

    expect(await screen.findByRole('status')).toHaveTextContent('Se anuló 1 compra.');
    expect(screen.queryByRole('complementary', { name: 'Detalle del sell in' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('checkbox', { name: 'Seleccionar compra #2' }));
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });
});
