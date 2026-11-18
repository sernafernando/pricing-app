import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import api from '../services/api';
import AccionesIa from './AccionesIa';

// setup.js stubs the api module globally; use the real one so the endpoint paths
// and payloads of accionesIaAPI are part of the test (the axios calls are spied below).
vi.unmock('../services/api');

const fila = (over) => ({
  id: 41,
  plan_id: 'p_1',
  created_at: '2026-11-18T15:00:00Z',
  usuario_id: 3,
  usuario_nombre: 'Usuario Demo',
  cliente: 'Claude',
  tool: 'precio_lista_cambiar',
  accion: 'precio_lista',
  objetivo: '12345',
  objetivo_label: 'SKU 12345 - Notebook X',
  antes: { precio: 100000 },
  despues: { precio: 95000 },
  motivo: 'Mejora el markup',
  resultado: 'ok',
  detalle: null,
  deshacible: true,
  deshecha: false,
  undo_of_id: null,
  ...over,
});

const ITEMS = [
  fila(),
  fila({ id: 42, objetivo: '777', objetivo_label: 'SKU 777 - Mouse', antes: { precio: 2000 }, despues: { precio: 2100 } }),
  fila({ id: 43, plan_id: 'p_2', objetivo_label: 'MLA999 - Teclado', accion: 'estado_pausar', tool: 'publicaciones_estado', antes: { estado: 'active' }, despues: { estado: 'paused' }, deshecha: true }),
  fila({ id: 44, plan_id: 'p_3', objetivo_label: 'SKU 555 - Monitor', resultado: 'rechazada', detalle: 'el precio cambió' }),
  fila({ id: 45, plan_id: 'p_4', objetivo_label: 'MLA888 - Silla', accion: 'promo_aplicar', deshacible: false }),
];

const PLAN = {
  plan_id: 'p_undo',
  confirm_token: 'tok-123',
  expires_at: '2026-11-18T15:15:00Z',
  filas: [
    { accion_id: 41, objetivo: '12345', objetivo_label: 'SKU 12345 - Notebook X', accion: 'precio_lista', antes: { precio: 95000 }, despues: { precio: 100000 }, estado: 'lista', detalle: null },
    { accion_id: 42, objetivo: '777', objetivo_label: 'SKU 777 - Mouse', accion: 'precio_lista', antes: { precio: 2100 }, despues: { precio: 2000 }, estado: 'bloqueada', detalle: 'el precio cambió desde la acción' },
  ],
};

let escritura;

function errorHttp(status, detail = 'x') {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status, data: { detail } } });
}

function mockGet() {
  vi.spyOn(api, 'get').mockImplementation((url) => {
    if (url === '/admin/mcp/escritura') return Promise.resolve({ data: escritura });
    if (url === '/admin/mcp/acciones') return Promise.resolve({ data: { total: ITEMS.length, items: ITEMS } });
    return Promise.reject(new Error(`unexpected GET ${url}`));
  });
}

const filaDe = (texto) => screen.getByText(texto).closest('tr');

