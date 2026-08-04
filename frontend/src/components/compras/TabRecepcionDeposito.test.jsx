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

const LISTADO_ENDPOINT = '/administracion/compras/pedidos';

function mockListado(items) {
  api.get.mockResolvedValue({
    data: { items, total: items.length, page: 1, page_size: 200 },
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
