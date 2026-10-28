/**
 * Entry-point test for the curation panel link (tickets-triage-feedback
 * PR5b): a user WITHOUT tickets.triage.ejemplos must see no "Ejemplos de
 * Corrección" link anywhere in the tickets sidebar section.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import Sidebar from './Sidebar';

const mockTienePermiso = vi.fn();
const mockTieneAlgunPermiso = vi.fn(() => false);

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    tienePermiso: (codigo) => mockTienePermiso(codigo),
    tieneAlgunPermiso: (codigos) => mockTieneAlgunPermiso(codigos),
  }),
  PermisosProvider: ({ children }) => children,
}));

beforeEach(() => {
  vi.clearAllMocks();
});

describe('Sidebar — curation link entry point', () => {
  it('hides "Ejemplos de Corrección" when the user lacks tickets.triage.ejemplos', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo === 'tickets.ver');
    const user = userEvent.setup();
    renderWithRouter(<Sidebar />, { initialEntries: ['/tickets'] });
    await user.click(screen.getByText('Tickets'));
    expect(screen.queryByText('Ejemplos de Corrección')).not.toBeInTheDocument();
  });

  it('shows "Ejemplos de Corrección" when the user has tickets.triage.ejemplos', async () => {
    mockTienePermiso.mockImplementation((codigo) => codigo === 'tickets.triage.ejemplos');
    const user = userEvent.setup();
    renderWithRouter(<Sidebar />, { initialEntries: ['/tickets'] });
    await user.click(screen.getByText('Tickets'));
    expect(screen.getByText('Ejemplos de Corrección')).toBeInTheDocument();
  });
});

describe('Sidebar — Publicaciones ML entry (go-live)', () => {
  async function openReportes() {
    const user = userEvent.setup();
    renderWithRouter(<Sidebar />, { initialEntries: ['/'] });
    await user.click(screen.getByText('Reportes'));
  }
  // The user holds exactly `codigos`, for one permission or any of several.
  const holds = (...codigos) => {
    mockTienePermiso.mockImplementation((codigo) => codigos.includes(codigo));
    mockTieneAlgunPermiso.mockImplementation((asked) => asked.some((codigo) => codigos.includes(codigo)));
  };

  it('links "Publicaciones ML" under Reportes with a "Nuevo" badge for ml_ops.ver', async () => {
    holds('ml_ops.ver');
    await openReportes();
    const link = screen.getByRole('link', { name: /^Publicaciones ML\s*Nuevo$/ });
    expect(link).toHaveAttribute('href', '/ml-publicaciones');
  });

  it("lists it with Productos' productos.ver alone (S12f1: PRICING and VENTAS keep their access)", async () => {
    holds('productos.ver');
    await openReportes();
    expect(screen.getByRole('link', { name: /^Publicaciones ML\s*Nuevo$/ })).toHaveAttribute('href', '/ml-publicaciones');
  });

  it('hides "Publicaciones ML" without productos.ver or ml_ops.ver', async () => {
    holds('ml_metricas.ver');
    await openReportes();
    expect(screen.queryByRole('link', { name: /Publicaciones ML/ })).not.toBeInTheDocument();
  });
});