beforeEach(() => {
  escritura = { habilitado: false, fuente: 'db' };
  mockGet();
  vi.spyOn(api, 'post').mockImplementation((url) => {
    if (url === '/admin/mcp/acciones/deshacer/plan') return Promise.resolve({ data: PLAN });
    if (url === '/admin/mcp/acciones/deshacer/aplicar') {
      return Promise.resolve({
        data: { plan_id: 'p_undo', resultados: [{ accion_id: 41, nueva_accion_id: 57, resultado: 'ok', detalle: null }] },
      });
    }
    return Promise.reject(new Error(`unexpected POST ${url}`));
  });
  vi.spyOn(api, 'put').mockImplementation((url, body) => Promise.resolve({ data: { habilitado: body.habilitado, fuente: 'db' } }));
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('AccionesIa', () => {
  it('lists the actions from the API with before → after, motivo and result', async () => {
    render(<AccionesIa />);
    expect(await screen.findByText('SKU 12345 - Notebook X')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/admin/mcp/acciones', { params: { limit: 50, offset: 0 } });
    const row = filaDe('SKU 12345 - Notebook X');
    expect(within(row).getByText('Usuario Demo')).toBeInTheDocument();
    expect(within(row).getByText('Claude')).toBeInTheDocument();
    expect(within(row).getByText('Precio de lista')).toBeInTheDocument();
    expect(within(row).getByText('precio: 100.000')).toBeInTheDocument();
    expect(within(row).getByText('precio: 95.000')).toBeInTheDocument();
    expect(within(row).getByText('Mejora el markup')).toBeInTheDocument();
    expect(within(row).getByText('OK')).toBeInTheDocument();
    expect(screen.getByText(/1–5 de 5/)).toBeInTheDocument();
  });

  it('shows Deshacer only for undoable, not undone, ok rows', async () => {
    render(<AccionesIa />);
    await screen.findByText('SKU 12345 - Notebook X');
    const deshacer = (texto) => within(filaDe(texto)).queryByRole('button', { name: 'Deshacer' });
    expect(deshacer('SKU 12345 - Notebook X')).toBeInTheDocument();
    expect(deshacer('SKU 777 - Mouse')).toBeInTheDocument();
    expect(deshacer('MLA999 - Teclado')).not.toBeInTheDocument(); // already undone
    expect(within(filaDe('MLA999 - Teclado')).getByText('Deshecha')).toBeInTheDocument();
    expect(deshacer('SKU 555 - Monitor')).not.toBeInTheDocument(); // rechazada
    expect(deshacer('MLA888 - Silla')).not.toBeInTheDocument(); // not deshacible
  });

  it('offers Deshacer plan once per plan with undoable rows', async () => {
    render(<AccionesIa />);
    await screen.findByText('SKU 12345 - Notebook X');
    expect(screen.getAllByRole('button', { name: 'Deshacer plan' })).toHaveLength(1);
    expect(within(filaDe('SKU 12345 - Notebook X')).getByRole('button', { name: 'Deshacer plan' })).toBeInTheDocument();
  });

  it('applies the filters as query params and resets to the first page', async () => {
    const user = userEvent.setup();
    render(<AccionesIa />);
    await screen.findByText('SKU 12345 - Notebook X');
    await user.selectOptions(screen.getByLabelText('Usuario'), '3');
    await user.selectOptions(screen.getByLabelText('Cliente'), 'Claude');
    await user.selectOptions(screen.getByLabelText('Tool'), 'precio_lista_cambiar');
    await user.selectOptions(screen.getByLabelText('Resultado'), 'ok');
    await user.type(screen.getByLabelText('Desde'), '2026-11-01');
    await user.type(screen.getByLabelText('Hasta'), '2026-11-18');
    await waitFor(() =>
      expect(api.get).toHaveBeenLastCalledWith('/admin/mcp/acciones', {
        params: {
          limit: 50,
          offset: 0,
          usuario_id: '3',
          cliente: 'Claude',
          tool: 'precio_lista_cambiar',
          resultado: 'ok',
          desde: '2026-11-01',
          hasta: '2026-11-18',
        },
      })
    );
  });

  it('undoes one row: motivo → plan → shows lista and bloqueada rows → confirm → results and refresh', async () => {
    const user = userEvent.setup();
    render(<AccionesIa />);
    await screen.findByText('SKU 12345 - Notebook X');
    await user.click(within(filaDe('SKU 12345 - Notebook X')).getByRole('button', { name: 'Deshacer' }));

    const modal = await screen.findByRole('dialog', { name: 'Deshacer acción' });
    const preparar = within(modal).getByRole('button', { name: 'Preparar' });
    expect(preparar).toBeDisabled(); // motivo is required
    await user.type(within(modal).getByLabelText('Motivo'), 'La IA se equivocó');
    await user.click(preparar);

    expect(api.post).toHaveBeenCalledWith('/admin/mcp/acciones/deshacer/plan', {
      accion_ids: [41],
      motivo: 'La IA se equivocó',
    });
    const lista = (await within(modal).findByText('SKU 12345 - Notebook X')).closest('tr');
    expect(within(lista).getByText('Lista')).toBeInTheDocument();
    const bloqueada = within(modal).getByText('SKU 777 - Mouse').closest('tr');
    expect(within(bloqueada).getByText('Bloqueada')).toBeInTheDocument();
    expect(within(bloqueada).queryByText('Lista')).not.toBeInTheDocument();
    expect(within(bloqueada).getByText('el precio cambió desde la acción')).toBeInTheDocument();
    expect(within(modal).getByText(/1 de 2 filas se van a deshacer/)).toBeInTheDocument();

    const llamadasAntes = api.get.mock.calls.filter(([url]) => url === '/admin/mcp/acciones').length;
    await user.click(within(modal).getByRole('button', { name: 'Confirmar' }));
    expect(api.post).toHaveBeenCalledWith('/admin/mcp/acciones/deshacer/aplicar', {
      plan_id: 'p_undo',
      confirm_token: 'tok-123',
    });
    const resultado = (await within(modal).findByText(/Acción nueva #57/)).closest('tr');
    expect(within(resultado).getByText('SKU 12345 - Notebook X')).toBeInTheDocument();
    expect(within(resultado).getByText('OK')).toBeInTheDocument();
    await waitFor(() =>
      expect(api.get.mock.calls.filter(([url]) => url === '/admin/mcp/acciones').length).toBe(llamadasAntes + 1)
    );
  });

  it('undoes a whole plan by plan_id', async () => {
    const user = userEvent.setup();
    render(<AccionesIa />);
    await screen.findByText('SKU 12345 - Notebook X');
    await user.click(screen.getByRole('button', { name: 'Deshacer plan' }));
    const modal = await screen.findByRole('dialog', { name: 'Deshacer plan' });
    await user.type(within(modal).getByLabelText('Motivo'), 'Revertir todo');
    await user.click(within(modal).getByRole('button', { name: 'Preparar' }));
    expect(api.post).toHaveBeenCalledWith('/admin/mcp/acciones/deshacer/plan', { plan_id: 'p_1', motivo: 'Revertir todo' });
  });

  it('does not offer Confirmar when every plan row is blocked', async () => {
    const user = userEvent.setup();
    api.post.mockResolvedValueOnce({ data: { ...PLAN, filas: [PLAN.filas[1]] } });
    render(<AccionesIa />);
    await screen.findByText('SKU 12345 - Notebook X');
    await user.click(within(filaDe('SKU 777 - Mouse')).getByRole('button', { name: 'Deshacer' }));
    const modal = await screen.findByRole('dialog', { name: 'Deshacer acción' });
    await user.type(within(modal).getByLabelText('Motivo'), 'x');
    await user.click(within(modal).getByRole('button', { name: 'Preparar' }));
    expect(await within(modal).findByText(/Ninguna fila se puede deshacer/)).toBeInTheDocument();
    expect(within(modal).queryByRole('button', { name: 'Confirmar' })).not.toBeInTheDocument();
  });

  it('explains an expired or used token (409) and lets you prepare a new plan', async () => {
    const user = userEvent.setup();
    render(<AccionesIa />);
    await screen.findByText('SKU 12345 - Notebook X');
    api.post.mockImplementation((url) =>
      url.endsWith('/plan') ? Promise.resolve({ data: PLAN }) : Promise.reject(errorHttp(409, 'token vencido'))
    );
    await user.click(within(filaDe('SKU 12345 - Notebook X')).getByRole('button', { name: 'Deshacer' }));
    const modal = await screen.findByRole('dialog', { name: 'Deshacer acción' });
    await user.type(within(modal).getByLabelText('Motivo'), 'x');
    await user.click(within(modal).getByRole('button', { name: 'Preparar' }));
    await user.click(await within(modal).findByRole('button', { name: 'Confirmar' }));
    expect(await within(modal).findByText(/El plan venció o ya se usó \(token vencido\)/)).toBeInTheDocument();
    expect(within(modal).getByRole('button', { name: 'Preparar' })).toBeEnabled();
  });

  it('explains that writes are off (503) when undoing', async () => {
    const user = userEvent.setup();
    api.post.mockRejectedValueOnce(errorHttp(503));
    render(<AccionesIa />);
    await screen.findByText('SKU 12345 - Notebook X');
    await user.click(within(filaDe('SKU 12345 - Notebook X')).getByRole('button', { name: 'Deshacer' }));
    const modal = await screen.findByRole('dialog', { name: 'Deshacer acción' });
    await user.type(within(modal).getByLabelText('Motivo'), 'x');
    await user.click(within(modal).getByRole('button', { name: 'Preparar' }));
    expect(await within(modal).findByText(/La escritura de la IA está apagada/)).toBeInTheDocument();
  });

  it('shows the permission message when the list answers 403', async () => {
    api.get.mockImplementation((url) =>
      url === '/admin/mcp/escritura' ? Promise.resolve({ data: escritura }) : Promise.reject(errorHttp(403))
    );
    render(<AccionesIa />);
    expect(
      await screen.findByText('No tenés permiso para ver ni deshacer las acciones de la IA (mcp.escribir).')
    ).toBeInTheDocument();
  });

  describe('kill switch', () => {
    it('reads the state and turns AI writes on with PUT', async () => {
      const user = userEvent.setup();
      render(<AccionesIa />);
      const interruptor = await screen.findByRole('switch', { name: 'Permitir que la IA modifique Pricing' });
      expect(api.get).toHaveBeenCalledWith('/admin/mcp/escritura');
      expect(interruptor).toHaveAttribute('aria-checked', 'false');
      expect(screen.getByText('Apagada')).toBeInTheDocument();
      await user.click(interruptor);
      expect(api.put).toHaveBeenCalledWith('/admin/mcp/escritura', { habilitado: true });
      await waitFor(() => expect(interruptor).toHaveAttribute('aria-checked', 'true'));
      expect(screen.getByText('Encendida')).toBeInTheDocument();
    });

    it('is locked when the server kill switch wins', async () => {
      escritura = { habilitado: false, fuente: 'kill_switch' };
      render(<AccionesIa />);
      const interruptor = await screen.findByRole('switch', { name: 'Permitir que la IA modifique Pricing' });
      expect(interruptor).toBeDisabled();
      expect(screen.getByText('Bloqueado por el servidor (kill switch)')).toBeInTheDocument();
    });

    it('shows the server lock when PUT answers it', async () => {
      const user = userEvent.setup();
      api.put.mockResolvedValueOnce({ data: { habilitado: false, fuente: 'kill_switch' } });
      render(<AccionesIa />);
      const interruptor = await screen.findByRole('switch', { name: 'Permitir que la IA modifique Pricing' });
      await user.click(interruptor);
      expect(await screen.findByText('Bloqueado por el servidor (kill switch)')).toBeInTheDocument();
      expect(interruptor).toBeDisabled();
    });

    it('explains a 403 when changing it', async () => {
      const user = userEvent.setup();
      api.put.mockRejectedValueOnce(errorHttp(403));
      render(<AccionesIa />);
      await user.click(await screen.findByRole('switch', { name: 'Permitir que la IA modifique Pricing' }));
      expect(
        await screen.findByText('No tenés permiso para cambiar la escritura de la IA (mcp.escribir).')
      ).toBeInTheDocument();
    });
  });
});
