/**
 * Sell in / Sell out, one view (owner, 2026-11-05: "trae todo a tacticals"; handoffs/tacticals-vista-unica-tarea.md):
 * Tacticals, Programas and Grupos tabs. The old Sell in / Sell out tabs' links land on Tacticals with that Tipo.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation, useSearchParams } from 'react-router-dom';
import { renderWithRouter } from '../test/renderWithRouter';
import { productosAPI } from '../services/api';
import { sellInAPI, sellInBonosAPI, sellInLotesAPI } from '../services/sellInAPI';
import { ALCANCE, BONO } from '../components/sellIn/sellInFixtures';
import { sellOutAPI, sellOutProgramasAPI } from '../services/sellOutAPI';
import { offsetGruposAPI } from '../services/offsetGruposAPI';
import { tacticalsAPI } from '../services/tacticalsAPI';
import { TACTICAL_REBATE, TACTICAL_BPS, pagina } from '../components/tacticals/tacticalsFixtures';
import { CAMPANA_MIGRADA, CONSUMOS_USD, PROGRAMAS_LISTA, PROGRAMAS_VACIO, SUGERENCIAS, SUGERENCIAS_VACIO } from '../components/sellOut/sellOutFixtures';
import SellIn from './SellIn';

const TACTICAL = { ...TACTICAL_REBATE, id: 7, nombre: 'Rebate TP-Link noviembre', marca: 'TP-Link' };

function NuevoTacticalProbe() {
  const [params] = useSearchParams();
  const renovar = params.get('renovar');
  return <p>{`Nuevo tactical: ${params.get('tipo')}${renovar ? ` renovando ${renovar}` : ''}`}</p>;
}

/** SellIn with the Nuevo tactical route next to it, so a button that goes there shows where it went. */
function renderConNuevoTactical(entrada) {
  return render(
    <MemoryRouter initialEntries={[entrada]}>
      <Routes>
        <Route path="/sell-in" element={<SellIn />} />
        <Route path="/sell-in/tactical/nuevo" element={<NuevoTacticalProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

vi.mock('../services/sellInAPI', () => ({
  sellInAPI: { listar: vi.fn(), resumen: vi.fn(), detalle: vi.fn() },
  sellInBonosAPI: { listar: vi.fn(), detalle: vi.fn(), alcance: vi.fn() },
  sellInLotesAPI: { productos: vi.fn(), lotes: vi.fn(), consumos: vi.fn(), modos: vi.fn(), modoPorDefecto: vi.fn() },
}));

vi.mock('../services/sellOutAPI', () => ({
  sellOutAPI: { listar: vi.fn(), detalle: vi.fn(), grupos: vi.fn(), consumos: vi.fn() },
  sellOutProgramasAPI: { listar: vi.fn(), crear: vi.fn(), asignar: vi.fn(), sugerencias: vi.fn() },
}));

vi.mock('../services/tacticalsAPI', () => ({ tacticalsAPI: { listar: vi.fn(), anular: vi.fn() } }));

vi.mock('../services/offsetGruposAPI', () => ({
  offsetGruposAPI: { listar: vi.fn(), alcance: vi.fn(), opciones: vi.fn(), crear: vi.fn() },
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
  productosAPI.marcas.mockResolvedValue({ data: { marcas: ['Mercusys', 'TP-Link'] } });
  sellInBonosAPI.detalle.mockResolvedValue({ data: BONO });
  sellInBonosAPI.alcance.mockResolvedValue({ data: ALCANCE });
  sellOutAPI.detalle.mockResolvedValue({ data: CAMPANA_MIGRADA });
  sellOutAPI.consumos.mockResolvedValue({ data: CONSUMOS_USD });
  sellOutProgramasAPI.listar.mockResolvedValue({ data: PROGRAMAS_VACIO });
  sellInLotesAPI.productos.mockResolvedValue({ data: { productos: [] } });
  sellOutProgramasAPI.sugerencias.mockResolvedValue({ data: SUGERENCIAS_VACIO });
  offsetGruposAPI.listar.mockResolvedValue({ data: [{ id: 1, nombre: 'TP-Link redes', descripcion: null, filtros: [] }] });
  offsetGruposAPI.alcance.mockResolvedValue({ data: [{ grupo_id: 1, productos: 3, campanas: [] }] });
  offsetGruposAPI.opciones.mockResolvedValue({ data: { marcas: [], categorias: [], subcategorias: [] } });
  tacticalsAPI.listar.mockResolvedValue({ data: pagina([TACTICAL]) });
});

/** Prints where the router is, so a test can read the tab the URL keeps. */
function Ubicacion() {
  const { search } = useLocation();
  return <output data-testid="ubicacion">{search}</output>;
}

describe('SellIn page — one view: Tacticals, Programas and Grupos', () => {
  it('has no Sell in or Sell out tab, and asks no purchase, bonus or campaign list', async () => {
    renderWithRouter(<SellIn />);
    await screen.findByText('Rebate TP-Link noviembre');

    expect(screen.getAllByRole('tab').map((t) => t.textContent.replace(/\s+/g, ' ').trim())).toEqual(['Tacticals · 1', 'Programas', 'Grupos', 'Productos']);
    expect(sellInAPI.listar).not.toHaveBeenCalled();
    expect(sellInAPI.resumen).not.toHaveBeenCalled();
    expect(sellInBonosAPI.listar).not.toHaveBeenCalled();
    expect(sellOutAPI.listar).not.toHaveBeenCalled();
  });

  it.each([
    ['/sell-in?tab=sell-in', 'Sell in'],
    ['/sell-in?tab=sell-out', 'Sell out'],
  ])('an old %s link opens Tacticals with Tipo %s, and the URL drops the old tab', async (entrada, tipo) => {
    renderWithRouter(
      <>
        <SellIn />
        <Ubicacion />
      </>,
      { initialEntries: [entrada] },
    );

    expect(await screen.findByRole('tab', { name: /Tacticals/ })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByRole('button', { name: tipo })).toHaveAttribute('aria-pressed', 'true');
    const listados = () => tacticalsAPI.listar.mock.calls.map(([params]) => params).filter((params) => params.page_size !== 1);
    await waitFor(() => expect(listados().at(-1)).toMatchObject({ tipo: tipo === 'Sell in' ? 'sell_in' : 'sell_out' }));
    await waitFor(() => expect(screen.getByTestId('ubicacion')).toHaveTextContent(/^$/));
  });

  it('an old Sell out link to its Programas section opens the Programas tab', async () => {
    renderWithRouter(
      <>
        <SellIn />
        <Ubicacion />
      </>,
      { initialEntries: ['/sell-in?tab=sell-out&seccion=programas'] },
    );

    expect(await screen.findByRole('tab', { name: 'Programas' })).toHaveAttribute('aria-selected', 'true');
    await waitFor(() => expect(screen.getByTestId('ubicacion')).toHaveTextContent('?tab=programas'));
  });

  it('the Programas tab lists the programs, keeps itself in the URL, and needs sell_out.ver', async () => {
    const user = userEvent.setup();
    sellOutProgramasAPI.listar.mockResolvedValue({ data: PROGRAMAS_LISTA });
    const { unmount } = renderWithRouter(
      <>
        <SellIn />
        <Ubicacion />
      </>,
    );
    await user.click(await screen.findByRole('tab', { name: 'Programas' }));

    const panel = screen.getByRole('tabpanel', { name: 'Programas' });
    expect(within(panel).getByRole('heading', { name: 'Programas' })).toBeInTheDocument();
    expect(await within(panel).findByText(PROGRAMAS_LISTA.items[0].nombre)).toBeInTheDocument();
    expect(screen.getByTestId('ubicacion')).toHaveTextContent('?tab=programas');
    unmount();

    vi.clearAllMocks();
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'sell_out.ver');
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=programas'] });
    expect(await screen.findByRole('tab', { name: /Tacticals/ })).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByRole('tab', { name: 'Programas' })).not.toBeInTheDocument();
    expect(sellOutProgramasAPI.listar).not.toHaveBeenCalled();
  });

  it('the arrow keys move between the tabs', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />);
    (await screen.findByRole('tab', { name: /Tacticals/ })).focus();

    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Programas' })).toHaveFocus();
    await user.keyboard('{End}');
    expect(screen.getByRole('tab', { name: 'Productos' })).toHaveAttribute('aria-selected', 'true');
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: /Tacticals/ })).toHaveFocus();
  });

  it('"Nuevo tactical" shows on Tacticals only and opens Nuevo tactical', async () => {
    const user = userEvent.setup();
    renderConNuevoTactical('/sell-in?tab=grupos');
    await screen.findByRole('tabpanel', { name: 'Grupos' });
    expect(screen.queryByRole('button', { name: /Nuevo tactical/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: /Tacticals/ }));
    await user.click(await screen.findByRole('button', { name: /Nuevo tactical/ }));
    expect(await screen.findByText('Nuevo tactical: null')).toBeInTheDocument();
  });

  it('offers "Nuevo tactical" with either gestionar permission, and not without one', async () => {
    mockTienePermiso.mockImplementation((codigo) => ['sell_in.ver', 'sell_out.gestionar'].includes(codigo));
    const { unmount } = renderWithRouter(<SellIn />);
    expect(await screen.findByRole('button', { name: /Nuevo tactical/ })).toBeInTheDocument();
    unmount();
    mockTienePermiso.mockImplementation((codigo) => ['sell_in.ver', 'sell_out.ver'].includes(codigo));
    renderWithRouter(<SellIn />);
    await screen.findByRole('tabpanel', { name: /Tacticals/ });
    expect(screen.queryByRole('button', { name: /Nuevo tactical/ })).not.toBeInTheDocument();
  });

  it('shows once what Nuevo tactical created when it comes back', async () => {
    render(
      <MemoryRouter initialEntries={[{ pathname: '/sell-in', search: '?tab=tacticals', state: { aviso: 'Tactical creado: Rebate' } }]}>
        <Routes>
          <Route path="/sell-in" element={<SellIn />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText('Tactical creado: Rebate')).toBeInTheDocument();
  });

  it("Ver ventas on a sell out line opens its campaign with the sales it credited, read only", async () => {
    const user = userEvent.setup();
    tacticalsAPI.listar.mockResolvedValue({ data: pagina([TACTICAL_BPS]) });
    renderWithRouter(<SellIn />);
    await user.click(await screen.findByRole('button', { name: `Ver las líneas de ${TACTICAL_BPS.nombre}` }));
    await user.click(screen.getByRole('button', { name: 'Ver ventas de la línea 3' }));

    const panel = await screen.findByRole('complementary', { name: 'Campaña de sell out' });
    expect(await within(panel).findByRole('heading', { name: CAMPANA_MIGRADA.nombre })).toBeInTheDocument();
    expect(sellOutAPI.detalle).toHaveBeenCalledWith(TACTICAL_BPS.lineas[2].id);
    await waitFor(() => expect(sellOutAPI.consumos).toHaveBeenCalled());
    expect(within(panel).queryByRole('button', { name: /Anular campaña|Guardar|Renovar/ })).not.toBeInTheDocument();
  });

  it('without sell_in.ver it says so and asks nothing', () => {
    mockTienePermiso.mockReturnValue(false);
    renderWithRouter(<SellIn />);
    expect(screen.getByText('No tenés permiso para ver sell in.')).toBeInTheDocument();
    expect(tacticalsAPI.listar).not.toHaveBeenCalled();
  });
});

