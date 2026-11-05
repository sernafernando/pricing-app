/**
 * The cost-mode panel inside the sell-in lot viewer (`GET/POST /sell-in/productos/{id}/modos`, `.../vista-previa`):
 * the mode governing today, the change to FIFO / Ponderado (PPP) / Último precio with its mandatory preview, and the
 * history. Owner: "El panel de modificaciones de ponderado y eso no existe todavía ... están los permisos pero no
 * existe un front para eso".
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SellInLotes from './SellInLotes';
import { sellInLotesAPI } from '../../services/sellInAPI';

vi.mock('../../services/sellInAPI', () => ({
  sellInLotesAPI: {
    lotes: vi.fn(),
    consumos: vi.fn(),
    modos: vi.fn(),
    vistaPrevia: vi.fn(),
    confirmarModo: vi.fn(),
    modoPorDefecto: vi.fn(),
    fijarModoPorDefecto: vi.fn(),
  },
}));

let permisos = new Set();
let rol = 'VENTAS';
vi.mock('../../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: (codigo) => permisos.has(codigo), rol }),
}));

const httpError = (status) => Object.assign(new Error(`HTTP ${status}`), { response: { status, data: {} } });

const LOTES = {
  item_id: 950,
  lotes: [
    { numero: 1, compra_item_id: 501, compra_id: 41, proveedor: 'Gauss SA', facturas: [], moneda: 'ARS', fecha_desde: '2026-10-01', cantidad: 40, consumidas: 0, restantes: 40, descuento_unit: '5472.000000', estado: 'vigente' },
    { numero: 2, compra_item_id: 502, compra_id: 42, proveedor: 'Gauss SA', facturas: [], moneda: 'ARS', fecha_desde: '2026-10-28', cantidad: 100, consumidas: 0, restantes: 100, descuento_unit: '5346.000000', estado: 'en_cola' },
  ],
  proxima: { numero: 1, compra_item_id: 501, descuento_unit: '5472.000000', restantes: 40, siguiente: { numero: 2, descuento_unit: '5346.000000', fecha_desde: '2026-10-28', estado: 'en_cola' } },
  bono_costo: null,
  compra_visible: true,
};

const fila = (overrides = {}) => ({
  id: 7,
  modo: 'ultimo',
  desde: '2026-11-01',
  cantidad: null,
  costo_unit: null,
  costo_base_unit: null,
  origen: 'visor',
  compra_id: null,
  usuario_id: 1,
  usuario_nombre: 'Fernando',
  created_at: '2026-11-02T10:00:00',
  ...overrides,
});

const PREVIEW = {
  ventas_cambian: 0,
  diferencia_ars: '0.00',
  unidades_restantes: 140,
  descuento_unit: '5382.000000',
  sin_asignar_antes: '0.00',
  sin_asignar_despues: '0.00',
  huella: 'a'.repeat(64),
};

const renderPanel = () => render(<SellInLotes productItemId={950} />);
/** The panel once its modes are read (its own "Cargando modo de costo…" is gone). */
async function panel() {
  const region = await screen.findByRole('region', { name: 'Modo de costo' });
  await within(region).findByText('Modo actual');
  return region;
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(new Date(2026, 10, 4, 12, 0, 0));
  permisos = new Set(['sell_in.costo_ponderado', 'sell_in.costo_ultimo']);
  rol = 'VENTAS';
  for (const fn of Object.values(sellInLotesAPI)) fn.mockReset();
  sellInLotesAPI.lotes.mockResolvedValue({ data: LOTES });
  sellInLotesAPI.modos.mockResolvedValue({ data: { item_id: 950, vigente: null, historial: [] } });
  sellInLotesAPI.vistaPrevia.mockResolvedValue({ data: PREVIEW });
  sellInLotesAPI.modoPorDefecto.mockResolvedValue({ data: { modo: 'fifo' } });
  sellInLotesAPI.fijarModoPorDefecto.mockImplementation((modo) => Promise.resolve({ data: { modo } }));
  sellInLotesAPI.confirmarModo.mockResolvedValue({ data: fila({ id: 8, modo: 'ponderado', desde: '2026-11-04' }) });
});

