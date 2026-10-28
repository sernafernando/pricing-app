import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import api from '../../services/api';
import AuditFilters from './AuditFilters';
import { EMPTY_AUDIT_FILTERS, kindLabel } from './auditFilters';

vi.mock('../../services/api', () => ({ default: { get: vi.fn() } }));

const filters = (overrides = {}) => ({ ...EMPTY_AUDIT_FILTERS, ...overrides });
const openPanel = () => userEvent.click(screen.getByRole('button', { name: /Filtros de auditoría/ }));

beforeEach(() => {
  api.get.mockImplementation((url) =>
    Promise.resolve({
      data:
        url === '/auditoria/usuarios'
          ? { usuarios: [{ id: 5, nombre: 'Ana' }, { id: 6, nombre: 'Beto' }] }
          : { tipos: ['modificar_precio_clasica', 'activar_rebate'] },
    }),
  );
});

describe('auditFilters', () => {
  it("clears Productos' four audit keys and labels a kind the way Productos does", () => {
    expect(EMPTY_AUDIT_FILTERS).toEqual({ audit_usuarios: [], audit_tipos: [], audit_desde: '', audit_hasta: '' });
    expect(kindLabel('modificar_precio_clasica')).toBe('Modificar Precio Clasica');
  });
});

describe('AuditFilters', () => {
  it("offers Productos' users, kinds and date range behind one button, loaded when it opens", async () => {
    render(<AuditFilters filters={filters()} setFilters={vi.fn()} />);
    expect(api.get).not.toHaveBeenCalled();
    await openPanel();
    expect(await screen.findByRole('checkbox', { name: 'Ana' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Activar Rebate' })).toBeInTheDocument();
    expect(screen.getByLabelText('Desde')).toHaveAttribute('type', 'datetime-local');
    expect(screen.getByLabelText('Hasta')).toHaveAttribute('type', 'datetime-local');
  });

  it('writes each pick to the URL', async () => {
    const setFilters = vi.fn();
    render(<AuditFilters filters={filters({ audit_usuarios: ['6'] })} setFilters={setFilters} />);
    await openPanel();
    await userEvent.click(await screen.findByRole('checkbox', { name: 'Ana' }));
    expect(setFilters).toHaveBeenLastCalledWith({ audit_usuarios: ['6', '5'] });
    await userEvent.click(screen.getByRole('checkbox', { name: 'Beto' }));
    expect(setFilters).toHaveBeenLastCalledWith({ audit_usuarios: [] });
    await userEvent.click(screen.getByRole('checkbox', { name: 'Activar Rebate' }));
    expect(setFilters).toHaveBeenLastCalledWith({ audit_tipos: ['activar_rebate'] });
  });

  it('shows a removable chip per active value, with the user name, and a control that clears them all', async () => {
    const setFilters = vi.fn();
    render(
      <AuditFilters
        filters={filters({ audit_usuarios: ['5'], audit_tipos: ['activar_rebate'], audit_desde: '2026-10-20T09:00' })}
        setFilters={setFilters}
      />,
    );
    await waitFor(() => expect(screen.getByRole('button', { name: 'Quitar Usuario: Ana' })).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Filtros de auditoría (3 activos)' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Quitar Desde: 20/10/2026 09:00' }));
    expect(setFilters).toHaveBeenLastCalledWith({ audit_desde: '' });
    await userEvent.click(screen.getByRole('button', { name: 'Quitar Tipo: Activar Rebate' }));
    expect(setFilters).toHaveBeenLastCalledWith({ audit_tipos: [] });
    await userEvent.click(screen.getByRole('button', { name: /Limpiar auditoría/ }));
    expect(setFilters).toHaveBeenLastCalledWith(EMPTY_AUDIT_FILTERS);
  });

  it("shows a bare date from a link in its input, as the whole day the backend reads", async () => {
    render(<AuditFilters filters={filters({ audit_desde: '2026-10-20', audit_hasta: '2026-10-21' })} setFilters={vi.fn()} />);
    await openPanel();
    expect(screen.getByLabelText('Desde')).toHaveValue('2026-10-20T00:00');
    expect(screen.getByLabelText('Hasta')).toHaveValue('2026-10-21T23:59');
  });

  it('asks the users and kinds again when the panel reopens after a failed load', async () => {
    api.get.mockRejectedValueOnce(new Error('offline'));
    render(<AuditFilters filters={filters()} setFilters={vi.fn()} />);
    await openPanel();
    expect(await screen.findByText(/No se pudieron cargar/)).toBeInTheDocument();
    await openPanel(); // closes
    await openPanel();
    expect(await screen.findByRole('checkbox', { name: 'Ana' })).toBeInTheDocument();
  });

  it('shows no chips and asks nothing while no audit filter is active', () => {
    render(<AuditFilters filters={filters()} setFilters={vi.fn()} />);
    expect(screen.queryByRole('button', { name: /Limpiar auditoría/ })).not.toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalled();
  });
});
