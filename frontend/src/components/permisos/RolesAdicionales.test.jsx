import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import api from '../../services/api';
import RolesAdicionales from './RolesAdicionales';

vi.mock('../../services/api', () => ({
  default: { get: vi.fn(), put: vi.fn() },
}));

const PRICING = { id: 3, codigo: 'PRICING', nombre: 'Pricing' };
const COMPRAS = { id: 4, codigo: 'COMPRAS', nombre: 'Compras' };
const VENTAS = { id: 5, codigo: 'VENTAS', nombre: 'Ventas' };
// An inactive role the `/roles` list does not include.
const LEGADO = { id: 9, codigo: 'LEGADO', nombre: 'Legado' };

const respuesta = (adicionales) => ({ usuario_id: 7, rol_principal: PRICING, roles_adicionales: adicionales });

function renderSeccion(props = {}) {
  const onGuardado = vi.fn();
  render(<RolesAdicionales usuarioId={7} roles={[PRICING, COMPRAS, VENTAS]} onGuardado={onGuardado} {...props} />);
  return { onGuardado };
}

beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockResolvedValue({ data: respuesta([COMPRAS, LEGADO]) });
  api.put.mockResolvedValue({ data: respuesta([COMPRAS, LEGADO]) });
});

describe('RolesAdicionales', () => {
  it('shows a role missing from the roles list by its code and keeps it on save', async () => {
    const user = userEvent.setup();
    const { onGuardado } = renderSeccion();

    expect(await screen.findByText('Compras')).toBeInTheDocument();
    expect(screen.getByText('LEGADO')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Editar roles adicionales' }));
    expect(screen.queryByRole('checkbox', { name: /LEGADO/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Guardar' }));

    expect(api.put).toHaveBeenCalledWith('/usuarios/7/roles-adicionales', { rol_ids: [4, 9] });
    expect(onGuardado).toHaveBeenCalled();
  });

  it('does not offer editing until the roles list has loaded', async () => {
    renderSeccion({ roles: null });

    // Without the list, every pill shows the server's code.
    expect(await screen.findByText('COMPRAS')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Editar roles adicionales' })).toBeDisabled();
    expect(screen.getByText(/lista de roles no está disponible/)).toBeInTheDocument();
  });

  it('shows a failed load and retries it', async () => {
    const user = userEvent.setup();
    api.get.mockRejectedValueOnce({ response: { data: { detail: 'Error de servidor' } } });
    renderSeccion();

    const alerta = await screen.findByRole('alert');
    expect(alerta).toHaveTextContent('Error de servidor');

    await user.click(screen.getByRole('button', { name: 'Reintentar' }));

    expect(await screen.findByText('Compras')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(api.get).toHaveBeenCalledTimes(2);
  });
});
