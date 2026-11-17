/**
 * ODD `vpf-metricas-canal-fe` S4/C4: "Ventas por Fuera" opens /metricas-ml?canal=fuera with
 * `ventas_fuera.ver_metricas_pdf`, and "Cargas de PDF" opens the upload history with either PDF permission.
 * The sidebar marks one item active: a query-string item ("Ventas por Fuera") when the URL carries its query,
 * the plain one ("Métricas ML") otherwise.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouter } from '../test/renderWithRouter';
import Sidebar from './Sidebar';

const { granted } = vi.hoisted(() => ({ granted: { set: new Set() } }));

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    tienePermiso: (codigo) => granted.set.has(codigo),
    tieneAlgunPermiso: (codigos) => codigos.some((c) => granted.set.has(c)),
  }),
  PermisosProvider: ({ children }) => children,
}));

vi.mock('../services/api', () => ({
  marcasPmAPI: { misTitularidades: vi.fn(() => Promise.resolve({ data: { total: 0 } })) },
}));

beforeEach(() => {
  vi.clearAllMocks();
});

async function openReportes(codigos, entry = '/') {
  granted.set = new Set(codigos);
  const user = userEvent.setup();
  renderWithRouter(<Sidebar />, { initialEntries: [entry] });
  // The section opens by itself when one of its items is active.
  if (!screen.queryByRole('link', { name: /^Tienda Nube/ }) && !screen.queryByRole('link', { name: /Ventas por Fuera|Cargas de PDF/ })) {
    await user.click(screen.getByText('Reportes'));
  }
}

const tokens = (link) => new Set(link.className.split(/\s+/).filter(Boolean));

describe('Sidebar — Ventas por Fuera opens the board with canal=fuera', () => {
  it('links /metricas-ml?canal=fuera with ventas_fuera.ver_metricas_pdf', async () => {
    await openReportes(['ventas_fuera.ver_metricas_pdf']);
    expect(screen.getByRole('link', { name: 'Ventas por Fuera' })).toHaveAttribute('href', '/metricas-ml?canal=fuera');
  });

  it('is gone for the old ventas_fuera.ver_dashboard alone', async () => {
    await openReportes(['ventas_fuera.ver_dashboard', 'ventas_tn.ver_dashboard']);
    expect(screen.queryByRole('link', { name: 'Ventas por Fuera' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /dashboard-ventas-fuera/ })).not.toBeInTheDocument();
  });

  it('lists "Cargas de PDF" for subir_pdf or ver_metricas_pdf', async () => {
    await openReportes(['ventas_fuera.subir_pdf']);
    expect(screen.getByRole('link', { name: 'Cargas de PDF' })).toHaveAttribute('href', '/metricas-ml/cargas');
    expect(screen.queryByRole('link', { name: 'Ventas por Fuera' })).not.toBeInTheDocument();
  });
});

describe('Sidebar — active item with a query string', () => {
  const ALL = ['ml_metricas.ver', 'ventas_fuera.ver_metricas_pdf', 'ventas_fuera.subir_pdf', 'ventas_tn.ver_dashboard'];

  it('marks Ventas por Fuera, not Métricas ML, on /metricas-ml?canal=fuera', async () => {
    await openReportes(ALL, '/metricas-ml?canal=fuera&vendedores=Ana');
    const fuera = tokens(screen.getByRole('link', { name: 'Ventas por Fuera' }));
    const ml = tokens(screen.getByRole('link', { name: /^Métricas ML\s*Nuevo$/ }));
    const tn = tokens(screen.getByRole('link', { name: 'Tienda Nube' }));
    expect(ml).toEqual(tn);
    expect(fuera.size).toBeGreaterThan(tn.size);
  });

  it('keeps Métricas ML active on /metricas-ml with any other query (previous behavior)', async () => {
    await openReportes(ALL, '/metricas-ml?canal=todo&periodo=7d');
    const fuera = tokens(screen.getByRole('link', { name: 'Ventas por Fuera' }));
    const ml = tokens(screen.getByRole('link', { name: /^Métricas ML\s*Nuevo$/ }));
    const tn = tokens(screen.getByRole('link', { name: 'Tienda Nube' }));
    expect(fuera).toEqual(tn);
    expect(ml.size).toBeGreaterThan(tn.size);
  });

  it('marks Cargas de PDF on its own path', async () => {
    await openReportes(ALL, '/metricas-ml/cargas');
    const cargas = tokens(screen.getByRole('link', { name: 'Cargas de PDF' }));
    const tn = tokens(screen.getByRole('link', { name: 'Tienda Nube' }));
    expect(cargas.size).toBeGreaterThan(tn.size);
  });
});
