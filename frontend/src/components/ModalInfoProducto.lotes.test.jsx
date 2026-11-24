import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import ModalInfoProducto from './ModalInfoProducto';
import api from '../services/api';

// Costo SI T5 PR B: costo SI replaced the FIFO lots, so the product info has no "Historial de lotes sell in" tab any
// more; the Información tab (with its Costo SI row, `ModalInfoProducto.costoSi.test.jsx`) stays.

vi.mock('../services/api', () => ({ default: { get: vi.fn() } }));

let granted = new Set();
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: (permiso) => granted.has(permiso) }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockResolvedValue({ data: { producto: { item_id: 950 }, pricing: {}, ultimas_compras: [] } });
});

describe('ModalInfoProducto - no sell-in lots tab', () => {
  it('has no lots tab, and the Información tab still opens', async () => {
    granted = new Set(['productos.ver', 'productos.ver_info_basica']);
    render(<ModalInfoProducto isOpen onClose={() => {}} itemId={950} />);

    expect(await screen.findByRole('button', { name: '📦 Información' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Historial de lotes sell in/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/Historial de lotes sell in/)).not.toBeInTheDocument();
  });

  it('a product permission alone opens no tab: the lots were its only one', async () => {
    granted = new Set(['productos.ver']);
    render(<ModalInfoProducto isOpen onClose={() => {}} itemId={950} />);

    expect(await screen.findByText('No tienes permisos para ver información del producto.')).toBeInTheDocument();
    expect(screen.queryByText(/Historial de lotes sell in/)).not.toBeInTheDocument();
  });
});
