import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ModalInfoProducto from './ModalInfoProducto';
import api from '../services/api';

// Productos' product info has the sell-in lot viewer as its own tab (`SellInLotes`), for whoever may see the product
// (`canViewProductPrices`: `productos.ver` or a product price edit permission, the backend's gate of the viewer).

vi.mock('../services/api', () => ({ default: { get: vi.fn() } }));

vi.mock('./sellIn/SellInLotes', () => ({
  default: ({ productItemId }) => <div data-testid="sell-in-lotes">{`lotes of ${productItemId}`}</div>,
}));

let granted = new Set();
vi.mock('../contexts/PermisosContext', () => ({
  usePermisos: () => ({ tienePermiso: (permiso) => granted.has(permiso) }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  api.get.mockResolvedValue({ data: { producto: { item_id: 950 }, pricing: {}, ultimas_compras: [] } });
});

describe('ModalInfoProducto - sell-in lots tab', () => {
  it('opens the lot viewer of the product from its tab', async () => {
    granted = new Set(['productos.ver', 'productos.ver_info_basica']);
    render(<ModalInfoProducto isOpen onClose={() => {}} itemId={950} />);

    await userEvent.click(await screen.findByRole('button', { name: 'Lotes sell in' }));

    expect(screen.getByTestId('sell-in-lotes')).toHaveTextContent('lotes of 950');
  });

  it('starts on the lots when it is the only tab allowed', async () => {
    granted = new Set(['productos.ver']);
    render(<ModalInfoProducto isOpen onClose={() => {}} itemId={950} />);

    expect(await screen.findByTestId('sell-in-lotes')).toHaveTextContent('lotes of 950');
  });

  it('an edit permission without productos.ver also sees it, as the backend allows', async () => {
    granted = new Set(['productos.ver_info_basica', 'productos.editar_precio_clasica']);
    render(<ModalInfoProducto isOpen onClose={() => {}} itemId={950} />);

    expect(await screen.findByRole('button', { name: 'Lotes sell in' })).toBeInTheDocument();
  });

  it('has no lots tab without a permission that shows the product', async () => {
    granted = new Set(['productos.ver_info_basica']);
    render(<ModalInfoProducto isOpen onClose={() => {}} itemId={950} />);

    expect(await screen.findByRole('button', { name: '📦 Información' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Lotes sell in' })).not.toBeInTheDocument();
  });
});
