import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PanelNCsProveedor from './PanelNCsProveedor';

// NOTE: vite.config.js sets `css: false` for the test run, so CSS Module class
// names do NOT resolve. Never assert on className — assert on text and roles.

// Referentially stable on purpose — the panel memoizes on the hook's functions.
const { hookValue } = vi.hoisted(() => ({
  hookValue: { listarDisponibles: vi.fn() },
}));

vi.mock('../../../hooks/useNCsLocales', () => ({ default: () => hookValue }));

const NC_ARS = {
  id: 5,
  numero: 'NC-0001',
  monto: '26246678.10',
  saldo_pendiente: '26246678.10',
  moneda: 'ARS',
  proveedor_id: 10,
};

const PEDIDO_A = { id: '101', numero: 'P-0101', moneda: 'ARS' };
const PEDIDO_B = { id: '202', numero: 'P-0202', moneda: 'ARS' };
const PEDIDO_C = { id: '303', numero: 'P-0303', moneda: 'ARS' };

const abrirPanel = async (user) => {
  await user.click(screen.getByRole('button', { name: /NCs disponibles del proveedor/i }));
  await screen.findByText('NC-0001');
};

describe('PanelNCsProveedor — mode="seleccionar"', () => {
  beforeEach(() => {
    hookValue.listarDisponibles.mockReset().mockResolvedValue([NC_ARS]);
  });

  it('con un solo pedido no pide destino y emite pedido_id null (lo infiere el backend)', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <PanelNCsProveedor
        proveedorId={10}
        opMoneda="ARS"
        mode="seleccionar"
        pedidos={[PEDIDO_A]}
        onChange={onChange}
      />
    );
    await abrirPanel(user);

    expect(screen.queryByLabelText(/Pedido destino/i)).not.toBeInTheDocument();

    await user.click(screen.getByLabelText('Seleccionar NC NC-0001'));

    expect(onChange).toHaveBeenLastCalledWith([
      expect.objectContaining({ nc_id: 5, pedido_id: null }),
    ]);
  });

  it('con varios pedidos pide destino y no emite pedido_id hasta que se elige', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <PanelNCsProveedor
        proveedorId={10}
        opMoneda="ARS"
        mode="seleccionar"
        pedidos={[PEDIDO_A, PEDIDO_B]}
        onChange={onChange}
      />
    );
    await abrirPanel(user);

    await user.click(screen.getByLabelText('Seleccionar NC NC-0001'));

    // Seleccionada pero sin destino: el consumidor debe poder distinguirlo.
    expect(onChange).toHaveBeenLastCalledWith([
      expect.objectContaining({ nc_id: 5, pedido_id: null }),
    ]);
    expect(screen.getByText(/Elegí contra qué pedido se descuenta/i)).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Pedido destino para NC NC-0001'), '202');

    expect(onChange).toHaveBeenLastCalledWith([
      expect.objectContaining({ nc_id: 5, pedido_id: 202 }),
    ]);
    expect(screen.queryByText(/Elegí contra qué pedido se descuenta/i)).not.toBeInTheDocument();
  });

  it('limpia el destino cuando el pedido elegido sale de la OP', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(
      <PanelNCsProveedor
        proveedorId={10}
        opMoneda="ARS"
        mode="seleccionar"
        pedidos={[PEDIDO_A, PEDIDO_B]}
        onChange={onChange}
      />
    );
    await abrirPanel(user);
    await user.click(screen.getByLabelText('Seleccionar NC NC-0001'));
    await user.selectOptions(screen.getByLabelText('Pedido destino para NC NC-0001'), '202');
    expect(onChange).toHaveBeenLastCalledWith([
      expect.objectContaining({ pedido_id: 202 }),
    ]);

    // El usuario reemplaza P-0202 por P-0303. Siguen siendo 2 pedidos (el selector
    // no desaparece), así que el destino viejo sólo se limpia si la limpieza corre.
    rerender(
      <PanelNCsProveedor
        proveedorId={10}
        opMoneda="ARS"
        mode="seleccionar"
        pedidos={[PEDIDO_A, PEDIDO_C]}
        onChange={onChange}
      />
    );

    expect(onChange).toHaveBeenLastCalledWith([
      expect.objectContaining({ pedido_id: null }),
    ]);
  });
});
