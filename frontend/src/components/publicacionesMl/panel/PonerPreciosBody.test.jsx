import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PonerPreciosBody from './PonerPreciosBody';

const detail = {
  row: {
    price: { amount: 1500, pricelist_id: 17, lista_nombre: null },
    link: { codigo: 'SKU-1' },
  },
};

describe('PonerPreciosBody', () => {
  it('shows lista, current price, codigo and an editable draft', async () => {
    const user = userEvent.setup();
    render(<PonerPreciosBody detail={detail} canEditPrice />);
    expect(screen.getByText('3 Cuotas')).toBeInTheDocument();
    expect(screen.getByText('1.500,00')).toBeInTheDocument();
    expect(screen.getByText('SKU-1')).toBeInTheDocument();
    const input = screen.getByLabelText('Nuevo precio');
    expect(input).toHaveValue('1500');
    await user.clear(input);
    await user.type(input, '1600');
    expect(input).toHaveValue('1600');
  });

  it('disables the input without edit permission', () => {
    render(<PonerPreciosBody detail={detail} canEditPrice={false} />);
    expect(screen.getByLabelText('Nuevo precio')).toBeDisabled();
  });
});