afterEach(() => vi.useRealTimers());

describe('the mode governing today', () => {
  it('is FIFO by default when the product has no mode row', async () => {
    renderPanel();
    const region = await panel();
    expect(sellInLotesAPI.modos).toHaveBeenCalledWith(950);
    expect(within(region).getByText('Modo actual').parentElement).toHaveTextContent('FIFO (por defecto)');
  });

  it('names the governing mode, since when, and lists the history newest first with who set it', async () => {
    sellInLotesAPI.modos.mockResolvedValue({
      data: { item_id: 950, vigente: fila(), historial: [fila(), fila({ id: 6, modo: 'fifo', desde: '2026-10-28', created_at: '2026-10-28T09:00:00' })] },
    });
    renderPanel();
    const region = await panel();
    expect(within(region).getByText('Modo actual').parentElement).toHaveTextContent('Último precio desde 01/11/2026');
    const historial = within(screen.getByRole('region', { name: 'Historial' })).getByRole('list', { name: 'Historial de modos' });
    const filas = within(historial).getAllByRole('listitem').map((li) => li.textContent);
    expect(filas).toEqual(['02/11/2026Último preciodesde 01/11/2026 · por Fernando', '28/10/2026FIFOdesde 28/10/2026 · por Fernando']);
  });

  it('is not shown without permission to read the modes (403), and the lots still are', async () => {
    sellInLotesAPI.modos.mockRejectedValue(httpError(403));
    renderPanel();
    await screen.findByRole('list', { name: 'Lotes en orden FIFO' });
    await waitFor(() => expect(sellInLotesAPI.modos).toHaveBeenCalled());
    expect(screen.queryByRole('region', { name: 'Modo de costo' })).not.toBeInTheDocument();
  });
});