describe('SellIn page — Grupos tab (T30)', () => {
  it('with grupos.ver a Grupos tab lists the groups and keeps itself in the URL', async () => {
    const user = userEvent.setup();
    renderWithRouter(
      <>
        <SellIn />
        <Ubicacion />
      </>,
    );
    await screen.findByText('Rebate TP-Link noviembre');
    expect(offsetGruposAPI.listar).not.toHaveBeenCalled();
    await user.click(screen.getByRole('tab', { name: 'Grupos' }));
    expect(screen.getByRole('tab', { name: 'Grupos' })).toHaveAttribute('aria-selected', 'true');
    const panel = screen.getByRole('tabpanel', { name: 'Grupos' });
    expect(await within(panel).findByText('TP-Link redes')).toBeInTheDocument();
    expect(screen.queryByText('Rebate TP-Link noviembre')).not.toBeInTheDocument();
    expect(screen.getByTestId('ubicacion')).toHaveTextContent('?tab=grupos');
  });

  it('"Actualizar" on the Grupos tab reloads the groups too', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=grupos'] });
    expect(await screen.findByText('TP-Link redes')).toBeInTheDocument();
    expect(offsetGruposAPI.listar).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole('button', { name: /Actualizar/ }));
    await waitFor(() => expect(offsetGruposAPI.listar).toHaveBeenCalledTimes(2));
    expect(offsetGruposAPI.alcance).toHaveBeenCalledTimes(2);
  });

  // Owner (tactical S9): "hoy no existe un permiso para que se vean los grupos, así que solo yo los veo"; on #2083:
  // "sí, sacalo y dejala solo con grupos.ver" (config.editar_constantes alone no longer shows the tab).
  it('without grupos.ver there is no Grupos tab, even with config.editar_constantes, and ?tab=grupos falls back to Tacticals', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'grupos.ver');
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=grupos'] });
    expect(await screen.findByText('Rebate TP-Link noviembre')).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Grupos' })).not.toBeInTheDocument();
    expect(offsetGruposAPI.listar).not.toHaveBeenCalled();
  });

  it('with grupos.ver alone the Grupos tab only reads: no Nuevo grupo, no Editar, nothing to check', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'config.editar_constantes');
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=grupos'] });
    const panel = await screen.findByRole('tabpanel', { name: 'Grupos' });
    expect(await within(panel).findByText('TP-Link redes')).toBeInTheDocument();
    expect(within(panel).queryByRole('button', { name: /Nuevo grupo/ })).not.toBeInTheDocument();
    expect(within(panel).queryByRole('button', { name: 'Editar' })).not.toBeInTheDocument();
    expect(within(panel).queryByRole('checkbox')).not.toBeInTheDocument();
  });
});


