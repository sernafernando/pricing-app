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