describe('changing the mode', () => {
  it('without any mode permission shows only the current mode and the history, no change controls', async () => {
    permisos = new Set();
    renderPanel();
    const region = await panel();
    expect(within(region).queryByRole('group', { name: 'Cambiar a' })).not.toBeInTheDocument();
    expect(within(region).queryByRole('button', { name: 'Ver cómo queda' })).not.toBeInTheDocument();
  });

  it('enables each mode only with its own permission; FIFO with any of them', async () => {
    permisos = new Set(['sell_in.costo_ponderado']);
    renderPanel();
    const modos = within(await panel()).getByRole('group', { name: 'Cambiar a' });
    expect(within(modos).getByRole('button', { name: 'FIFO' })).toBeEnabled();
    expect(within(modos).getByRole('button', { name: 'Ponderado (PPP)' })).toBeEnabled();
    expect(within(modos).getByRole('button', { name: 'Último precio' })).toBeDisabled();
    expect(within(modos).getByRole('button', { name: 'Manual' })).toBeDisabled();
  });

  it('previews the change from today and confirms it with the fingerprint, then reloads the modes and the lots', async () => {
    const user = userEvent.setup();
    renderPanel();
    const region = await panel();
    await user.click(within(region).getByRole('button', { name: 'Ponderado (PPP)' }));
    expect(region).toHaveTextContent('Ponderado (PPP): todas las unidades quedan a un mismo descuento de sell in por unidad.');
    expect(within(region).getByLabelText('Desde')).toHaveValue('2026-11-04');
    await user.click(within(region).getByRole('button', { name: 'Ver cómo queda' }));

    expect(sellInLotesAPI.vistaPrevia).toHaveBeenCalledWith(950, { modo: 'ponderado', desde: '2026-11-04' });
    const preview = await screen.findByRole('region', { name: 'Así queda' });
    expect(preview).toHaveTextContent('Ventas ya registradas que cambian: 0');
    expect(preview).toHaveTextContent('Diferencia total: $ 0,00');
    expect(preview).toHaveTextContent('Quedan 140 u a $ 5.382,00 de sell in c/u');
    const proxima = within(preview).getByRole('row', { name: /Próxima unidad/ });
    expect(proxima).toHaveTextContent('$ 5.472,00$ 5.382,00');

    sellInLotesAPI.modos.mockResolvedValue({ data: { item_id: 950, vigente: fila({ id: 8, modo: 'ponderado', desde: '2026-11-04' }), historial: [fila({ id: 8, modo: 'ponderado', desde: '2026-11-04' })] } });
    await user.click(within(preview).getByRole('button', { name: 'Confirmar cambio' }));
    expect(sellInLotesAPI.confirmarModo).toHaveBeenCalledWith(950, { modo: 'ponderado', desde: '2026-11-04', huella: 'a'.repeat(64) });
    await waitFor(() => expect(within(region).getByText('Modo actual').parentElement).toHaveTextContent('Ponderado (PPP) desde 04/11/2026'));
    expect(screen.queryByRole('region', { name: 'Así queda' })).not.toBeInTheDocument();
    expect(sellInLotesAPI.lotes).toHaveBeenCalledTimes(2);
  });

  it('a past date needs the backdating permission; with it the preview counts the recorded sales that change', async () => {
    const user = userEvent.setup();
    const { unmount } = renderPanel();
    expect(within(await panel()).getByLabelText('Desde')).toHaveAttribute('min', '2026-11-04');
    unmount();

    permisos.add('sell_in.costo_retroactivo');
    sellInLotesAPI.vistaPrevia.mockResolvedValue({ data: { ...PREVIEW, ventas_cambian: 6, diferencia_ars: '-18240.50' } });
    renderPanel();
    const region = await panel();
    const desde = within(region).getByLabelText('Desde');
    expect(desde).not.toHaveAttribute('min');
    await user.click(within(region).getByRole('button', { name: 'Último precio' }));
    await user.clear(desde);
    await user.type(desde, '2026-10-20');
    await user.click(within(region).getByRole('button', { name: 'Ver cómo queda' }));
    expect(sellInLotesAPI.vistaPrevia).toHaveBeenCalledWith(950, { modo: 'ultimo', desde: '2026-10-20' });
    const preview = await screen.findByRole('region', { name: 'Así queda' });
    expect(preview).toHaveTextContent('Ventas ya registradas que cambian: 6');
    expect(preview).toHaveTextContent('Diferencia total: -$ 18.240,50');
  });

  it('shows the ARS the last price leaves unassigned or hands out beyond the lots, never hides it', async () => {
    const user = userEvent.setup();
    sellInLotesAPI.vistaPrevia.mockResolvedValue({ data: { ...PREVIEW, sin_asignar_despues: '200.00' } });
    renderPanel();
    const region = await panel();
    await user.click(within(region).getByRole('button', { name: 'Último precio' }));
    await user.click(within(region).getByRole('button', { name: 'Ver cómo queda' }));
    expect(await screen.findByRole('region', { name: 'Así queda' })).toHaveTextContent(
      'Con este modo $ 200,00 de los lotes quedan sin asignar a ninguna unidad.',
    );
  });

  it('a mode or date change after the preview drops it, so nothing is confirmed that was not previewed', async () => {
    const user = userEvent.setup();
    renderPanel();
    const region = await panel();
    await user.click(within(region).getByRole('button', { name: 'Ponderado (PPP)' }));
    await user.click(within(region).getByRole('button', { name: 'Ver cómo queda' }));
    await screen.findByRole('region', { name: 'Así queda' });
    await user.click(within(region).getByRole('button', { name: 'Último precio' }));
    expect(screen.queryByRole('region', { name: 'Así queda' })).not.toBeInTheDocument();
  });

  it('while the preview is computing the mode and the date are locked, so it never shows under another mode', async () => {
    sellInLotesAPI.vistaPrevia.mockReturnValue(new Promise(() => {}));
    const user = userEvent.setup();
    renderPanel();
    const region = await panel();
    await user.click(within(region).getByRole('button', { name: 'Ponderado (PPP)' }));
    await user.click(within(region).getByRole('button', { name: 'Ver cómo queda' }));
    expect(within(region).getByRole('button', { name: 'Último precio' })).toBeDisabled();
    expect(within(region).getByLabelText('Desde')).toBeDisabled();
  });

  it('when the product moved since the preview (409) says to preview again and drops the preview', async () => {
    const user = userEvent.setup();
    sellInLotesAPI.confirmarModo.mockRejectedValue(httpError(409));
    renderPanel();
    const region = await panel();
    await user.click(within(region).getByRole('button', { name: 'Ponderado (PPP)' }));
    await user.click(within(region).getByRole('button', { name: 'Ver cómo queda' }));
    await user.click(within(await screen.findByRole('region', { name: 'Así queda' })).getByRole('button', { name: 'Confirmar cambio' }));
    expect(await within(region).findByRole('alert')).toHaveTextContent(
      'El producto cambió desde la vista previa (o alguien lo está modificando). Tocá «Ver cómo queda» de nuevo.',
    );
    expect(screen.queryByRole('region', { name: 'Así queda' })).not.toBeInTheDocument();
  });

  it('cancel drops the preview and saves nothing', async () => {
    const user = userEvent.setup();
    renderPanel();
    const region = await panel();
    await user.click(within(region).getByRole('button', { name: 'Ponderado (PPP)' }));
    await user.click(within(region).getByRole('button', { name: 'Ver cómo queda' }));
    await user.click(within(await screen.findByRole('region', { name: 'Así queda' })).getByRole('button', { name: 'Cancelar' }));
    expect(screen.queryByRole('region', { name: 'Así queda' })).not.toBeInTheDocument();
    expect(sellInLotesAPI.confirmarModo).not.toHaveBeenCalled();
  });
});

