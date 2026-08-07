import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import api from '../../services/api';
import TabRecepcionDeposito from './TabRecepcionDeposito';

// NOTE: vite.config.js sets `css: false` for the test run, so CSS Module class
// names do NOT resolve. Never assert on className — assert on text and roles.

const PEDIDO_PAGADO = {
  id: 1,
  numero: 'PC-0001',
  proveedor_id: 10,
  proveedor_nombre: 'Proveedor Uno',
  estado: 'pagado',
  numero_factura: 'A-0001-00000001',
  observaciones: 'Entregar en el portón 3',
  requiere_envio: false,
  oc_poh_id: null,
  // Money fields are part of the payload but must never reach the clipboard.
  monto: '123456.78',
  moneda: 'ARS',
};

const PEDIDO_CUENTA_CORRIENTE = {
  id: 2,
  numero: 'PC-0002',
  proveedor_id: 20,
  proveedor_nombre: 'Proveedor Dos',
  estado: 'en_cuenta_corriente',
  numero_factura: null,
  observaciones: null,
  requiere_envio: true,
  oc_poh_id: null,
  monto: '999999.99',
  moneda: 'USD',
};

// CON-OC fixtures (oc_poh_id set) — Phase 4/5 (D5a, D5b/D6). The two existing
// fixtures above are deliberately SIN-OC (oc_poh_id: null); these cover the
// arrival read-only table and the closed-header items badge.
const PEDIDO_CON_OC_PAGADO = {
  id: 3,
  numero: 'PC-0003',
  proveedor_id: 30,
  proveedor_nombre: 'Proveedor Tres',
  estado: 'pagado',
  numero_factura: null,
  observaciones: null,
  requiere_envio: false,
  oc_poh_id: 500,
  oc_lineas_total: 2,
  oc_unidades_total: '15.000000',
  monto: '5000.00',
  moneda: 'ARS',
};

const PEDIDO_CON_OC_CUENTA_CORRIENTE = {
  ...PEDIDO_CON_OC_PAGADO,
  id: 4,
  numero: 'PC-0004',
  estado: 'en_cuenta_corriente',
  oc_lineas_total: 1,
  oc_unidades_total: '1.000000',
};

// Two OC lines, split across two depositos — matches the pod_id = item×destino
// granularity the design's copy locks ("2 líneas", never "productos distintos").
const SALDOS_ARRIBO = {
  pedido_id: PEDIDO_CON_OC_PAGADO.id,
  tiene_oc: true,
  estado: 'pagado',
  requiere_envio: false,
  lineas: [
    {
      pod_id: 1001,
      item_id: 55,
      item_code: 'SKU-55',
      item_nombre: 'Memoria RAM 16GB',
      stor_id: 1,
      deposito_nombre: 'Depósito Central',
      pod_qty: '10.000000',
      cantidad_recibida_total: '0.000000',
      saldo_pendiente: '10.000000',
    },
    {
      pod_id: 1002,
      item_id: 56,
      item_code: 'SKU-56',
      item_nombre: 'Disco SSD 1TB',
      stor_id: 2,
      deposito_nombre: 'Depósito Norte',
      pod_qty: '5.000000',
      cantidad_recibida_total: '0.000000',
      saldo_pendiente: '5.000000',
    },
  ],
};

const LISTADO_ENDPOINT = '/administracion/compras/pedidos';
const saldosUrlFor = (pedidoId) =>
  `/administracion/compras/pedidos/${pedidoId}/recepcion/saldos`;

function mockListado(items) {
  api.get.mockResolvedValue({
    data: { items, total: items.length, page: 1, page_size: 200 },
  });
}

/**
 * Routes GET by URL: the listing endpoint returns `items`, and
 * `/recepcion/saldos` for `pedidoId` resolves/rejects per `saldosByPedidoId`.
 * `{ reject: detail }` triggers a 409-shaped rejection; anything else resolves.
 */
