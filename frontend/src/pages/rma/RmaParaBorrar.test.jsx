/**
 * RMA "Para borrar" (owner, 2026-11-03): "necesito una vista sencilla de rma donde se vean los pedidos que se
 * marcan parar borrar ... y que tenga un tilde cuando ya se revisó para que no aparezca más" ... "(con un filtro
 * claro)". A Pendientes / Revisados / Todos filter with counts, and a "Revisado" checkbox per row that only users
 * with rma.gestionar see.
 *
 * Grouped by ML operation (owner, 2026-11-06): "si pueden traer el número de envío de la operación ... y cuando es
 * un mismo pedido agruparlo juntos, no mostrar dos líneas, si bien son 2 RMA serían una misma operación". One row
 * per operation with its cases, articles and shipping number; its tick reviews every case of the row.
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

// The list answers one item per operation; a case alone is an operation of its own.
const op = (caso, extra = {}) => ({
  clave: `caso:${caso.id}`,
  ml_id: caso.ml_id,
  numero_envio: null,
  cliente_nombre: caso.cliente_nombre,
  revisado: Boolean(caso.borrar_revisado_at),
  casos: [caso],
  ...extra,
});
const ROW_URL = '/rma-seguimiento/para-borrar/revisado';

beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockImplementation((_url, { params }) => {
    const items = { pendientes: [op(PENDIENTE)], revisados: [op(REVISADO)], todos: [op(REVISADO), op(PENDIENTE)] }[
      params.estado
    ];
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
    api.put.mockResolvedValue({ data: [{ ...PENDIENTE, borrar_revisado_at: '2026-11-03T10:00:00Z' }] });
    render(<RmaParaBorrar puedeGestionar />);
    const row = (await screen.findByText('RMA-2026-0001')).closest('tr');

    await userEvent.click(within(row).getByRole('checkbox', { name: 'Revisado RMA-2026-0001' }));

    expect(api.put).toHaveBeenCalledWith(ROW_URL, { caso_ids: [1], revisado: true });
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
  });

  it('unticking a reviewed case sends revisado false', async () => {
    api.put.mockResolvedValue({ data: [{ ...REVISADO, borrar_revisado_at: null }] });
    render(<RmaParaBorrar puedeGestionar />);
    await screen.findByText('RMA-2026-0001');
    await userEvent.click(screen.getByRole('button', { name: 'Revisados (1)' }));
    const checkbox = await screen.findByRole('checkbox', { name: 'Revisado RMA-2026-0002' });
    expect(checkbox).toBeChecked();

    await userEvent.click(checkbox);

    expect(api.put).toHaveBeenCalledWith(ROW_URL, { caso_ids: [2], revisado: false });
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
        : Promise.resolve({ data: { items: [op(REVISADO)], counts: COUNTS } }),
    );
    render(<RmaParaBorrar puedeGestionar />);

    await userEvent.click(screen.getByRole('button', { name: 'Revisados' }));
    await screen.findByText('RMA-2026-0002');
    resolvePendientes({ data: { items: [op(PENDIENTE)], counts: COUNTS } });

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
    resolvePut({ data: [] });

    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(3));
    expect(api.get).toHaveBeenLastCalledWith('/rma-seguimiento/para-borrar', { params: { estado: 'revisados' } });
    expect(await screen.findByText('RMA-2026-0002')).toBeInTheDocument();
    expect(screen.queryByText('RMA-2026-0001')).not.toBeInTheDocument();
  });
});

describe('RmaParaBorrar dates', () => {
  it('shows a date-only fecha_caso on its own day in Argentina, not the day before', async () => {
    const previous = globalThis.process.env.TZ;
    globalThis.process.env.TZ = 'America/Argentina/Buenos_Aires';
    try {
      render(<RmaParaBorrar puedeGestionar />);
      const row = (await screen.findByText('RMA-2026-0001')).closest('tr');
      expect(within(row).getByText('01/11/2026')).toBeInTheDocument();
    } finally {
      globalThis.process.env.TZ = previous;
    }
  });
});

describe('RmaParaBorrar second click before the reload lands', () => {
  it('the row shows the saved tick at once, so a second click unticks it', async () => {
    api.put.mockImplementation((_url, { revisado }) =>
      Promise.resolve({
        data: [
          {
            ...PENDIENTE,
            borrar_revisado_at: revisado ? '2026-11-03T10:00:00Z' : null,
            borrar_revisado_por_nombre: revisado ? 'Ana' : null,
          },
        ],
      }),
    );
    render(<RmaParaBorrar puedeGestionar />);
    await screen.findByText('RMA-2026-0001');
    // The reload after the tick never answers: the row must show the PUT's answer by itself.
    api.get.mockImplementation(() => new Promise(() => {}));

    await userEvent.click(screen.getByRole('checkbox', { name: 'Revisado RMA-2026-0001' }));
    const checkbox = await screen.findByRole('checkbox', { name: 'Revisado RMA-2026-0001' });
    await waitFor(() => expect(checkbox).toBeChecked());
    await userEvent.click(checkbox);

    expect(api.put).toHaveBeenNthCalledWith(1, ROW_URL, { caso_ids: [1], revisado: true });
    expect(api.put).toHaveBeenNthCalledWith(2, ROW_URL, { caso_ids: [1], revisado: false });
  });
});

describe('RmaParaBorrar timestamp format', () => {
  it('shows who reviewed and the zero-padded day of the review', async () => {
    render(<RmaParaBorrar puedeGestionar />);
    await screen.findByText('RMA-2026-0001');
    await userEvent.click(screen.getByRole('button', { name: 'Revisados (1)' }));
    const row = (await screen.findByText('RMA-2026-0002')).closest('tr');
    expect(within(row).getByText('Ana · 02/11/2026')).toBeInTheDocument();
  });
});

describe('RmaParaBorrar one row per operation', () => {
  // Two RMAs for the two articles of one ML cart, the second already reviewed: the operation is still pending.
  const A = { ...PENDIENTE, id: 11, numero_caso: 'RMA-2026-0011', ml_id: '2000000000000002', articulos: ['Router AX1500'] };
  const B = {
    ...REVISADO,
    id: 12,
    numero_caso: 'RMA-2026-0012',
    ml_id: '2000000000000003',
    articulos: ['Repetidor RE200'],
  };
  const CARRITO = op(B, {
    clave: 'op:2000000000000001',
    ml_id: B.ml_id,
    numero_envio: '40000000001',
    revisado: false,
    casos: [B, A],
  });

  beforeEach(() => {
    api.get.mockResolvedValue({ data: { items: [CARRITO], counts: { pendientes: 1, revisados: 0, todos: 1 } } });
  });

  it('shows the cases, articles and shipping number of the operation in one row', async () => {
    render(<RmaParaBorrar puedeGestionar />);

    const row = (await screen.findByText('RMA-2026-0011')).closest('tr');
    expect(within(row).getByText('RMA-2026-0012')).toBeInTheDocument();
    expect(within(row).getByText('Router AX1500')).toBeInTheDocument();
    expect(within(row).getByText('Repetidor RE200')).toBeInTheDocument();
    expect(within(row).getByText('40000000001')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Envío' })).toBeInTheDocument();
    expect(screen.getAllByRole('row')).toHaveLength(2);
  });

  it('a row with some cases reviewed is unticked and says how many', async () => {
    render(<RmaParaBorrar puedeGestionar />);

    const checkbox = await screen.findByRole('checkbox', { name: 'Revisado RMA-2026-0012, RMA-2026-0011' });
    expect(checkbox).not.toBeChecked();
    expect(screen.getByText('1 de 2 revisados')).toBeInTheDocument();
  });

  it('ticking the row reviews all its cases at once', async () => {
    api.put.mockResolvedValue({ data: [B, { ...A, borrar_revisado_at: '2026-11-06T10:00:00Z' }] });
    render(<RmaParaBorrar puedeGestionar />);
    const checkbox = await screen.findByRole('checkbox', { name: 'Revisado RMA-2026-0012, RMA-2026-0011' });
    // The reload after the tick never answers: the row must show the PUT's answer by itself.
    api.get.mockImplementation(() => new Promise(() => {}));

    await userEvent.click(checkbox);

    expect(api.put).toHaveBeenCalledWith(ROW_URL, { caso_ids: [12, 11], revisado: true });
    await waitFor(() =>
      expect(screen.getByRole('checkbox', { name: 'Revisado RMA-2026-0012, RMA-2026-0011' })).toBeChecked(),
    );
  });

  it('a case with no stored sale shows a dash as its shipping number', async () => {
    api.get.mockResolvedValue({ data: { items: [op(PENDIENTE)], counts: COUNTS } });
    render(<RmaParaBorrar puedeGestionar />);

    const row = (await screen.findByText('RMA-2026-0001')).closest('tr');
    const envio = within(row).getAllByRole('cell')[4];
    expect(envio).toHaveTextContent('—');
  });
});