describe('SellIn page — Programas tab: suggestions (campanas-sistema slice E)', () => {
  const BANNER = '2 sugerencias de programa: campañas sin programa con las mismas fechas';
  const tarjeta = (desde, hasta) => screen.getByRole('group', { name: `Sugerencia del ${desde} al ${hasta}` });

  it('the banner shows with sell_out.gestionar and suggestions, and not without either', async () => {
    sellOutProgramasAPI.sugerencias.mockResolvedValue({ data: SUGERENCIAS });
    const { unmount } = renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=programas'] });
    expect(await screen.findByText(BANNER)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ver sugerencias' })).toBeInTheDocument();
    expect(lastParams(sellOutProgramasAPI.sugerencias)).toEqual({ page: 1, page_size: 200 });
    unmount();

    vi.clearAllMocks();
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'sell_out.gestionar');
    const lector = renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=programas'] });
    await screen.findByRole('heading', { name: 'Programas' });
    expect(screen.queryByText(BANNER)).not.toBeInTheDocument();
    expect(sellOutProgramasAPI.sugerencias).not.toHaveBeenCalled();
    lector.unmount();

    mockTienePermiso.mockReturnValue(true);
    sellOutProgramasAPI.sugerencias.mockResolvedValue({ data: SUGERENCIAS_VACIO });
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=programas'] });
    await waitFor(() => expect(sellOutProgramasAPI.sugerencias).toHaveBeenCalled());
    await screen.findByRole('heading', { name: 'Programas' });
    expect(screen.queryByText(/sugerencias? de programa/)).not.toBeInTheDocument();
  });

  it('"Crear programa y asignar" creates the program with the edited name, assigns its campaigns and refreshes', async () => {
    sellOutProgramasAPI.sugerencias.mockResolvedValue({ data: SUGERENCIAS });
    sellOutProgramasAPI.crear
      .mockRejectedValueOnce({ response: { status: 409, data: { error: { message: 'Ya existe un programa llamado «MARCA».' } } } })
      .mockResolvedValueOnce({ data: { id: 15, nombre: 'MARCA PROG', descripcion: null, estado: 'activo', campanas: 0, activas: 0, desde: null, hasta: null, nombres: 0 } });
    sellOutProgramasAPI.asignar.mockResolvedValue({ data: { asignadas: 3, sin_cambio: 0 } });
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=programas'] });
    await user.click(await screen.findByRole('button', { name: 'Ver sugerencias' }));

    const drawer = screen.getByRole('dialog', { name: 'Sugerencias de programa' });
    expect(drawer).toHaveTextContent('Las sugerencias agrupan campañas sin programa con exactamente las mismas fechas. No se aplica nada hasta que lo confirmes.');
    expect(within(drawer).getAllByRole('textbox', { name: 'Nombre del programa' }).map((i) => i.value)).toEqual([
      'MARCA',
      'Del 01/11/2025 al 31/10/2026',
    ]);
    const primera = tarjeta('01/08/2026', '31/10/2026');
    expect(primera).toHaveTextContent('01/08/2026 – 31/10/2026 · 3 campañas · 2 nombres');
    expect(primera).toHaveTextContent('2 activas');
    await user.click(within(primera).getByRole('button', { name: 'Ver campañas' }));
    expect(within(primera).getByText('MARCA PROGRAM1 (×2)').closest('li')).toHaveTextContent('Activa');
    expect(within(primera).getByText('MARCA PROG 3.0').closest('li')).toHaveTextContent('Anulada');

    await user.click(within(primera).getByRole('button', { name: 'Crear programa y asignar' }));
    expect(await within(primera).findByRole('alert')).toHaveTextContent('Ya existe un programa llamado «MARCA».');
    expect(sellOutProgramasAPI.asignar).not.toHaveBeenCalled();

    const nombre = within(primera).getByRole('textbox', { name: 'Nombre del programa' });
    await user.clear(nombre);
    await user.type(nombre, 'MARCA PROG');
    const sugerencias = sellOutProgramasAPI.sugerencias.mock.calls.length;
    const programas = sellOutProgramasAPI.listar.mock.calls.length;
    await user.click(within(primera).getByRole('button', { name: 'Crear programa y asignar' }));

    await waitFor(() => expect(sellOutProgramasAPI.asignar).toHaveBeenCalledWith([81, 82, 83], 15));
    expect(sellOutProgramasAPI.crear).toHaveBeenLastCalledWith({ nombre: 'MARCA PROG' });
    expect(await within(drawer).findByRole('status')).toHaveTextContent('3 campañas asignadas a «MARCA PROG».');
    await waitFor(() => expect(sellOutProgramasAPI.sugerencias.mock.calls.length).toBeGreaterThan(sugerencias));
    expect(sellOutProgramasAPI.listar.mock.calls.length).toBeGreaterThan(programas);
  });

  it('when the assignment fails after the create, a retry only assigns, and the new program is read at once', async () => {
    sellOutProgramasAPI.sugerencias.mockResolvedValue({ data: SUGERENCIAS });
    sellOutProgramasAPI.crear.mockResolvedValue({ data: { id: 15, nombre: 'MARCA', descripcion: null, estado: 'activo', campanas: 0, activas: 0, desde: null, hasta: null, nombres: 0 } });
    sellOutProgramasAPI.asignar
      .mockRejectedValueOnce({ response: { status: 422, data: { error: { message: 'La campaña 83 no existe.' } } } })
      .mockResolvedValueOnce({ data: { asignadas: 3, sin_cambio: 0 } });
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=programas'] });
    await user.click(await screen.findByRole('button', { name: 'Ver sugerencias' }));
    const primera = tarjeta('01/08/2026', '31/10/2026');
    const programas = sellOutProgramasAPI.listar.mock.calls.length;
    await user.click(within(primera).getByRole('button', { name: 'Crear programa y asignar' }));

    expect(await within(primera).findByRole('alert')).toHaveTextContent('La campaña 83 no existe.');
    await waitFor(() => expect(sellOutProgramasAPI.listar.mock.calls.length).toBeGreaterThan(programas));
    await user.click(within(primera).getByRole('button', { name: 'Crear programa y asignar' }));
    await waitFor(() => expect(sellOutProgramasAPI.asignar).toHaveBeenCalledTimes(2));
    expect(sellOutProgramasAPI.crear).toHaveBeenCalledTimes(1);
    expect(sellOutProgramasAPI.asignar).toHaveBeenLastCalledWith([81, 82, 83], 15);
  });

  it('the drawer takes the focus, keeps Tab inside and gives it back to "Ver sugerencias" on close', async () => {
    sellOutProgramasAPI.sugerencias.mockResolvedValue({ data: SUGERENCIAS });
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=programas'] });
    const abrir = await screen.findByRole('button', { name: 'Ver sugerencias' });
    await user.click(abrir);
    const drawer = screen.getByRole('dialog', { name: 'Sugerencias de programa' });
    await waitFor(() => expect(drawer).toContainElement(document.activeElement));
    for (let i = 0; i < 12; i += 1) {
      await user.tab();
      expect(drawer).toContainElement(document.activeElement);
    }
    await user.click(within(drawer).getByRole('button', { name: 'Cerrar sugerencias' }));
    expect(abrir).toHaveFocus();
  });

  it('a suggestion with more than 500 campaigns cannot be created and assigned at once', async () => {
    const grande = {
      ...SUGERENCIAS.items[0],
      campanas: Array.from({ length: 501 }, (_, i) => ({ ...SUGERENCIAS.items[0].campanas[0], id: 2000 + i })),
    };
    sellOutProgramasAPI.sugerencias.mockResolvedValue({ data: { ...SUGERENCIAS, items: [grande], total: 1 } });
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=programas'] });
    await user.click(await screen.findByRole('button', { name: 'Ver sugerencias' }));
    const card = tarjeta('01/08/2026', '31/10/2026');
    expect(card).toHaveTextContent('Se pueden asignar hasta 500 campañas por vez.');
    expect(within(card).getByRole('button', { name: 'Crear programa y asignar' })).toBeDisabled();
    expect(within(card).getByRole('button', { name: 'Descartar' })).toBeEnabled();
    expect(sellOutProgramasAPI.crear).not.toHaveBeenCalled();
  });

  it('when no suggestion is left, closing the drawer puts the focus on the programs heading', async () => {
    sellOutProgramasAPI.sugerencias.mockResolvedValue({ data: SUGERENCIAS });
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=programas'] });
    await user.click(await screen.findByRole('button', { name: 'Ver sugerencias' }));
    const drawer = screen.getByRole('dialog', { name: 'Sugerencias de programa' });
    await user.click(within(tarjeta('01/08/2026', '31/10/2026')).getByRole('button', { name: 'Descartar' }));
    await user.click(within(tarjeta('01/11/2025', '31/10/2026')).getByRole('button', { name: 'Descartar' }));
    expect(screen.queryByRole('button', { name: 'Ver sugerencias' })).not.toBeInTheDocument();
    await user.click(within(drawer).getByRole('button', { name: 'Cerrar sugerencias' }));
    expect(screen.getByRole('heading', { name: 'Programas' })).toHaveFocus();
  });

  it('"Descartar" hides that card only, for this session, and writes nothing', async () => {
    sellOutProgramasAPI.sugerencias.mockResolvedValue({ data: SUGERENCIAS });
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in?tab=programas'] });
    await user.click(await screen.findByRole('button', { name: 'Ver sugerencias' }));
    await user.click(within(tarjeta('01/08/2026', '31/10/2026')).getByRole('button', { name: 'Descartar' }));

    expect(screen.queryByRole('group', { name: 'Sugerencia del 01/08/2026 al 31/10/2026' })).not.toBeInTheDocument();
    expect(tarjeta('01/11/2025', '31/10/2026')).toBeInTheDocument();
    expect(screen.getByText('1 sugerencia de programa: campañas sin programa con las mismas fechas')).toBeInTheDocument();
    expect(sellOutProgramasAPI.crear).not.toHaveBeenCalled();
    expect(sellOutProgramasAPI.asignar).not.toHaveBeenCalled();
  });
});