/**
 * The mode the selector opens preselected with, a global setting only an admin changes. Owner: "podemos hacer un
 * modal donde un admin pueda elegir cuál es el por defecto?" ... "ponele que hoy trabajamos con FIFO, pero deciden que
 * empecemos a trabajar con PPP para evitar cagadas eligen que por defecto el modal abra en PPP".
 */
describe('the default mode', () => {
  const elegido = (region) =>
    within(within(region).getByRole('group', { name: 'Cambiar a' }))
      .getAllByRole('button')
      .filter((b) => b.getAttribute('aria-pressed') === 'true')
      .map((b) => b.textContent);

  it('opens the selector on the default mode', async () => {
    sellInLotesAPI.modoPorDefecto.mockResolvedValue({ data: { modo: 'ponderado' } });
    renderPanel();
    const region = await panel();
    await waitFor(() => expect(elegido(region)).toEqual(['Ponderado (PPP)']));
    expect(within(region).getByRole('button', { name: 'Ver cómo queda' })).toBeEnabled();
  });

  it('falls back to FIFO when the user may not set the default mode', async () => {
    permisos = new Set(['sell_in.costo_ponderado']);
    sellInLotesAPI.modoPorDefecto.mockResolvedValue({ data: { modo: 'ultimo' } });
    renderPanel();
    const region = await panel();
    await waitFor(() => expect(sellInLotesAPI.modoPorDefecto).toHaveBeenCalled());
    expect(elegido(region)).toEqual(['FIFO']);
  });

  it('falls back to FIFO for Manual, never a default (it needs its own figures), and when the setting cannot be read', async () => {
    permisos.add('sell_in.costo_manual');
    sellInLotesAPI.modoPorDefecto.mockResolvedValue({ data: { modo: 'manual' } });
    const { unmount } = renderPanel();
    expect(elegido(await panel())).toEqual(['FIFO']);
    unmount();

    sellInLotesAPI.modoPorDefecto.mockRejectedValue(httpError(500));
    renderPanel();
    expect(elegido(await panel())).toEqual(['FIFO']);
  });

  it.each(['VENTAS', 'PRICING_MANAGER', undefined])('is not offered to change to a non-admin (%s)', async (r) => {
    rol = r;
    renderPanel();
    const region = await panel();
    expect(within(region).queryByRole('button', { name: 'Modo por defecto' })).not.toBeInTheDocument();
  });

  it('an admin changes it in a modal and the selector opens on the new one', async () => {
    rol = 'ADMIN';
    const user = userEvent.setup();
    renderPanel();
    const region = await panel();
    await user.click(within(region).getByRole('button', { name: 'Modo por defecto' }));
    expect(await screen.findByRole('heading', { name: 'Modo por defecto' })).toBeInTheDocument();
    expect(screen.getByText(/No recalcula nada/)).toBeInTheDocument();
    const grupo = screen.getByRole('group', { name: 'Modo por defecto' });
    expect(within(grupo).getByRole('button', { name: 'FIFO' })).toHaveAttribute('aria-pressed', 'true');
    // Manual would fall back to FIFO for everyone, so it is not offered.
    expect(within(grupo).getAllByRole('button').map((b) => b.textContent)).toEqual(['FIFO', 'Ponderado (PPP)', 'Último precio']);
    await user.click(within(grupo).getByRole('button', { name: 'Último precio' }));
    await user.click(screen.getByRole('button', { name: 'Guardar' }));
    expect(sellInLotesAPI.fijarModoPorDefecto).toHaveBeenCalledWith('ultimo');
    await waitFor(() => expect(screen.queryByRole('group', { name: 'Modo por defecto' })).not.toBeInTheDocument());
    expect(elegido(region)).toEqual(['Último precio']);
  });

  it('a default saved while a preview is open does not change the previewed mode', async () => {
    rol = 'ADMIN';
    sellInLotesAPI.modoPorDefecto.mockResolvedValue({ data: { modo: 'ponderado' } });
    const user = userEvent.setup();
    renderPanel();
    const region = await panel();
    await waitFor(() => expect(elegido(region)).toEqual(['Ponderado (PPP)']));
    await user.click(within(region).getByRole('button', { name: 'Ver cómo queda' }));
    await screen.findByRole('region', { name: 'Así queda' });

    await user.click(within(region).getByRole('button', { name: 'Modo por defecto' }));
    await user.click(within(screen.getByRole('group', { name: 'Modo por defecto' })).getByRole('button', { name: 'Último precio' }));
    await user.click(screen.getByRole('button', { name: 'Guardar' }));
    await waitFor(() => expect(screen.queryByRole('group', { name: 'Modo por defecto' })).not.toBeInTheDocument());

    expect(elegido(region)).toEqual(['Ponderado (PPP)']);
    const preview = screen.getByRole('region', { name: 'Así queda' });
    expect(preview).toHaveTextContent('Después (Ponderado (PPP))');
    await user.click(within(preview).getByRole('button', { name: 'Confirmar cambio' }));
    expect(sellInLotesAPI.confirmarModo).toHaveBeenCalledWith(950, expect.objectContaining({ modo: 'ponderado' }));
  });

  it('after a failed preview the selector follows the default again', async () => {
    rol = 'ADMIN';
    sellInLotesAPI.modoPorDefecto.mockResolvedValue({ data: { modo: 'ponderado' } });
    sellInLotesAPI.vistaPrevia.mockRejectedValue(httpError(500));
    const user = userEvent.setup();
    renderPanel();
    const region = await panel();
    await waitFor(() => expect(elegido(region)).toEqual(['Ponderado (PPP)']));
    await user.click(within(region).getByRole('button', { name: 'Ver cómo queda' }));
    await within(region).findByRole('alert');

    await user.click(within(region).getByRole('button', { name: 'Modo por defecto' }));
    await user.click(within(screen.getByRole('group', { name: 'Modo por defecto' })).getByRole('button', { name: 'Último precio' }));
    await user.click(screen.getByRole('button', { name: 'Guardar' }));
    await waitFor(() => expect(screen.queryByRole('group', { name: 'Modo por defecto' })).not.toBeInTheDocument());
    expect(elegido(region)).toEqual(['Último precio']);
  });

  it('a failed save keeps the modal open and says so', async () => {
    rol = 'SUPERADMIN';
    sellInLotesAPI.fijarModoPorDefecto.mockRejectedValue(httpError(403));
    const user = userEvent.setup();
    renderPanel();
    const region = await panel();
    await user.click(within(region).getByRole('button', { name: 'Modo por defecto' }));
    await user.click(within(screen.getByRole('group', { name: 'Modo por defecto' })).getByRole('button', { name: 'Ponderado (PPP)' }));
    await user.click(screen.getByRole('button', { name: 'Guardar' }));
    expect(await screen.findByText('No tenés permiso para ese cambio.')).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Modo por defecto' })).toBeInTheDocument();
    expect(elegido(region)).toEqual(['FIFO']);
  });
});