function mockListadoAndSaldos(items, saldosByPedidoId = {}) {
  api.get.mockImplementation((url) => {
    if (url === LISTADO_ENDPOINT) {
      return Promise.resolve({ data: { items, total: items.length, page: 1, page_size: 200 } });
    }
    const match = url.match(/\/pedidos\/(\d+)\/recepcion\/saldos$/);
    if (match) {
      const entry = saldosByPedidoId[Number(match[1])];
      if (entry?.reject) {
        return Promise.reject({ response: { data: { detail: entry.reject } } });
      }
      if (entry) return Promise.resolve({ data: entry });
      return Promise.reject(new Error(`no saldos mock for pedido ${match[1]}`));
    }
    return Promise.reject(new Error(`unexpected GET ${url}`));
  });
}

/**
 * Renders the tab and waits for the first pedido of the mocked listing to show up,
 * so the mount fetch is settled before any assertion runs.
 */
async function renderTab(items = [PEDIDO_PAGADO, PEDIDO_CUENTA_CORRIENTE]) {
  mockListado(items);
  const result = render(<TabRecepcionDeposito />);
  await screen.findByText(`#${items[0].numero}`);
  return result;
}

/**
 * jsdom does not implement navigator.clipboard, and userEvent.setup() installs
 * its own stub — so this must run AFTER setup() or it gets overwritten.
 */
function stubClipboard() {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText },
    configurable: true,
    writable: true,
  });
  return writeText;
}

/**
 * The tab renders exactly ONE copy live region, however many pedidos are listed:
 * at most one copy outcome can exist at a time, so one region per row meant a
 * full page mounted up to 200 of them.
 *
 * The count is asserted HERE rather than only in the dedicated guard test, so
 * every live-region test breaks the moment a per-row region comes back.
 */
function copyLiveRegion() {
  const regions = screen.getAllByRole('status');
  expect(regions).toHaveLength(1);
  return regions[0];
}

/**
 * Renders a single pedido, clicks its copy button and returns the copied string.
 * The clipboard payload builder is module-private, so it is exercised through
 * the button that owns it.
 */
async function copiarPedido(pedido) {
  const user = userEvent.setup();
  const writeText = stubClipboard();
  await renderTab([pedido]);

  await user.click(
    screen.getByRole('button', { name: `Copiar datos del pedido #${pedido.numero}` }),
  );

  expect(writeText).toHaveBeenCalledTimes(1);
  return writeText.mock.calls[0][0];
}

afterEach(() => {
  delete navigator.clipboard;
});

describe('TabRecepcionDeposito — "Por recibir" merged filter', () => {
  it('requests the listing with both receivable estados on mount', async () => {
    await renderTab();

    expect(api.get).toHaveBeenCalledWith(LISTADO_ENDPOINT, {
      params: { estado: 'pagado,en_cuenta_corriente', page_size: 200 },
    });
  });

  it('has no "En cuenta corriente" filter tab, but still shows its badge', async () => {
    await renderTab();

    // The filter tabs are exactly four; payment mode is not a warehouse filter.
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'Por recibir',
      'Recibidos sin controlar',
      'Controlados',
      'Con faltantes',
    ]);
    expect(screen.queryByRole('tab', { name: 'En cuenta corriente' })).not.toBeInTheDocument();

    // The badge stays: it is informative, and it is the only place the payment
    // mode is still visible. Re-splitting the tabs must break the assertion above.
    expect(screen.getByText('En cuenta corriente')).toBeInTheDocument();
  });

  it('lists pagado and en_cuenta_corriente pedidos under the single tab', async () => {
    await renderTab();

    expect(screen.getByText('#PC-0001')).toBeInTheDocument();
    expect(screen.getByText('Proveedor Uno')).toBeInTheDocument();
    expect(screen.getByText('Pagado')).toBeInTheDocument();

    expect(screen.getByText('#PC-0002')).toBeInTheDocument();
    expect(screen.getByText('Proveedor Dos')).toBeInTheDocument();
    expect(screen.getByText('En cuenta corriente')).toBeInTheDocument();
  });
});

