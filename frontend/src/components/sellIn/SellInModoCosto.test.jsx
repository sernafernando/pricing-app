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

  // sell-in-costo-si T5 PR A: the server answers 410 to any change, so the card never offers one.
  it('with every mode permission offers no change either, and says the cost is costo SI', async () => {
    permisos = new Set(['sell_in.costo_ponderado', 'sell_in.costo_ultimo', 'sell_in.costo_manual', 'sell_in.costo_retroactivo']);
    renderPanel();
    const region = await panel();
    expect(within(region).queryByRole('group', { name: 'Cambiar a' })).not.toBeInTheDocument();
    expect(within(region).queryByRole('button', { name: 'Ver cómo queda' })).not.toBeInTheDocument();
    expect(within(region).queryByRole('button', { name: 'Manual' })).not.toBeInTheDocument();
    expect(within(region).getByText('El modo de costo ya no se puede cambiar: el costo es el costo SI.')).toBeInTheDocument();
    expect(sellInLotesAPI.vistaPrevia).not.toHaveBeenCalled();
  });
});

/**
 * The mode the selector opens preselected with, a global setting only an admin changes. Owner: "podemos hacer un
 * modal donde un admin pueda elegir cuál es el por defecto?" ... "ponele que hoy trabajamos con FIFO, pero deciden que
 * empecemos a trabajar con PPP para evitar cagadas eligen que por defecto el modal abra en PPP".
 */
describe('the default mode', () => {
  it.each(['VENTAS', 'PRICING_MANAGER', undefined])('is not offered to change to a non-admin (%s)', async (r) => {
    rol = r;
    renderPanel();
    const region = await panel();
    expect(within(region).queryByRole('button', { name: 'Modo por defecto' })).not.toBeInTheDocument();
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
    del_bloque: true,
  };

  beforeEach(() => {
    permisos = new Set(['sell_in.costo_manual']);
    sellInLotesAPI.vistaPrevia.mockResolvedValue({ data: MANUAL });
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

describe('collapsed behind its current mode (product panel, S5)', () => {
  const renderCollapsed = () => render(<SellInLotes productItemId={950} collapseModo />);

  it('says "Ver", never "Cambiar", even with every mode permission (T5 PR A)', async () => {
    permisos = new Set(['sell_in.costo_ponderado', 'sell_in.costo_ultimo', 'sell_in.costo_manual']);
    renderCollapsed();
    const region = await screen.findByRole('region', { name: 'Modo de costo' });
    await within(region).findByText('FIFO (por defecto)');
    expect(within(region).getByRole('button', { name: 'Ver' })).toBeInTheDocument();
    expect(within(region).queryByRole('button', { name: 'Cambiar' })).not.toBeInTheDocument();
  });

  it('says "Ver" instead of "Cambiar" without a mode permission', async () => {
    permisos = new Set();
    renderCollapsed();
    const region = await screen.findByRole('region', { name: 'Modo de costo' });
    await within(region).findByText('FIFO (por defecto)');
    expect(within(region).getByRole('button', { name: 'Ver' })).toBeInTheDocument();
  });

  it('a load error keeps the card open with its retry', async () => {
    sellInLotesAPI.modos.mockRejectedValue(httpError(500));
    renderCollapsed();
    expect(await screen.findByText('No se pudo cargar el modo de costo.')).toBeInTheDocument();
  });
});
