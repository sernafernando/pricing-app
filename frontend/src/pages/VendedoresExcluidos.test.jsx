/**
 * Vendedores excluidos (/dashboard-ventas-fuera/vendedores-excluidos; ODD `vpf-metricas-canal-fe` S4): the admin
 * that lived in the old Ventas por fuera dashboard's Admin tab, now on its own route. Same access as that tab: the
 * route's `ventas_fuera.ver_dashboard` plus the ADMIN or SUPERADMIN role (the backend refuses everyone else).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import api from '../services/api';
import VendedoresExcluidos from './VendedoresExcluidos';

vi.mock('../services/api', () => ({
  default: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

const { auth } = vi.hoisted(() => ({ auth: { user: { rol: 'ADMIN' } } }));
vi.mock('../store/authStore', () => ({
  useAuthStore: (selector) => (typeof selector === 'function' ? selector(auth) : auth),
}));

function renderPage() {
  render(
    <MemoryRouter>
      <VendedoresExcluidos />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockResolvedValue({ data: [{ sm_id: 4, sm_name: 'VENDEDOR ML', motivo: 'Ventas de ML', created_at: '2026-10-01T10:00:00' }] });
});

describe('Vendedores excluidos page', () => {
  it('shows the existing admin (TabAdminVentasFuera) to an ADMIN, with a way back to the PDF loads', async () => {
    auth.user = { rol: 'ADMIN' };
    renderPage();
    expect(screen.getByRole('heading', { level: 1, name: 'Vendedores excluidos' })).toBeInTheDocument();
    expect(await screen.findByText('VENDEDOR ML')).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/vendedores-excluidos');
    expect(screen.getByRole('link', { name: 'Cargas de PDF' })).toHaveAttribute('href', '/metricas-ml/cargas');
  });

  it('keeps the old tab rule: other roles see a notice and the list is never requested', () => {
    auth.user = { rol: 'VENTAS' };
    renderPage();
    expect(screen.getByText('Solo un administrador puede gestionar los vendedores excluidos.')).toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalled();
  });
});
