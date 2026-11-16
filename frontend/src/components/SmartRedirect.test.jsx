import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom';
import SmartRedirect from './SmartRedirect';

let permisos = new Set();

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    tienePermiso: (codigo) => permisos.has(codigo),
    loading: false,
    initialized: true,
  }),
}));

function Donde() {
  const location = useLocation();
  return <div>{`EN ${location.pathname}${location.search}`}</div>;
}

function renderAt() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<SmartRedirect />} />
        <Route path="/productos" element={<div>PRODUCTOS</div>} />
        <Route path="/ml-publicaciones" element={<div>PUBLICACIONES</div>} />
        <Route path="/tienda" element={<div>TIENDA</div>} />
        <Route path="/fichaje" element={<div>FICHAJE</div>} />
        <Route path="/login" element={<div>LOGIN</div>} />
        <Route path="/metricas-ml" element={<Donde />} />
        <Route path="/dashboard-ventas-fuera" element={<Donde />} />
        <Route path="/dashboard-tienda-nube" element={<Donde />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('SmartRedirect — Publicaciones ML', () => {
  it('lands a user whose only access is ml_ops.ver on /ml-publicaciones', () => {
    permisos = new Set(['ml_ops.ver']);
    renderAt();
    expect(screen.getByText('PUBLICACIONES')).toBeInTheDocument();
  });

  it('lands a productos.ver user on /ml-publicaciones, not /productos', () => {
    permisos = new Set(['productos.ver']);
    renderAt();
    expect(screen.getByText('PUBLICACIONES')).toBeInTheDocument();
  });

  it('puts /ml-publicaciones ahead of every other landing', () => {
    permisos = new Set(['productos.ver', 'productos.ver_tienda', 'ml_ops.ver']);
    renderAt();
    expect(screen.getByText('PUBLICACIONES')).toBeInTheDocument();
  });

  it('keeps the next landing for users without productos.ver or ml_ops.ver', () => {
    permisos = new Set(['productos.ver_tienda']);
    renderAt();
    expect(screen.getByText('TIENDA')).toBeInTheDocument();
  });
});

describe('SmartRedirect — Ventas por fuera (ODD vpf-metricas-canal-fe S4)', () => {
  it('lands a ventas_fuera.ver_metricas_pdf user on the board with canal=fuera', () => {
    permisos = new Set(['ventas_fuera.ver_metricas_pdf']);
    renderAt();
    expect(screen.getByText('EN /metricas-ml?canal=fuera')).toBeInTheDocument();
  });

  it('no longer sends the old ventas_fuera.ver_dashboard to the retired dashboard', () => {
    permisos = new Set(['ventas_fuera.ver_dashboard', 'ventas_tn.ver_dashboard']);
    renderAt();
    expect(screen.getByText('EN /dashboard-tienda-nube')).toBeInTheDocument();
  });
});