describe('TabRecepcionDeposito — copy header data', () => {
  it('copies numero, proveedor, estado label, factura and observaciones', async () => {
    const copiado = await copiarPedido(PEDIDO_PAGADO);

    expect(copiado).toBe(
      [
        'Pedido #PC-0001',
        'Proveedor: Proveedor Uno',
        'Estado: Pagado',
        'Factura: A-0001-00000001',
        'Observaciones: Entregar en el portón 3',
      ].join('\n'),
    );
  });

  it('never leaks money fields', async () => {
    const copiado = await copiarPedido(PEDIDO_PAGADO);

    // Deliberate privacy decision: warehouse listings withhold the money trail,
    // and the clipboard must not become a side channel around it.
    expect(copiado).not.toContain('123456.78');
    expect(copiado).not.toContain('ARS');
    expect(copiado).not.toMatch(/monto|saldo|tipo de cambio/i);
  });

  it('omits null factura and observaciones and appends the retiro line', async () => {
    const copiado = await copiarPedido(PEDIDO_CUENTA_CORRIENTE);

    expect(copiado).toBe(
      [
        'Pedido #PC-0002',
        'Proveedor: Proveedor Dos',
        'Estado: En cuenta corriente',
        'Requiere retiro',
      ].join('\n'),
    );
  });

  it('omits blank values and the retiro line when requiere_envio is false', async () => {
    const copiado = await copiarPedido({
      ...PEDIDO_PAGADO,
      numero_factura: '   ',
      observaciones: '',
    });

    expect(copiado).toBe(['Pedido #PC-0001', 'Proveedor: Proveedor Uno', 'Estado: Pagado'].join('\n'));
    expect(copiado).not.toContain('Requiere retiro');
  });

  it('falls back to the raw estado when it has no known label', async () => {
    const copiado = await copiarPedido({ ...PEDIDO_PAGADO, estado: 'estado_desconocido' });

    expect(copiado).toContain('Estado: estado_desconocido');
  });

  it('renders exactly ONE live region for a list of two pedidos', async () => {
    stubClipboard();
    await renderTab([PEDIDO_PAGADO, PEDIDO_CUENTA_CORRIENTE]);

    // Regression guard for the per-row region this replaced. Both pedido rows
    // are collapsed, so the only role="status" in the tree is the list-level one:
    // reinstating one region per PedidoAccordion makes this count 2 and fail.
    expect(screen.getAllByRole('status')).toHaveLength(1);
    expect(screen.getByText('#PC-0001')).toBeInTheDocument();
    expect(screen.getByText('#PC-0002')).toBeInTheDocument();
  });

  it('mounts the copy live region empty, before any interaction', async () => {
    stubClipboard();
    await renderTab([PEDIDO_PAGADO, PEDIDO_CUENTA_CORRIENTE]);

    // The region must exist from the very first render: a live region inserted
    // at the same moment its text appears is routinely missed by screen readers.
    expect(copyLiveRegion()).toBeEmptyDOMElement();
  });

  it('announces a successful copy through the live region', async () => {
    const user = userEvent.setup();
    stubClipboard();
    await renderTab([PEDIDO_PAGADO, PEDIDO_CUENTA_CORRIENTE]);

    await user.click(screen.getByRole('button', { name: 'Copiar datos del pedido #PC-0001' }));

    // Success used to be signalled only by an aria-hidden <Check> icon, so
    // assistive technology got a failure message but never a confirmation.
    await screen.findByText('Datos del pedido #PC-0001 copiados');
    expect(copyLiveRegion()).toHaveTextContent('Datos del pedido #PC-0001 copiados');
  });

  it('reuses the shared live region for the next pedido copied', async () => {
    const user = userEvent.setup();
    stubClipboard();
    await renderTab([PEDIDO_PAGADO, PEDIDO_CUENTA_CORRIENTE]);

    await user.click(screen.getByRole('button', { name: 'Copiar datos del pedido #PC-0001' }));
    await screen.findByText('Datos del pedido #PC-0001 copiados');

    await user.click(screen.getByRole('button', { name: 'Copiar datos del pedido #PC-0002' }));

    // The one region now names the pedido that was JUST copied. A stale message
    // here would tell the operator the wrong pedido made it to the clipboard.
    await screen.findByText('Datos del pedido #PC-0002 copiados');
    expect(copyLiveRegion()).toHaveTextContent('Datos del pedido #PC-0002 copiados');
    expect(screen.queryByText('Datos del pedido #PC-0001 copiados')).not.toBeInTheDocument();
  });

  it('announces a rejected copy through the live region, keeping the button name stable', async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockRejectedValue(new Error('NotAllowedError'));
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
      writable: true,
    });
    await renderTab([PEDIDO_PAGADO, PEDIDO_CUENTA_CORRIENTE]);

    await user.click(screen.getByRole('button', { name: 'Copiar datos del pedido #PC-0001' }));

    // A rejected copy must be distinguishable from a click that never happened.
    await screen.findByText('No se pudo copiar el pedido #PC-0001');
    expect(copyLiveRegion()).toHaveTextContent('No se pudo copiar el pedido #PC-0001');

    // The accessible name describes the action, not the last outcome. Mutating
    // it is not reliably re-announced for the already-focused element, and it
    // would double up with the live region.
    expect(
      screen.getByRole('button', { name: 'Copiar datos del pedido #PC-0001' }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /No se pudo copiar/ })).not.toBeInTheDocument();
  });

  it('announces the failure through the live region when the clipboard API is missing', async () => {
    const user = userEvent.setup();
    // userEvent.setup() installs its own clipboard stub, so removing the API
    // has to happen after it — this is the browser-without-async-clipboard case.
    delete navigator.clipboard;
    await renderTab([PEDIDO_PAGADO, PEDIDO_CUENTA_CORRIENTE]);

    await user.click(screen.getByRole('button', { name: 'Copiar datos del pedido #PC-0001' }));

    await screen.findByText('No se pudo copiar el pedido #PC-0001');
    expect(copyLiveRegion()).toHaveTextContent('No se pudo copiar el pedido #PC-0001');
  });

  it('does not toggle the accordion open', async () => {
    const user = userEvent.setup();
    stubClipboard();
    await renderTab([PEDIDO_PAGADO]);

    const toggle = screen.getByRole('button', { name: /Proveedor Uno/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');

    await user.click(screen.getByRole('button', { name: 'Copiar datos del pedido #PC-0001' }));

    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText(/no tiene OC vinculada/i)).not.toBeInTheDocument();
  });
});

