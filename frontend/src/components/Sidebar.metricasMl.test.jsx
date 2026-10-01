/**
 * ODD `metricas-ml-tablero` (naming decision 2026-10-01): the NEW board is
 * "Métricas ML" with a "Nuevo" badge; the old dashboard keeps its URL as
 * "Métricas ML (anterior)". Each entry gated by its own permission.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import Sidebar from './Sidebar';

const mockTienePermiso = vi.fn();

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    tienePermiso: (codigo) => mockTienePermiso(codigo),
    tieneAlgunPermiso: () => false,
  }),
  PermisosProvider: ({ children }) => children,
}));

beforeEach(() => {
  vi.clearAllMocks();
});

async function openReportes() {
  const user = userEvent.setup();
  renderWithRouter(<Sidebar />, { initialEntries: ['/'] });
  await user.click(screen.getByText('Reportes'));
}

describe('Sidebar — Métricas ML entries', () => {
  it('links the new board as "Métricas ML" with a "Nuevo" badge, and the old one as "(anterior)"', async () => {
    mockTienePermiso.mockImplementation((codigo) => ['ml_metricas.ver', 'ventas_ml.ver_dashboard'].includes(codigo));
    await openReportes();

    const nueva = screen.getByRole('link', { name: /^Métricas ML\s*Nuevo$/ });
    expect(nueva).toHaveAttribute('href', '/metricas-ml');
    expect(within(nueva).getByText('Nuevo')).toBeInTheDocument();
    const anterior = screen.getByRole('link', { name: 'Métricas ML (anterior)' });
    expect(anterior).toHaveAttribute('href', '/dashboard-metricas-ml');
  });

  it('hides the new board without ml_metricas.ver', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo === 'ventas_ml.ver_dashboard');
    await openReportes();

    expect(screen.queryByRole('link', { name: /^Métricas ML\s*Nuevo$/ })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Métricas ML (anterior)' })).toBeInTheDocument();
  });
});
