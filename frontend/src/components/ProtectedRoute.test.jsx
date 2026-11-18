import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import ProtectedRoute from './ProtectedRoute';

let authState;

vi.mock('../store/authStore', () => ({
  useAuthStore: (selector) => selector(authState),
}));

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    tienePermiso: () => true,
    tieneAlgunPermiso: () => true,
    tieneTodosPermisos: () => true,
    loading: false,
    initialized: true,
    error: null,
    recargar: vi.fn(),
    rol: 'ADMIN',
  }),
}));

function LoginEspia() {
  const location = useLocation();
  const from = location.state?.from;
  return <div>{`LOGIN from=${from ? `${from.pathname}${from.search}` : 'ninguno'}`}</div>;
}

function renderAt(entrada) {
  return render(
    <MemoryRouter initialEntries={[entrada]}>
      <Routes>
        <Route path="/login" element={<LoginEspia />} />
        <Route path="/mcp/autorizar" element={<ProtectedRoute><div>CONSENTIMIENTO</div></ProtectedRoute>} />
      </Routes>
    </MemoryRouter>
  );
}

beforeEach(() => {
  authState = { token: null, user: null };
});

describe('ProtectedRoute', () => {
  it('sends a visitor without a session to /login remembering where they were going', () => {
    renderAt('/mcp/autorizar?req=abc');
    expect(screen.getByText('LOGIN from=/mcp/autorizar?req=abc')).toBeInTheDocument();
  });

  it('renders the protected content when there is a session', () => {
    authState = { token: 't', user: { rol: 'ADMIN' } };
    renderAt('/mcp/autorizar?req=abc');
    expect(screen.getByText('CONSENTIMIENTO')).toBeInTheDocument();
  });
});
