/**
 * Productos' pricing modal (shared with Publicaciones ML and Tienda): figures in the Argentine format, labels in
 * sentence case, the mode as a segmented control and "Calcular" on the field's line.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PricingModalTesla from './PricingModalTesla';
import api from '../services/api';

vi.mock('../services/api', () => ({ default: { get: vi.fn(), post: vi.fn() } }));

const PRODUCTO = { item_id: 7, descripcion: 'Router Archer AX55', marca: 'TP-LINK', categoria: 'Redes', stock: 12, costo: 95.5, moneda_costo: 'USD' };

const RESULTADO = {
  clasica: { precio: 98500.5, markup_real: 42.98 },
  cuotas: { '3_cuotas': { precio: 104200, markup_real: 40.1 } },
};

const open = () => render(<PricingModalTesla isOpen producto={PRODUCTO} onClose={() => {}} onSave={() => {}} />);

describe('PricingModalTesla - format and controls', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    api.get.mockResolvedValue({ data: { con_oferta: 0, total_publicaciones: 0, publicaciones: [] } });
  });

  it('subtitles the product with its cost in the Argentine format', async () => {
    open();
    expect(await screen.findByText('TP-LINK · Redes · Stock 12 · Costo USD 95,50')).toBeInTheDocument();
  });

  it('picks the mode in a segmented control, in sentence case', async () => {
    const user = userEvent.setup();
    open();
    const modes = screen.getByRole('group', { name: 'Modo de cálculo' });
    const markup = within(modes).getByRole('button', { name: 'Por markup' });
    const manual = within(modes).getByRole('button', { name: 'Precio manual' });
    expect(markup).toHaveAttribute('aria-pressed', 'true');
    expect(manual).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('heading', { name: 'Markup objetivo (%)' })).toBeInTheDocument();

    await user.click(manual);
    expect(manual).toHaveAttribute('aria-pressed', 'true');
    expect(markup).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('heading', { name: 'Precio manual ($)' })).toBeInTheDocument();
    expect(screen.getByLabelText('Participa en rebate')).toBeInTheDocument();
  });

  it('puts "Calcular" on the line of the value it calculates from', () => {
    open();
    const field = screen.getByRole('spinbutton', { name: 'Markup objetivo (%)' });
    const calcular = screen.getByRole('button', { name: 'Calcular' });
    expect(calcular.parentElement).toBe(field.parentElement);
    expect(calcular).not.toHaveClass('full');
  });

  it('shows the result in the Argentine format and saves in sentence case', async () => {
    const user = userEvent.setup();
    api.post.mockResolvedValue({ data: RESULTADO });
    open();
    await user.click(screen.getByRole('button', { name: 'Calcular' }));
    expect(await screen.findByText('$ 98.500,50')).toBeInTheDocument();
    expect(screen.getByText('42,98 %')).toBeInTheDocument();
    expect(screen.getByText('$ 104.200,00')).toBeInTheDocument();
    expect(screen.getByText('40,10 %')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Precio clásica' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Precios con cuotas' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Guardar precio' })).toBeInTheDocument();
    // The value sent to the server is the raw number, not the formatted one.
    expect(api.post).toHaveBeenCalledWith('/precios/calcular-completo', { item_id: 7, markup_objetivo: 42.98, adicional_cuotas: 4.0 });
  });
});