/**
 * The manual mode (D6): the user types the quantity and unit cost left (the approved design's "Cantidad" and "Costo
 * unitario"); the server freezes the product's cost, and each unit carries that cost minus the typed one. Owner: "otro
 * permiso aparte para poder setear cantidad y costo a mano, por si un sell in quedó defazado al stock actual y se
 * quiere usar un costo a mano que sea el de reposición por ejemplo".
 */
describe('the manual mode', () => {
  const MANUAL = {
    ...PREVIEW,
    unidades_restantes: 30,
    descuento_unit: '-2000.000000',
    costo_base_unit: '50000.000000',
  };

  async function elegirManual(user) {
    const region = await panel();
    await user.click(within(region).getByRole('button', { name: 'Manual' }));
    return region;
  }

  beforeEach(() => {
    permisos = new Set(['sell_in.costo_manual']);
    sellInLotesAPI.vistaPrevia.mockResolvedValue({ data: MANUAL });
  });

  it('is offered only with its own permission', async () => {
    permisos = new Set(['sell_in.costo_ponderado', 'sell_in.costo_ultimo']);
    const { unmount } = renderPanel();
    expect(within(within(await panel()).getByRole('group', { name: 'Cambiar a' })).getByRole('button', { name: 'Manual' })).toBeDisabled();
    unmount();

    permisos = new Set(['sell_in.costo_manual']);
    renderPanel();
    expect(within(within(await panel()).getByRole('group', { name: 'Cambiar a' })).getByRole('button', { name: 'Manual' })).toBeEnabled();
  });

  it('asks for the quantity and unit cost, and previews only with both', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderPanel();
    expect(within(await panel()).queryByLabelText('Cantidad')).not.toBeInTheDocument();
    const region = await elegirManual(user);
    const ver = within(region).getByRole('button', { name: 'Ver cómo queda' });
    expect(ver).toBeDisabled();
    await user.type(within(region).getByLabelText('Cantidad'), '30');
    expect(ver).toBeDisabled();
    await user.type(within(region).getByLabelText('Costo unitario'), '52000');
    expect(ver).toBeEnabled();
    await user.clear(within(region).getByLabelText('Cantidad'));
    await user.type(within(region).getByLabelText('Cantidad'), '0');
    expect(ver).toBeDisabled();
  });

  it('previews and confirms with the typed figures, showing the frozen cost and the surcharge', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderPanel();
    const region = await elegirManual(user);
    await user.type(within(region).getByLabelText('Cantidad'), '30');
    await user.type(within(region).getByLabelText('Costo unitario'), '52000');
    await user.click(within(region).getByRole('button', { name: 'Ver cómo queda' }));

    const cuerpo = { modo: 'manual', desde: '2026-11-04', cantidad: 30, costo_unit: '52000' };
    expect(sellInLotesAPI.vistaPrevia).toHaveBeenCalledWith(950, cuerpo);
    const vista = await screen.findByRole('region', { name: 'Así queda' });
    expect(vista).toHaveTextContent('Quedan 30 u a $ 52.000,00 c/u (manual)');
    expect(vista).toHaveTextContent('Costo del producto congelado: $ 50.000,00');
    expect(vista).toHaveTextContent('Cada unidad suma $ 2.000,00 al costo (recargo de sell in)');

    await user.click(within(vista).getByRole('button', { name: 'Confirmar cambio' }));
    expect(sellInLotesAPI.confirmarModo).toHaveBeenCalledWith(950, { ...cuerpo, huella: 'a'.repeat(64) });
  });

  it('a typed cost below the frozen one is a discount per unit', async () => {
    sellInLotesAPI.vistaPrevia.mockResolvedValue({ data: { ...MANUAL, descuento_unit: '1500.000000' } });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderPanel();
    const region = await elegirManual(user);
    await user.type(within(region).getByLabelText('Cantidad'), '30');
    await user.type(within(region).getByLabelText('Costo unitario'), '48500');
    await user.click(within(region).getByRole('button', { name: 'Ver cómo queda' }));

    expect(await screen.findByRole('region', { name: 'Así queda' })).toHaveTextContent(
      'Cada unidad descuenta $ 1.500,00 del costo (sell in)',
    );
  });

  it('when recorded sales already used the block up, the units left are not said to be at the typed cost', async () => {
    // A past `desde`: the next sale takes a later purchase at 5 346, not the manual block.
    sellInLotesAPI.vistaPrevia.mockResolvedValue({ data: { ...MANUAL, unidades_restantes: 100, descuento_unit: '5346.000000' } });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderPanel();
    const region = await elegirManual(user);
    await user.type(within(region).getByLabelText('Cantidad'), '30');
    await user.type(within(region).getByLabelText('Costo unitario'), '52000');
    await user.click(within(region).getByRole('button', { name: 'Ver cómo queda' }));

    const vista = await screen.findByRole('region', { name: 'Así queda' });
    expect(vista).toHaveTextContent('Quedan 100 u a $ 5.346,00 de sell in c/u');
    expect(vista).not.toHaveTextContent('(manual)');
  });

  it.each([
    ['The product has no cost to freeze', 'No se pudo calcular la vista previa: el producto no tiene costo cargado para congelar.'],
    [
      "There is no USD rate to freeze the product's cost in pesos",
      'No se pudo calcular la vista previa: no hay tipo de cambio USD para pasar el costo del producto a pesos.',
    ],
  ])('says why it cannot freeze the product cost (%s)', async (mensaje, texto) => {
    sellInLotesAPI.vistaPrevia.mockRejectedValue(
      Object.assign(new Error('HTTP 422'), { response: { status: 422, data: { error: { message: mensaje } } } }),
    );
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderPanel();
    const region = await elegirManual(user);
    await user.type(within(region).getByLabelText('Cantidad'), '30');
    await user.type(within(region).getByLabelText('Costo unitario'), '52000');
    await user.click(within(region).getByRole('button', { name: 'Ver cómo queda' }));

    expect(await within(region).findByRole('alert')).toHaveTextContent(texto);
  });

  it('changing a figure drops the preview', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    renderPanel();
    const region = await elegirManual(user);
    await user.type(within(region).getByLabelText('Cantidad'), '30');
    await user.type(within(region).getByLabelText('Costo unitario'), '52000');
    await user.click(within(region).getByRole('button', { name: 'Ver cómo queda' }));
    await screen.findByRole('region', { name: 'Así queda' });

    await user.type(within(region).getByLabelText('Cantidad'), '1');
    expect(screen.queryByRole('region', { name: 'Así queda' })).not.toBeInTheDocument();
  });

  it('the history shows a manual row with its figures', async () => {
    const manual = fila({ modo: 'manual', cantidad: 30, costo_unit: '52000.000000', costo_base_unit: '50000.000000' });
    sellInLotesAPI.modos.mockResolvedValue({ data: { item_id: 950, vigente: manual, historial: [manual] } });
    renderPanel();
    await panel();
    const historial = within(screen.getByRole('region', { name: 'Historial' })).getByRole('list', { name: 'Historial de modos' });
    expect(within(historial).getByRole('listitem')).toHaveTextContent(
      'Manualdesde 01/11/2026 · 30 u a $ 52.000,00 (costo congelado $ 50.000,00) · por Fernando',
    );
  });
});
