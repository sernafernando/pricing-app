import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PanelCheques from './PanelCheques';

// NOTE: vite.config.js sets `css: false` for the test run, so CSS Module class
// names do NOT resolve. Never assert on className — assert on text and roles.

const { hookValue } = vi.hoisted(() => ({
  hookValue: { listar: vi.fn().mockResolvedValue({ items: [] }), loading: false },
}));

vi.mock('../../../hooks/useCheques', () => ({ default: () => hookValue }));

// ModalCheque real abre un formulario completo con llamadas a /admin/empresas.
// Acá sólo interesa el payload que devuelve, así que lo reemplazamos por un
// disparador: el panel es quien tiene la lógica bajo prueba.
vi.mock('../ModalCheque', () => ({
  default: ({ onEmitido }) => (
    <button
      type="button"
      onClick={() =>
        onEmitido({
          banco_empresa_id: 1,
          instrumento: 'fisico',
          numero: '00000001',
          monto: 5000,
          moneda: 'ARS',
          fecha_emision: '2026-08-25',
          fecha_pago: '2026-08-25',
          proveedor_id: 10,
        })
      }
    >
      stub-emitir
    </button>
  ),
}));

const PEDIDO_A = { id: '101', numero: 'P-0101', moneda: 'ARS' };
const PEDIDO_B = { id: '202', numero: 'P-0202', moneda: 'ARS' };
const PEDIDO_C = { id: '303', numero: 'P-0303', moneda: 'ARS' };

const agregarCheque = async (user) => {
  await user.click(screen.getByRole('button', { name: /^Cheques/ }));
  await user.click(screen.getByRole('button', { name: /Emitir cheque propio/i }));
  await user.click(screen.getByRole('button', { name: 'stub-emitir' }));
};

describe('PanelCheques — destino por pedido', () => {
  beforeEach(() => {
    hookValue.listar.mockClear();
  });

  it('con un solo pedido no pide destino', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <PanelCheques proveedorId={10} opMoneda="ARS" pedidos={[PEDIDO_A]} onChange={onChange} />
    );
    await agregarCheque(user);

    expect(screen.queryByLabelText(/Pedido destino/i)).not.toBeInTheDocument();
    expect(onChange).toHaveBeenLastCalledWith([
      expect.objectContaining({ numero: '00000001' }),
    ]);
  });

  it('con varios pedidos pide destino y lo propaga al padre', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <PanelCheques
        proveedorId={10}
        opMoneda="ARS"
        pedidos={[PEDIDO_A, PEDIDO_B]}
        onChange={onChange}
      />
    );
    await agregarCheque(user);

    expect(screen.getByText(/Elegí contra qué pedido se descuenta/i)).toBeInTheDocument();

    await user.selectOptions(
      screen.getByLabelText('Pedido destino para cheque 00000001'),
      '202'
    );

    expect(onChange).toHaveBeenLastCalledWith([
      expect.objectContaining({ pedido_id: 202 }),
    ]);
    expect(screen.queryByText(/Elegí contra qué pedido se descuenta/i)).not.toBeInTheDocument();
  });

  it('limpia el destino cuando el pedido elegido sale de la OP', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(
      <PanelCheques
        proveedorId={10}
        opMoneda="ARS"
        pedidos={[PEDIDO_A, PEDIDO_B]}
        onChange={onChange}
      />
    );
    await agregarCheque(user);
    await user.selectOptions(
      screen.getByLabelText('Pedido destino para cheque 00000001'),
      '202'
    );

    // Sigue habiendo 2 pedidos, así que el selector no desaparece: el destino
    // viejo sólo se limpia si la limpieza corre de verdad.
    rerender(
      <PanelCheques
        proveedorId={10}
        opMoneda="ARS"
        pedidos={[PEDIDO_A, PEDIDO_C]}
        onChange={onChange}
      />
    );

    expect(onChange).toHaveBeenLastCalledWith([
      expect.objectContaining({ pedido_id: null }),
    ]);
  });
});

describe('PanelCheques — permiteNuevosCheques (S5)', () => {
  beforeEach(() => {
    hookValue.listar.mockClear();
  });

  it('deshabilita Emitir y Endosar cuando permiteNuevosCheques=false, deja Aplicar habilitado', async () => {
    const user = userEvent.setup();
    render(
      <PanelCheques
        proveedorId={10}
        opMoneda="ARS"
        pedidos={[PEDIDO_A]}
        onChange={vi.fn()}
        permiteNuevosCheques={false}
      />
    );
    await user.click(screen.getByRole('button', { name: /^Cheques/ }));

    expect(screen.getByRole('button', { name: /Emitir cheque propio/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Endosar de cartera/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Aplicar cheque propio/i })).toBeEnabled();
    expect(screen.getByText(/Para emitir un cheque propio nuevo o endosar/i)).toBeInTheDocument();
  });

  it('habilita las tres acciones cuando permiteNuevosCheques=true (default)', async () => {
    const user = userEvent.setup();
    render(
      <PanelCheques proveedorId={10} opMoneda="ARS" pedidos={[PEDIDO_A]} onChange={vi.fn()} />
    );
    await user.click(screen.getByRole('button', { name: /^Cheques/ }));

    expect(screen.getByRole('button', { name: /Emitir cheque propio/i })).toBeEnabled();
    expect(screen.getByRole('button', { name: /Endosar de cartera/i })).toBeEnabled();
    expect(screen.getByRole('button', { name: /Aplicar cheque propio/i })).toBeEnabled();
  });
});
