/**
 * NOTA: vite.config.js corre la suite con `css: false`, así que los nombres de
 * clase de CSS Modules NO resuelven. Nunca asertar sobre className — asertar
 * sobre texto y roles.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

const { getMock, postMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  postMock: vi.fn(),
}));

vi.mock('../services/api', () => ({
  default: { get: getMock, post: postMock },
}));

let mockTienePermiso = () => false;
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({
    permisos: [],
    tienePermiso: (codigo) => mockTienePermiso(codigo),
  }),
}));

const VariosVentaPctModal = (await import('./VariosVentaPctModal')).default;

const HISTORIAL = [
  { id: 2, porcentaje: 4.5, fecha_desde: '2026-08-01', fecha_hasta: null },
  { id: 1, porcentaje: 3, fecha_desde: '2026-01-01', fecha_hasta: '2026-07-31' },
];

describe('VariosVentaPctModal', () => {
  beforeEach(() => {
    getMock.mockReset();
    postMock.mockReset();
    mockTienePermiso = () => false;
    getMock.mockResolvedValue({ data: HISTORIAL });
  });

  it('sin permiso de edición: muestra el historial pero NO el formulario', async () => {
    mockTienePermiso = (codigo) => codigo !== 'ml_ops.varios_editar';

    render(<VariosVentaPctModal isOpen={true} onClose={() => {}} />);

    await waitFor(() => expect(screen.getByText('4.5%')).toBeInTheDocument());
    expect(screen.getByText('3%')).toBeInTheDocument();

    expect(screen.queryByLabelText(/Porcentaje \(%\)/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Guardar nueva versión/i })).not.toBeInTheDocument();
  });

  it('con permiso de edición: muestra el historial Y el formulario', async () => {
    mockTienePermiso = () => true;

    render(<VariosVentaPctModal isOpen={true} onClose={() => {}} />);

    await waitFor(() => expect(screen.getByText('4.5%')).toBeInTheDocument());

    expect(screen.getByLabelText(/Porcentaje \(%\)/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Guardar nueva versión/i })).toBeInTheDocument();
  });
});
