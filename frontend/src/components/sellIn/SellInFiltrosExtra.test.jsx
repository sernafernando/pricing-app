import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { productosAPI } from '../../services/api';
import { sellInAPI } from '../../services/sellInAPI';
import { PRODUCTOS } from './sellInFixtures';
import SellInFiltrosExtra from './SellInFiltrosExtra';

vi.mock('../../services/sellInAPI', () => ({ sellInAPI: { proveedores: vi.fn() } }));

// The supplier search's answer (`GET /administracion/proveedores`).
const PROVEEDORES = { proveedores: [{ id: 7, nombre: 'TP-Link', cuit: '30-1' }], total: 1, page: 1, page_size: 10 };

beforeEach(() => {
  vi.clearAllMocks();
  productosAPI.listar.mockResolvedValue({ data: { productos: PRODUCTOS, total: 2, page: 1, page_size: 10 } });
  sellInAPI.proveedores.mockResolvedValue({ data: PROVEEDORES });
});

describe('SellInFiltrosExtra — product and supplier filters of the Sell in list', () => {
  it('searches the catalog and hands back the picked product', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<SellInFiltrosExtra producto={null} proveedor={null} onChange={onChange} />);
    await user.type(within(screen.getByRole('group', { name: 'Producto' })).getByRole('searchbox'), 'sw');
    await user.click(await screen.findByRole('button', { name: /SW-8 · Switch 8 bocas/ }));
    expect(productosAPI.listar).toHaveBeenCalledWith({ search: 'sw', page_size: 10 });
    expect(onChange).toHaveBeenCalledWith({ producto: PRODUCTOS[0] });
  });

  it('searches the suppliers the purchase form searches and hands back the picked one', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<SellInFiltrosExtra producto={null} proveedor={null} onChange={onChange} />);
    await user.type(within(screen.getByRole('group', { name: 'Proveedor' })).getByRole('searchbox'), 'tp');
    await user.click(await screen.findByRole('button', { name: /TP-Link/ }));
    expect(sellInAPI.proveedores).toHaveBeenCalledWith('tp');
    expect(onChange).toHaveBeenCalledWith({ proveedor: PROVEEDORES.proveedores[0] });
  });

  it('shows what is picked with a way to clear each one', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<SellInFiltrosExtra producto={PRODUCTOS[0]} proveedor={PROVEEDORES.proveedores[0]} onChange={onChange} />);
    expect(screen.getByText('SW-8 · Switch 8 bocas')).toBeInTheDocument();
    expect(screen.getByText('TP-Link')).toBeInTheDocument();
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Quitar producto' }));
    expect(onChange).toHaveBeenLastCalledWith({ producto: null });
    await user.click(screen.getByRole('button', { name: 'Quitar proveedor' }));
    expect(onChange).toHaveBeenLastCalledWith({ proveedor: null });
  });

  it('says when a search failed', async () => {
    const user = userEvent.setup();
    sellInAPI.proveedores.mockRejectedValue(new Error('500'));
    productosAPI.listar.mockRejectedValue(new Error('500'));
    render(<SellInFiltrosExtra producto={null} proveedor={null} onChange={vi.fn()} />);
    await user.type(within(screen.getByRole('group', { name: 'Proveedor' })).getByRole('searchbox'), 'tp');
    expect(await screen.findByText('No se pudieron buscar proveedores.')).toBeInTheDocument();
    await user.type(within(screen.getByRole('group', { name: 'Producto' })).getByRole('searchbox'), 'sw');
    expect(await screen.findByText('No se pudieron buscar productos.')).toBeInTheDocument();
  });
});
