import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SellInBuscador from './SellInBuscador';

describe('SellInBuscador', () => {
  it('says a search failed, and clearing the box clears that message', async () => {
    const user = userEvent.setup();
    const buscar = vi.fn().mockRejectedValue(new Error('403'));
    render(<SellInBuscador label="Proveedor" buscar={buscar} onPick={vi.fn()} errorMessage="No se pudieron buscar proveedores." />);
    await user.type(screen.getByRole('searchbox'), 'tp');
    expect(await screen.findByText('No se pudieron buscar proveedores.')).toBeInTheDocument();
    await user.clear(screen.getByRole('searchbox'));
    await waitFor(() => expect(screen.queryByText('No se pudieron buscar proveedores.')).not.toBeInTheDocument());
  });

  it('lists the results and hands back the one picked', async () => {
    const user = userEvent.setup();
    const onPick = vi.fn();
    const opcion = { key: 7, label: 'TP-Link', sub: '30-1' };
    render(<SellInBuscador label="Proveedor" buscar={vi.fn().mockResolvedValue([opcion])} onPick={onPick} />);
    await user.type(screen.getByRole('searchbox'), 'tp');
    await user.click(await screen.findByRole('button', { name: /TP-Link/ }));
    expect(onPick).toHaveBeenCalledWith(opcion);
  });
});
