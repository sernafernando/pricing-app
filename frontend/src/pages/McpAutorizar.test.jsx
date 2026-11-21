import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import api from '../services/api';
import McpAutorizar from './McpAutorizar';

// setup.js stubs the api module globally; use the real one so the endpoint paths
// of the API helpers are part of the test (the axios calls are spied below).
vi.unmock('../services/api');

vi.mock('../store/authStore', () => ({
  useAuthStore: (selector) => selector({ user: { nombre: 'Ana Pérez', username: 'ana' } }),
}));

const PEDIDO = {
  client_name: 'ChatGPT',
  scope: 'pricing.read',
  expires_at: '2026-11-18T12:10:00Z',
  redirect_host: 'chatgpt.com',
  redirect_local: false,
};
const REDIRECT = 'https://chatgpt.example/connector/oauth/callback?code=c&state=s';
const VENCIDO = 'El pedido de conexión venció o ya se usó. Volvé a conectar desde la aplicación de IA.';

function errorHttp(status) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status, data: { detail: 'x' } } });
}

function renderPagina(url = '/mcp/autorizar?req=abc') {
  const irA = vi.fn();
  render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/mcp/autorizar" element={<McpAutorizar irA={irA} />} />
      </Routes>
    </MemoryRouter>
  );
  return { irA };
}

