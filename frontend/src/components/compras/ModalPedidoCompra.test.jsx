import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ModalPedidoCompra from './ModalPedidoCompra';

const { pedidosApi } = vi.hoisted(() => ({
  pedidosApi: {
    crear: vi.fn().mockResolvedValue({ id: 1 }),
    editar: vi.fn().mockResolvedValue({ id: 1 }),
    loading: false,
    error: null,
  },
}));

vi.mock('../../hooks/useComprasPedidos', () => ({ default: () => pedidosApi }));
vi.mock('./ProveedorComprasAutocomplete', () => ({
  default: () => <div data-testid="proveedor-stub" />,
}));

const EMPRESAS = [{ id: 1, nombre: 'Empresa Uno' }];
const PROVEEDOR = { id: 10, nombre: 'Proveedor Uno' };

describe('ModalPedidoCompra — create tipo selector', () => {
  beforeEach(() => {
    pedidosApi.crear.mockClear();
    pedidosApi.editar.mockClear();
  });

  it('defaults to mercaderia and sends tipo on create', async () => {
    const user = userEvent.setup();
    render(
      <ModalPedidoCompra
        pedido={null}
        empresas={EMPRESAS}
        proveedorInicial={PROVEEDOR}
        onClose={vi.fn()}
      />
    );

    const tipo = screen.getByLabelText(/Tipo/i);
    expect(tipo).toHaveValue('mercaderia');

    await user.selectOptions(screen.getAllByRole('combobox')[0], '1');
    await user.type(screen.getByPlaceholderText('0.00'), '100');
    await user.click(screen.getByRole('button', { name: 'Crear pedido' }));

    expect(pedidosApi.crear).toHaveBeenCalledTimes(1);
    expect(pedidosApi.crear.mock.calls[0][0]).toMatchObject({
      tipo: 'mercaderia',
      empresa_id: 1,
      proveedor_id: 10,
      monto: 100,
    });
  });

  it('sends tipo=servicio when the PM selects servicio', async () => {
    const user = userEvent.setup();
    render(
      <ModalPedidoCompra
        pedido={null}
        empresas={EMPRESAS}
        proveedorInicial={PROVEEDOR}
        onClose={vi.fn()}
      />
    );

    await user.selectOptions(screen.getByLabelText(/Tipo/i), 'servicio');
    await user.selectOptions(screen.getAllByRole('combobox')[0], '1');
    await user.type(screen.getByPlaceholderText('0.00'), '50');
    await user.click(screen.getByRole('button', { name: 'Crear pedido' }));

    expect(pedidosApi.crear).toHaveBeenCalledTimes(1);
    expect(pedidosApi.crear.mock.calls[0][0].tipo).toBe('servicio');
  });

  it('hides the tipo selector on edit and does not send tipo', async () => {
    const user = userEvent.setup();
    render(
      <ModalPedidoCompra
        pedido={{
          id: 9,
          numero: 'P-01-2026-00009',
          empresa_id: 1,
          proveedor_id: 10,
          moneda: 'ARS',
          monto: '80',
          tipo: 'mercaderia',
          estado: 'borrador',
        }}
        empresas={EMPRESAS}
        onClose={vi.fn()}
      />
    );

    expect(screen.queryByLabelText(/Tipo/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Guardar cambios' }));

    expect(pedidosApi.editar).toHaveBeenCalledTimes(1);
    expect(pedidosApi.editar.mock.calls[0][1]).not.toHaveProperty('tipo');
  });
});
