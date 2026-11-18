import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import api from '../../services/api';
import ConexionesMcp from './ConexionesMcp';

// setup.js stubs the api module globally; use the real one so the endpoint paths
// of the API helpers are part of the test (the axios calls are spied below).
vi.unmock('../../services/api');

const CONEXIONES = [
  {
    id: 11,
    usuario_id: 7,
    client_id: 'https://chatgpt.example/oauth/client.json',
    client_name: 'ChatGPT',
    scope: 'pricing.read',
    created_at: '2026-11-18T13:00:00Z',
    last_used_at: null,
  },
  {
    id: 12,
    usuario_id: 7,
    client_id: 'https://otro.example/client.json',
    client_name: 'Otro cliente',
    scope: 'pricing.read',
    created_at: '2026-11-10T13:00:00Z',
    last_used_at: '2026-11-17T15:30:00Z',
  },
];

beforeEach(() => {
  vi.spyOn(api, 'get').mockResolvedValue({ data: CONEXIONES });
  vi.spyOn(api, 'delete').mockResolvedValue({ status: 204 });
  vi.spyOn(window, 'confirm');
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ConexionesMcp', () => {
  it("lists the user's active connections, with 'nunca' when never used", async () => {
    render(<ConexionesMcp usuarioId={7} />);
    expect(await screen.findByText('ChatGPT')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/admin/mcp/connections', { params: { usuario_id: 7 } });
    const filas = screen.getAllByRole('listitem');
    expect(filas).toHaveLength(2);
    expect(within(filas[0]).getByText(/nunca/)).toBeInTheDocument();
    expect(within(filas[1]).getByText('Otro cliente')).toBeInTheDocument();
    expect(within(filas[1]).queryByText(/nunca/)).not.toBeInTheDocument();
  });

  it('shows the empty state', async () => {
    api.get.mockResolvedValue({ data: [] });
    render(<ConexionesMcp usuarioId={7} />);
    expect(await screen.findByText('Sin conexiones activas.')).toBeInTheDocument();
  });

  it('revokes after confirming and removes the row', async () => {
    const user = userEvent.setup();
    render(<ConexionesMcp usuarioId={7} />);
    const fila = (await screen.findByText('ChatGPT')).closest('li');
    await user.click(within(fila).getByRole('button', { name: 'Revocar' }));
    expect(api.delete).not.toHaveBeenCalled();
    expect(within(fila).getByText(/Va a tener que volver a conectarse/)).toBeInTheDocument();
    await user.click(within(fila).getByRole('button', { name: 'Sí, revocar' }));
    expect(window.confirm).not.toHaveBeenCalled();
    expect(api.delete).toHaveBeenCalledWith('/admin/mcp/connections/11');
    expect(screen.queryByText('ChatGPT')).not.toBeInTheDocument();
    expect(screen.getByText('Otro cliente')).toBeInTheDocument();
  });

  it('does nothing when the confirmation is cancelled', async () => {
    const user = userEvent.setup();
    render(<ConexionesMcp usuarioId={7} />);
    const fila = (await screen.findByText('ChatGPT')).closest('li');
    await user.click(within(fila).getByRole('button', { name: 'Revocar' }));
    await user.click(within(fila).getByRole('button', { name: 'Cancelar' }));
    expect(api.delete).not.toHaveBeenCalled();
    expect(within(fila).getByRole('button', { name: 'Revocar' })).toBeInTheDocument();
    expect(screen.getByText('ChatGPT')).toBeInTheDocument();
  });

  it('shows an error when the list cannot load', async () => {
    api.get.mockRejectedValue(new Error('boom'));
    render(<ConexionesMcp usuarioId={7} />);
    expect(await screen.findByText('No se pudieron cargar las conexiones.')).toBeInTheDocument();
  });
});