// The list's own requests, leaving out the tab's count (page_size 1, on page load).
const listadosDeTacticals = () => tacticalsAPI.listar.mock.calls.filter(([params]) => params.page_size !== 1).length;

describe('SellIn page — Tacticals tab', () => {
  it('opens on Tacticals: counts the current ones on the tab and lists them with the brands to filter by', async () => {
    renderWithRouter(<SellIn />);
    expect(tacticalsAPI.listar).toHaveBeenCalledWith({ estado: 'vigentes', page: 1, page_size: 1 });
    expect(await screen.findByRole('tab', { name: 'Tacticals · 1' })).toHaveAttribute('aria-selected', 'true');

    const panel = screen.getByRole('tabpanel', { name: /Tacticals/ });
    expect(await within(panel).findByText('Rebate TP-Link noviembre')).toBeInTheDocument();
    expect(within(within(panel).getByLabelText('Marca')).getByRole('option', { name: 'TP-Link' })).toBeInTheDocument();
    expect(listadosDeTacticals()).toBe(1);
  });

  it("Renovar in a tactical's menu opens Nuevo tactical prefilled from it", async () => {
    const user = userEvent.setup();
    renderConNuevoTactical('/sell-in');
    await user.click(await screen.findByRole('button', { name: 'Acciones de Rebate TP-Link noviembre' }));
    await user.click(screen.getByRole('menuitem', { name: 'Renovar' }));

    expect(await screen.findByText('Nuevo tactical: sell_in renovando 7')).toBeInTheDocument();
  });

  it('voiding a tactical reloads what Actualizar reloads: the tab count too', async () => {
    const user = userEvent.setup();
    tacticalsAPI.anular.mockResolvedValue({ data: {} });
    renderWithRouter(<SellIn />);
    await user.click(await screen.findByRole('button', { name: 'Acciones de Rebate TP-Link noviembre' }));
    await user.click(screen.getByRole('menuitem', { name: 'Anular' }));
    const conteos = () => tacticalsAPI.listar.mock.calls.filter(([params]) => params.page_size === 1).length;
    const antes = conteos();
    await user.click(screen.getByRole('button', { name: 'Anular tactical' }));

    await waitFor(() => expect(conteos()).toBeGreaterThan(antes));
  });

  it("Ver ventas on a tactical's line opens that line's record in the side panel, read only", async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in'] });
    await user.click(await screen.findByRole('button', { name: 'Ver las líneas de Rebate TP-Link noviembre' }));
    await user.click(screen.getByRole('button', { name: 'Ver ventas de la línea 1' }));

    const panel = await screen.findByRole('complementary', { name: 'Bono de marca' });
    await waitFor(() => expect(sellInBonosAPI.detalle).toHaveBeenCalledWith(31));
    expect(await within(panel).findByRole('heading', { name: 'Bono TP-Link USD 3/u' })).toBeInTheDocument();
    expect(within(panel).queryByRole('button', { name: 'Anular bono' })).not.toBeInTheDocument();
    expect(within(panel).queryByRole('button', { name: 'Guardar cambios' })).not.toBeInTheDocument();
  });

  it('Ver ventas on a line of an unknown origin opens nothing', async () => {
    const user = userEvent.setup();
    const RARO = { ...TACTICAL, lineas: [{ ...TACTICAL.lineas[0], origen: 'otro' }] };
    tacticalsAPI.listar.mockResolvedValue({ data: { total: 1, page: 1, page_size: 50, items: [RARO] } });
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in'] });
    await user.click(await screen.findByRole('button', { name: 'Ver las líneas de Rebate TP-Link noviembre' }));
    await user.click(screen.getByRole('button', { name: 'Ver ventas de la línea 1' }));

    expect(screen.queryByRole('complementary')).not.toBeInTheDocument();
    expect(sellInAPI.detalle).not.toHaveBeenCalled();
  });

  it("without the kind's gestionar a tactical has no actions menu", async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo !== 'sell_in.gestionar');
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in'] });

    expect(await screen.findByText('Rebate TP-Link noviembre')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^Acciones de / })).not.toBeInTheDocument();
  });

  it('"Actualizar" on the Tacticals tab asks the list again', async () => {
    const user = userEvent.setup();
    renderWithRouter(<SellIn />, { initialEntries: ['/sell-in'] });
    expect(await screen.findByText('Rebate TP-Link noviembre')).toBeInTheDocument();
    expect(listadosDeTacticals()).toBe(1);

    await user.click(screen.getByRole('button', { name: /Actualizar/ }));

    await waitFor(() => expect(listadosDeTacticals()).toBe(2));
  });

  it('"Actualizar" also asks the tab count again, which recovers from a failure', async () => {
    const user = userEvent.setup();
    let conteos = 0;
    tacticalsAPI.listar.mockImplementation((params) => {
      if (params.page_size !== 1) return Promise.resolve({ data: pagina([TACTICAL]) });
      conteos += 1;
      return conteos === 1 ? Promise.reject({ response: { status: 500 } }) : Promise.resolve({ data: pagina([TACTICAL], 3) });
    });
    renderWithRouter(<SellIn />);
    expect(await screen.findByRole('tab', { name: 'Tacticals · —' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Actualizar/ }));

    expect(await screen.findByRole('tab', { name: 'Tacticals · 3' })).toBeInTheDocument();
  });

  it('any other failure keeps the tab, with a dash for the count', async () => {
    tacticalsAPI.listar.mockRejectedValue({ response: { status: 500 } });
    renderWithRouter(<SellIn />);

    expect(await screen.findByRole('tab', { name: 'Tacticals · —' })).toBeInTheDocument();
  });
});

