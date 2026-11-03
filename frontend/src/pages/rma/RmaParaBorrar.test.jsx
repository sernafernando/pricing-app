/**
 * RMA "Para borrar" (owner, 2026-11-03): "necesito una vista sencilla de rma donde se vean los pedidos que se
 * marcan parar borrar ... y que tenga un tilde cuando ya se revisó para que no aparezca más" ... "(con un filtro
 * claro)". A Pendientes / Revisados / Todos filter with counts, and a "Revisado" checkbox per row that only users
 * with rma.gestionar see.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import RmaParaBorrar from './RmaParaBorrar';
import api from '../../services/api';

vi.mock('../../services/api', () => ({ default: { get: vi.fn(), put: vi.fn() } }));

const COUNTS = { pendientes: 1, revisados: 1, todos: 2 };
const PENDIENTE = {
  id: 1,
  numero_caso: 'RMA-2026-0001',
  cliente_nombre: 'Juan Pérez',
  ml_id: '2000001',
  estado: 'Abierto',
  fecha_caso: '2026-11-01',
  borrar_revisado_at: null,
  borrar_revisado_por_nombre: null,
};
const REVISADO = {
  ...PENDIENTE,
  id: 2,
  numero_caso: 'RMA-2026-0002',
  borrar_revisado_at: '2026-11-02T15:00:00Z',
  borrar_revisado_por_nombre: 'Ana',
};

beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockImplementation((_url, { params }) => {
    const items = { pendientes: [PENDIENTE], revisados: [REVISADO], todos: [REVISADO, PENDIENTE] }[params.estado];
    return Promise.resolve({ data: { items, counts: COUNTS } });
  });
});

describe('RmaParaBorrar filter', () => {
  it('opens on Pendientes and shows the count of each filter', async () => {
    render(<RmaParaBorrar puedeGestionar />);

    expect(await screen.findByText('RMA-2026-0001')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/rma-seguimiento/para-borrar', { params: { estado: 'pendientes' } });
    expect(screen.getByRole('button', { name: 'Pendientes (1)' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Revisados (1)' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: 'Todos (2)' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('switching to Revisados lists the reviewed cases with who reviewed them', async () => {
    render(<RmaParaBorrar puedeGestionar />);
    await screen.findByText('RMA-2026-0001');

    await userEvent.click(screen.getByRole('button', { name: 'Revisados (1)' }));

    const row = (await screen.findByText('RMA-2026-0002')).closest('tr');
    expect(screen.queryByText('RMA-2026-0001')).not.toBeInTheDocument();
    expect(within(row).getByText(/Ana/)).toBeInTheDocument();
    expect(api.get).toHaveBeenLastCalledWith('/rma-seguimiento/para-borrar', { params: { estado: 'revisados' } });
  });
});

describe('RmaParaBorrar Revisado checkbox', () => {
  it('ticking it saves the review and reloads the list', async () => {
    api.put.mockResolvedValue({ data: { ...PENDIENTE, borrar_revisado_at: '2026-11-03T10:00:00Z' } });
    render(<RmaParaBorrar puedeGestionar />);
    const row = (await screen.findByText('RMA-2026-0001')).closest('tr');

    await userEvent.click(within(row).getByRole('checkbox', { name: 'Revisado RMA-2026-0001' }));

    expect(api.put).toHaveBeenCalledWith('/rma-seguimiento/1/borrar-revisado', { revisado: true });
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
  });

  it('unticking a reviewed case sends revisado false', async () => {
    api.put.mockResolvedValue({ data: { ...REVISADO, borrar_revisado_at: null } });
    render(<RmaParaBorrar puedeGestionar />);
    await screen.findByText('RMA-2026-0001');
    await userEvent.click(screen.getByRole('button', { name: 'Revisados (1)' }));
    const checkbox = await screen.findByRole('checkbox', { name: 'Revisado RMA-2026-0002' });
    expect(checkbox).toBeChecked();

    await userEvent.click(checkbox);

    expect(api.put).toHaveBeenCalledWith('/rma-seguimiento/2/borrar-revisado', { revisado: false });
  });

  it('without rma.gestionar there is no checkbox', async () => {
    render(<RmaParaBorrar puedeGestionar={false} />);
    await screen.findByText('RMA-2026-0001');
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });
});

describe('RmaParaBorrar stale answers', () => {
  it('an older answer that arrives late does not overwrite the current filter', async () => {
    let resolvePendientes;
    api.get.mockImplementation((_url, { params }) =>
      params.estado === 'pendientes'
        ? new Promise((resolve) => {
            resolvePendientes = resolve;
          })
        : Promise.resolve({ data: { items: [REVISADO], counts: COUNTS } }),
    );
    render(<RmaParaBorrar puedeGestionar />);

    await userEvent.click(screen.getByRole('button', { name: 'Revisados' }));
    await screen.findByText('RMA-2026-0002');
    resolvePendientes({ data: { items: [PENDIENTE], counts: COUNTS } });

    await waitFor(() => expect(screen.getByRole('button', { name: 'Revisados (1)' })).toBeInTheDocument());
    expect(screen.getByText('RMA-2026-0002')).toBeInTheDocument();
    expect(screen.queryByText('RMA-2026-0001')).not.toBeInTheDocument();
  });
});

describe('RmaParaBorrar tick then filter change', () => {
  it('a tick that finishes after the filter changed reloads the current filter, not the old one', async () => {
    let resolvePut;
    api.put.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvePut = resolve;
        }),
    );
    render(<RmaParaBorrar puedeGestionar />);
    const row = (await screen.findByText('RMA-2026-0001')).closest('tr');

    await userEvent.click(within(row).getByRole('checkbox', { name: 'Revisado RMA-2026-0001' }));
    await userEvent.click(screen.getByRole('button', { name: 'Revisados (1)' }));
    await screen.findByText('RMA-2026-0002');
    resolvePut({ data: {} });

    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(3));
    expect(api.get).toHaveBeenLastCalledWith('/rma-seguimiento/para-borrar', { params: { estado: 'revisados' } });
    expect(await screen.findByText('RMA-2026-0002')).toBeInTheDocument();
    expect(screen.queryByText('RMA-2026-0001')).not.toBeInTheDocument();
  });
});
