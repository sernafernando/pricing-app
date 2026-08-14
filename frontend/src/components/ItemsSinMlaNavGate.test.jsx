/**
 * UI5 / D9 (tn-publisher-module PR-2): the "Items sin MLA" nav entry in
 * `Navbar.jsx`, `Sidebar.jsx`, and the redirect priority list in
 * `SmartRedirect.jsx` were gated on `admin.gestionar_mla_banlist`, while the
 * route guard in `App.jsx` requires `admin.ver_items_sin_mla`. A user
 * holding the route permission but not the banlist one got no nav entry at
 * all — and was skipped by `SmartRedirect`'s priority scan. All three MUST
 * gate on `admin.ver_items_sin_mla`, matching the route guard.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import Navbar from './Navbar';
import Sidebar from './Sidebar';
import SmartRedirect from './SmartRedirect';

let permisosDelUsuario = new Set();
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: Array.from(permisosDelUsuario),
    tienePermiso: (codigo) => permisosDelUsuario.has(codigo),
    tieneAlgunPermiso: (codigos) => codigos.some((c) => permisosDelUsuario.has(c)),
    cargandoPermisos: false,
    loading: false,
    initialized: true,
  }),
  PermisosProvider: ({ children }) => children,
}));

// Navbar also mounts NotificationBell (needs SSEProvider) and ThemeToggle
// (needs ThemeProvider) — neither is relevant to the nav-gate behavior under
// test, so both are stubbed out rather than wiring two unrelated providers.
vi.mock('./NotificationBell', () => ({ default: () => null }));
vi.mock('./ThemeToggle', () => ({ default: () => null }));

function renderWithRouter(ui) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

describe('Items sin MLA nav gate matches the route gate (admin.ver_items_sin_mla)', () => {
  describe('Navbar', () => {
    it('shows the entry for a user with admin.ver_items_sin_mla but not admin.gestionar_mla_banlist', () => {
      permisosDelUsuario = new Set(['admin.ver_items_sin_mla']);
      renderWithRouter(<Navbar />);
      expect(screen.getByText('Items sin MLA')).toBeInTheDocument();
    });

    it('hides the entry for a user with only admin.gestionar_mla_banlist', () => {
      permisosDelUsuario = new Set(['admin.gestionar_mla_banlist']);
      renderWithRouter(<Navbar />);
      expect(screen.queryByText('Items sin MLA')).not.toBeInTheDocument();
    });
  });

  describe('Sidebar', () => {
    it('shows the entry for a user with admin.ver_items_sin_mla but not admin.gestionar_mla_banlist', () => {
      permisosDelUsuario = new Set(['admin.ver_items_sin_mla']);
      renderWithRouter(<Sidebar />);
      expect(screen.getByText('Items sin MLA')).toBeInTheDocument();
    });

    it('hides the entry for a user with only admin.gestionar_mla_banlist', () => {
      permisosDelUsuario = new Set(['admin.gestionar_mla_banlist']);
      renderWithRouter(<Sidebar />);
      expect(screen.queryByText('Items sin MLA')).not.toBeInTheDocument();
    });
  });

  describe('SmartRedirect', () => {
    // `/mla-banlist` (still gated on admin.gestionar_mla_banlist, unchanged)
    // is checked BEFORE `/items-sin-mla` in SmartRedirect's priority list, so
    // a user holding only admin.gestionar_mla_banlist always lands there
    // regardless of this fix — the only permission combination that actually
    // distinguishes old vs. new gating is admin.ver_items_sin_mla alone.
    it('routes a user with only admin.ver_items_sin_mla to /items-sin-mla', () => {
      permisosDelUsuario = new Set(['admin.ver_items_sin_mla']);
      render(
        <MemoryRouter initialEntries={['/']}>
          <Routes>
            <Route path="/" element={<SmartRedirect />} />
            <Route path="/items-sin-mla" element={<div>ITEMS_SIN_MLA_PAGE</div>} />
            <Route path="/fichaje" element={<div>FICHAJE_PAGE</div>} />
          </Routes>
        </MemoryRouter>,
      );
      expect(screen.getByText('ITEMS_SIN_MLA_PAGE')).toBeInTheDocument();
    });
  });
});