// F3: the approved cost-mode design's list, "Costo de sell in por producto. Entrá a un producto para ver sus lotes y
// su modo de costo."
describe('SellIn page — Productos tab', () => {
  const PRODUCTO = {
    item_id: 4512,
    codigo: 'TPL-AX55',
    descripcion: 'Router TP-Link Archer AX55',
    modo: 'ponderado',
    unidades: 200,
    sell_in_unit: '5472.000000',
    ultima_compra: '2026-11-02',
  };

  beforeEach(() => {
    sellInLotesAPI.productos.mockResolvedValue({ data: { productos: [PRODUCTO] } });
    sellInLotesAPI.lotes.mockResolvedValue({
      data: { item_id: 4512, lotes: [], proxima: null, bono_costo: null, compra_visible: false },
    });
    sellInLotesAPI.modos.mockResolvedValue({ data: { item_id: 4512, vigente: null, historial: [] } });
    sellInLotesAPI.modoPorDefecto.mockResolvedValue({ data: { modo: 'fifo' } });
  });

  it('lists the products with their cost mode and a row opens its lots and cost mode', async () => {
    const user = userEvent.setup();
    renderWithRouter(
      <>
        <SellIn />
        <Ubicacion />
      </>,
    );

    await user.click(await screen.findByRole('tab', { name: 'Productos' }));

    const panel = screen.getByRole('tabpanel', { name: 'Productos' });
    const tabla = await within(panel).findByRole('table', { name: 'Productos con lotes de sell in' });
    expect(within(tabla).getByText('Ponderado (PPP)')).toBeInTheDocument();
    expect(screen.getByTestId('ubicacion')).toHaveTextContent('tab=productos');

    await user.click(within(tabla).getByRole('button', { name: 'Ver lotes y modo de costo de Router TP-Link Archer AX55' }));

    expect(await screen.findByRole('heading', { name: 'Costo de sell in · Router TP-Link Archer AX55' })).toBeInTheDocument();
    expect(screen.getByText('TPL-AX55 · 200 unidades en stock')).toBeInTheDocument();
    expect(sellInLotesAPI.lotes).toHaveBeenCalledWith(4512);
  });

  it('needs a permission that shows products: without one there is no Productos tab', async () => {
    const VER_PRODUCTO = ['productos.ver', 'productos.editar_precio_clasica', 'productos.editar_precio_cuotas',
      'productos.toggle_rebate', 'productos.toggle_web_transferencia', 'tienda.editar_precio_gremio',
      'tienda.editar_precio_web_transf'];
    mockTienePermiso.mockImplementation((codigo) => !VER_PRODUCTO.includes(codigo));
    renderWithRouter(<SellIn />);

    expect(await screen.findByRole('tab', { name: /^Tacticals/ })).toBeInTheDocument();
    expect(screen.queryByRole('tab', { name: 'Productos' })).not.toBeInTheDocument();
    expect(sellInLotesAPI.productos).not.toHaveBeenCalled();
  });
});
