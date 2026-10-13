import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import SmartRedirect from './SmartRedirect';

let permisos = new Set();

vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    tienePermiso: (codigo) => permisos.has(codigo),
    loading: false,
    initialized: true,
  }),
}));

function renderAt() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<SmartRedirect />} />
        <Route path="/productos" element={<div>PRODUCTOS</div>} />
        <Route path="/ml-publicaciones" element={<div>PUBLICACIONES</div>} />
        <Route path="/fichaje" element={<div>FICHAJE</div>} />
        <Route path="/login" element={<div>LOGIN</div>} />
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

  it('keeps higher-priority landings: productos.ver still goes to /productos', () => {
    permisos = new Set(['productos.ver', 'ml_ops.ver']);
    renderAt();
    expect(screen.getByText('PRODUCTOS')).toBeInTheDocument();
  });
});