describe('TabRecepcionDeposito — retiro action', () => {
  it('labels the retiro button "Coordinar retiro"', async () => {
    await renderTab([PEDIDO_CUENTA_CORRIENTE]);

    expect(
      screen.getByRole('button', { name: 'Coordinar retiro para pedido #PC-0002' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Coordinar retiro')).toBeInTheDocument();
    expect(screen.queryByText('Despachar retiro')).not.toBeInTheDocument();
  });
});

// ── Phase 4 (D5a) — read-only arrival item list ──────────────────

describe('TabRecepcionDeposito — arrival item list (CON-OC, D5a)', () => {
  /** Renders the tab, opens the single pedido's accordion, and returns the user. */
  async function renderArribo(pedido, saldosByPedidoId) {
    const user = userEvent.setup();
    mockListadoAndSaldos([pedido], saldosByPedidoId);
    render(<TabRecepcionDeposito />);
    await screen.findByText(`#${pedido.numero}`);
    await user.click(screen.getByRole('button', { name: new RegExp(pedido.proveedor_nombre) }));
    return user;
  }

  it.each([
    ['pagado', PEDIDO_CON_OC_PAGADO],
    ['en_cuenta_corriente', PEDIDO_CON_OC_CUENTA_CORRIENTE],
  ])('renders read-only item rows with zero editable controls for estado=%s', async (_estado, pedido) => {
    await renderArribo(pedido, { [pedido.id]: SALDOS_ARRIBO });

    await screen.findByText('Memoria RAM 16GB');
    expect(screen.getByText('Disco SSD 1TB')).toBeInTheDocument();
    expect(screen.getByText('Depósito Central')).toBeInTheDocument();
    expect(screen.getByText('Depósito Norte')).toBeInTheDocument();
    // The fixture feeds the raw serialized Decimal ("10.000000") exactly as the
    // backend sends it; the cell must render the OPERATOR-facing form. Asserting
    // the raw string here is what let "10.000000" reach a column whose whole job
    // is to be read at a glance.
    expect(screen.getByText('10')).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.queryByText('10.000000')).not.toBeInTheDocument();

    // ZERO editable controls: no input (any type), no checkbox, no tanda state.
    expect(document.querySelectorAll('input')).toHaveLength(0);
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
    expect(screen.queryAllByRole('spinbutton')).toHaveLength(0);
    expect(
      screen.queryByRole('button', { name: /marcar (con faltantes|como controlado)/i }),
    ).not.toBeInTheDocument();

    // Banner + "Marcar como recibido" stay reachable.
    const arriboBtn = screen.getByRole('button', { name: 'Marcar como recibido' });
    expect(arriboBtn).toBeInTheDocument();
    expect(arriboBtn).not.toBeDisabled();
  });

  it('"Marcar como recibido" still works with the item list present', async () => {
    api.post.mockResolvedValue({
      data: { pedido_id: PEDIDO_CON_OC_PAGADO.id, estado_nuevo: 'recibido' },
    });
    const user = await renderArribo(PEDIDO_CON_OC_PAGADO, { [PEDIDO_CON_OC_PAGADO.id]: SALDOS_ARRIBO });
    await screen.findByText('Memoria RAM 16GB');

    await user.click(screen.getByRole('button', { name: 'Marcar como recibido' }));

    await screen.findByText(/Arribo registrado/);
    expect(api.post).toHaveBeenCalledWith(
      `/administracion/compras/pedidos/${PEDIDO_CON_OC_PAGADO.id}/recepcion/confirmar-pedido`,
      { completo: true },
    );
  });

  it('keeps the banner and "Marcar como recibido" reachable when /saldos fails', async () => {
    await renderArribo(PEDIDO_CON_OC_PAGADO, {
      [PEDIDO_CON_OC_PAGADO.id]: { reject: 'saldos no disponibles' },
    });

    await screen.findByRole('alert');
    expect(screen.getByText('saldos no disponibles')).toBeInTheDocument();

    // The deliberate divergence from AccordionBodyConOc: a failed /saldos
    // fetch must NOT early-return the body.
    expect(screen.getByRole('button', { name: 'Marcar como recibido' })).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('shows a loading indicator while /saldos is pending, without hiding the banner', async () => {
    let resolveSaldos;
    const user = userEvent.setup();
    api.get.mockImplementation((url) => {
      if (url === LISTADO_ENDPOINT) {
        return Promise.resolve({
          data: { items: [PEDIDO_CON_OC_PAGADO], total: 1, page: 1, page_size: 200 },
        });
      }
      if (url === saldosUrlFor(PEDIDO_CON_OC_PAGADO.id)) {
        return new Promise((resolve) => {
          resolveSaldos = resolve;
        });
      }
      return Promise.reject(new Error(`unexpected GET ${url}`));
    });
    render(<TabRecepcionDeposito />);
    await screen.findByText(`#${PEDIDO_CON_OC_PAGADO.numero}`);
    await user.click(screen.getByRole('button', { name: /Proveedor Tres/ }));

    expect(await screen.findByText(/Cargando/)).toBeInTheDocument();
    // Not an early return: the banner/button render even while /saldos is pending.
    expect(screen.getByRole('button', { name: 'Marcar como recibido' })).toBeInTheDocument();

    resolveSaldos({ data: SALDOS_ARRIBO });
    await screen.findByText('Memoria RAM 16GB');
  });

  it('does not render the table when /saldos returns zero lineas', async () => {
    await renderArribo(PEDIDO_CON_OC_PAGADO, {
      [PEDIDO_CON_OC_PAGADO.id]: { ...SALDOS_ARRIBO, lineas: [] },
    });
    await screen.findByRole('button', { name: 'Marcar como recibido' });

    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('renders an absent quantity as a dash, never "NaN" or a fabricated 0', async () => {
    // Contract test for formatUnidades, not a reachable backend state:
    // SaldoLineaResponse declares the quantity fields as required Decimals, so
    // Pydantic would reject a null before the frontend ever saw it. This pins the
    // formatter's behaviour for whoever reuses it on a genuinely optional field.
    await renderArribo(PEDIDO_CON_OC_PAGADO, {
      [PEDIDO_CON_OC_PAGADO.id]: {
        ...SALDOS_ARRIBO,
        lineas: [{ ...SALDOS_ARRIBO.lineas[0], pod_qty: null }],
      },
    });

    await screen.findByText('Memoria RAM 16GB');
    expect(screen.queryByText('NaN')).not.toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });
});

// ── Phase 5 (D5b, D6, D8) — closed-header identification ─────────

describe('TabRecepcionDeposito — closed header items badge (CON-OC, D6)', () => {
  it('renders the badge with "N líneas · N u" copy, never "productos distintos"', async () => {
    await renderTab([PEDIDO_CON_OC_PAGADO]);

    expect(screen.getByText('2 líneas · 15 u')).toBeInTheDocument();
    expect(screen.queryByText(/productos distintos/i)).not.toBeInTheDocument();
  });

  it('uses singular "línea" when there is exactly one line', async () => {
    await renderTab([PEDIDO_CON_OC_CUENTA_CORRIENTE]);

    expect(screen.getByText('1 línea · 1 u')).toBeInTheDocument();
  });

  it('renders the badge across multiple estados for CON-OC pedidos', async () => {
    const recibido = {
      ...PEDIDO_CON_OC_PAGADO,
      id: 5,
      numero: 'PC-0005',
      estado: 'recibido',
      oc_lineas_total: 3,
      oc_unidades_total: '9.000000',
    };
    await renderTab([recibido]);

    expect(screen.getByText('3 líneas · 9 u')).toBeInTheDocument();
  });

  it('renders no badge at all — never "0 ítems" — when oc_lineas_total is null', async () => {
    const sinAgregado = {
      ...PEDIDO_CON_OC_PAGADO,
      id: 6,
      numero: 'PC-0006',
      oc_lineas_total: null,
      oc_unidades_total: null,
    };
    await renderTab([sinAgregado]);

    expect(screen.queryByText(/línea/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/0 ítems/i)).not.toBeInTheDocument();
  });

  it('renders no badge when oc_lineas_total is 0, not "0 líneas · 0 u"', async () => {
    // The backend cannot currently produce this: the aggregate's GROUP BY emits
    // no row for an OC with no lines, so the pedido is absent from the map and
    // both fields arrive null. This pins the render-site guard anyway — the
    // component is the last place that can stop the forbidden fake zero, and it
    // must not rely on an invariant enforced two layers away.
    const cero = {
      ...PEDIDO_CON_OC_PAGADO,
      id: 7,
      numero: 'PC-0007',
      oc_lineas_total: 0,
      oc_unidades_total: '0.000000',
    };
    await renderTab([cero]);

    expect(screen.queryByText(/línea/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/0 u/i)).not.toBeInTheDocument();
  });

  it('excludes the badge text from the accordion toggle accessible name (D8)', async () => {
    await renderTab([PEDIDO_CON_OC_PAGADO]);

    // .headerBadges is a sibling of .accordionToggle: the toggle's own text
    // content (its accessible name, name-from-content) must not include it.
    const toggle = screen.getByRole('button', { name: /Proveedor Tres/ });
    expect(toggle.textContent).not.toMatch(/línea/i);
  });
});

describe('TabRecepcionDeposito — closed header identification chips (SIN-OC, D6, D8)', () => {
  it('shows a factura chip when numero_factura is present', async () => {
    await renderTab([PEDIDO_PAGADO]);

    expect(screen.getByText(PEDIDO_PAGADO.numero_factura)).toBeInTheDocument();
  });

  it('omits the factura/observaciones chips when both fields are empty', async () => {
    await renderTab([PEDIDO_CUENTA_CORRIENTE]);

    // Only the copy button carries a `title` in this render; a rendered chip
    // would add a second one.
    const titled = document.querySelectorAll('[title]');
    expect(titled).toHaveLength(1);
    expect(titled[0]).toHaveAccessibleName('Copiar datos del pedido #PC-0002');
  });

  it('truncates a long observaciones chip visually but keeps the full text in title and sr-only', async () => {
    const texto =
      'Coordinar entrega con el encargado de turno tarde antes de las 18 horas, sin excepciones.';
    await renderTab([{ ...PEDIDO_PAGADO, observaciones: texto }]);

    const truncado = `${texto.slice(0, 60).trimEnd()}…`;
    expect(screen.getByText(truncado)).toBeInTheDocument();
    expect(screen.queryByText(texto)).not.toBeInTheDocument();

    const chip = screen.getByTitle(texto);
    expect(chip).toHaveTextContent(`Observaciones: ${texto}`);
  });

  it('does not truncate observaciones at or under 60 chars', async () => {
    await renderTab([PEDIDO_PAGADO]);

    // Fixture observaciones is 24 chars — must render verbatim, no ellipsis.
    expect(screen.getByText(PEDIDO_PAGADO.observaciones)).toBeInTheDocument();
  });
});