beforeEach(() => {
  vi.spyOn(api, 'get').mockResolvedValue({ data: PEDIDO });
  vi.spyOn(api, 'post').mockResolvedValue({ data: { redirect_to: REDIRECT } });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('McpAutorizar', () => {
  it('shows who is connecting, read only, with the same permissions, as the logged user', async () => {
    renderPagina();
    expect(await screen.findByText(/ChatGPT/, { selector: 'strong' })).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/oauth/requests/abc');
    expect(screen.getByText(/solo lectura/)).toBeInTheDocument();
    expect(screen.getByText(/con tus mismos permisos/)).toBeInTheDocument();
    expect(screen.getByText(/Ana Pérez/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Permitir' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancelar' })).toBeInTheDocument();
  });

  it('shows where the connection goes back to and warns to approve only a connection you started', async () => {
    renderPagina();
    expect(await screen.findByText('chatgpt.com')).toBeInTheDocument();
    expect(screen.getByText(/Permití solo si iniciaste vos esta conexión recién/)).toBeInTheDocument();
    expect(screen.queryByText(/en esta computadora/)).not.toBeInTheDocument();
  });

  it('says a local client (Claude Code, Cursor, Gemini CLI) returns to this computer', async () => {
    api.get.mockResolvedValue({
      data: { ...PEDIDO, client_name: 'Claude Code', redirect_host: 'localhost', redirect_local: true },
    });
    renderPagina();
    expect(await screen.findByText(/Claude Code/, { selector: 'strong' })).toBeInTheDocument();
    expect(screen.getByText(/en esta computadora/)).toBeInTheDocument();
    expect(screen.getByText('localhost')).toBeInTheDocument();
  });

  it('approves and sends the browser to the redirect the backend returns', async () => {
    const user = userEvent.setup();
    const { irA } = renderPagina();
    await user.click(await screen.findByRole('button', { name: 'Permitir' }));
    expect(api.post).toHaveBeenCalledWith('/oauth/requests/abc/decision', { approve: true });
    expect(irA).toHaveBeenCalledWith(REDIRECT);
  });

  it('denies and also sends the browser back to the client', async () => {
    const user = userEvent.setup();
    api.post.mockResolvedValue({ data: { redirect_to: `${REDIRECT}&error=access_denied` } });
    const { irA } = renderPagina();
    await user.click(await screen.findByRole('button', { name: 'Cancelar' }));
    expect(api.post).toHaveBeenCalledWith('/oauth/requests/abc/decision', { approve: false });
    expect(irA).toHaveBeenCalledWith(`${REDIRECT}&error=access_denied`);
  });

  it('explains an expired or used request (404) without buttons', async () => {
    api.get.mockRejectedValue(errorHttp(404));
    renderPagina();
    expect(await screen.findByText(VENCIDO)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Permitir' })).not.toBeInTheDocument();
  });

  it('explains a missing permission when approving fails with 403, and does not redirect', async () => {
    const user = userEvent.setup();
    api.post.mockRejectedValue(errorHttp(403));
    const { irA } = renderPagina();
    await user.click(await screen.findByRole('button', { name: 'Permitir' }));
    expect(
      await screen.findByText('No tenés permiso para conectar aplicaciones de IA (mcp.conectar). Pedíselo a un administrador.')
    ).toBeInTheDocument();
    expect(irA).not.toHaveBeenCalled();
  });

  it('treats a request that expired between loading and deciding (404) as expired', async () => {
    const user = userEvent.setup();
    api.post.mockRejectedValue(errorHttp(404));
    const { irA } = renderPagina();
    await user.click(await screen.findByRole('button', { name: 'Permitir' }));
    expect(await screen.findByText(VENCIDO)).toBeInTheDocument();
    expect(irA).not.toHaveBeenCalled();
  });

  describe('write access (scope pricing.write)', () => {
    const SIN_PERMISO_ESCRITURA = 'Solo lectura: no tenés permiso para modificar (mcp.escribir)';

    it('says the app can read and MODIFY, with plan + confirmation and undo in Acciones IA, when the token will write', async () => {
      api.get.mockResolvedValue({
        data: { ...PEDIDO, scope: 'pricing.read pricing.write', escritura_pedida: true, escritura: true },
      });
      renderPagina();
      expect(await screen.findByText(/quiere consultar y MODIFICAR Pricing como/)).toBeInTheDocument();
      expect(
        screen.getByText(/promociones, precios de lista, precios en cuotas, precios mayoristas y pausar o activar publicaciones/)
      ).toBeInTheDocument();
      expect(screen.getByText(/Cada cambio necesita un plan y tu confirmación/)).toBeInTheDocument();
      expect(screen.getByText(/Acciones IA/)).toBeInTheDocument();
      expect(screen.getByText(/Deshacer/)).toBeInTheDocument();
      expect(screen.queryByText(/solo lectura/i)).not.toBeInTheDocument();
      expect(screen.queryByText(SIN_PERMISO_ESCRITURA)).not.toBeInTheDocument();
    });

    it('keeps the read-only wording and explains the missing mcp.escribir when writing was asked but not granted', async () => {
      api.get.mockResolvedValue({
        data: { ...PEDIDO, scope: 'pricing.read pricing.write', escritura_pedida: true, escritura: false },
      });
      renderPagina();
      expect(await screen.findByText(SIN_PERMISO_ESCRITURA)).toBeInTheDocument();
      expect(screen.getByText(/quiere consultar Pricing como/)).toBeInTheDocument();
      expect(screen.getByText(/Acceso de solo lectura: puede consultar, no puede modificar nada/)).toBeInTheDocument();
      expect(screen.queryByText(/MODIFICAR/)).not.toBeInTheDocument();
    });

    it('keeps the plain read-only wording when writing was not asked', async () => {
      api.get.mockResolvedValue({ data: { ...PEDIDO, escritura_pedida: false, escritura: false } });
      renderPagina();
      expect(await screen.findByText(/Acceso de solo lectura: puede consultar, no puede modificar nada/)).toBeInTheDocument();
      expect(screen.queryByText(SIN_PERMISO_ESCRITURA)).not.toBeInTheDocument();
      expect(screen.queryByText(/MODIFICAR/)).not.toBeInTheDocument();
      expect(screen.queryByText(/Acciones IA/)).not.toBeInTheDocument();
    });
  });

  it('shows the expired message when the url has no req, without calling the API', async () => {
    renderPagina('/mcp/autorizar');
    expect(await screen.findByText(VENCIDO)).toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalled();
  });
});
