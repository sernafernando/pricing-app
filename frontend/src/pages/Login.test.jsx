import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import Login from './Login';

const login = vi.fn();

vi.mock('../store/authStore', () => ({
  useAuthStore: (selector) => selector({ login }),
}));

function Donde() {
  const location = useLocation();
  return <div>{`EN ${location.pathname}${location.search}`}</div>;
}

function renderLogin(state) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: '/login', state }]}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="*" element={<Donde />} />
      </Routes>
    </MemoryRouter>
  );
}

async function ingresar() {
  const user = userEvent.setup();
  await user.type(screen.getByPlaceholderText('usuario o tu@email.com'), 'ana');
  await user.type(screen.getByPlaceholderText('••••••••'), 'secreto');
  await user.click(screen.getByRole('button', { name: 'Iniciar Sesión' }));
}

beforeEach(() => {
  login.mockReset();
  login.mockResolvedValue({ success: true });
});

describe('Login', () => {
  it('goes to / after a normal login, as before', async () => {
    renderLogin(undefined);
    await ingresar();
    expect(login).toHaveBeenCalledWith('ana', 'secreto');
    expect(await screen.findByText('EN /')).toBeInTheDocument();
  });

  it('returns to the page that asked for the login when it is a safe app path', async () => {
    renderLogin({ from: { pathname: '/mcp/autorizar', search: '?req=abc' } });
    await ingresar();
    expect(await screen.findByText('EN /mcp/autorizar?req=abc')).toBeInTheDocument();
  });

  it.each([
    [{ pathname: '//evil.com', search: '' }],
    ['https://evil.com'],
    ['/\\evil'],
  ])('ignores an unsafe return path %j and goes to /', async (from) => {
    renderLogin({ from });
    await ingresar();
    expect(await screen.findByText('EN /')).toBeInTheDocument();
  });

  it('shows the error and stays on the login when the credentials fail', async () => {
    login.mockResolvedValue({ success: false, error: 'Usuario o contraseña incorrectos' });
    renderLogin({ from: { pathname: '/mcp/autorizar', search: '?req=abc' } });
    await ingresar();
    expect(await screen.findByText('Usuario o contraseña incorrectos')).toBeInTheDocument();
    expect(screen.queryByText(/^EN /)).not.toBeInTheDocument();
  });
});
