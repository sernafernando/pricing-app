/**
 * PriceEditCell (S11c): a price of the table edited in place. A click opens an input with the current price, Enter
 * saves it, Escape or leaving the input drops it.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PriceEditCell from './PriceEditCell';

const setup = (props = {}) => {
  const onSave = vi.fn().mockResolvedValue(true);
  render(
    <PriceEditCell label="Precio Clásica" value={1200.5} onSave={onSave} {...props}>
      <span>1.200,50</span>
    </PriceEditCell>,
  );
  return { onSave };
};

describe('PriceEditCell', () => {
  it('shows the price as a button that names what it edits and the price it holds', () => {
    setup();
    expect(screen.getByRole('button', { name: 'Editar Precio Clásica: 1.200,50' })).toHaveTextContent('1.200,50');
  });

  it('a price not set is named as such', () => {
    setup({ value: null });
    expect(screen.getByRole('button', { name: 'Editar Precio Clásica: sin precio' })).toBeInTheDocument();
  });

  it('a click opens an input with the current price, and Enter saves the typed one', async () => {
    const { onSave } = setup();
    await userEvent.click(screen.getByRole('button', { name: /^Editar Precio Clásica/ }));
    const input = screen.getByRole('textbox', { name: 'Precio Clásica' });
    expect(input).toHaveValue('1200,5');
    expect(input).toHaveFocus();
    await userEvent.clear(input);
    await userEvent.type(input, '1500{Enter}');
    expect(onSave).toHaveBeenCalledWith('1500');
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });

  it('a price not set opens an empty input', async () => {
    setup({ value: null });
    await userEvent.click(screen.getByRole('button', { name: /^Editar Precio Clásica/ }));
    expect(screen.getByRole('textbox', { name: 'Precio Clásica' })).toHaveValue('');
  });

  it('Escape and leaving the input save nothing', async () => {
    const { onSave } = setup();
    await userEvent.click(screen.getByRole('button', { name: /^Editar Precio Clásica/ }));
    await userEvent.type(screen.getByRole('textbox'), '9{Escape}');
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /^Editar Precio Clásica/ }));
    fireEvent.blur(screen.getByRole('textbox'));
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
  });

  it('keys typed in the input do not reach the row', async () => {
    const onKeyDown = vi.fn();
    render(
      <div onKeyDown={onKeyDown}>
        <PriceEditCell label="Precio Clásica" value={1} onSave={vi.fn()}>
          <span>1</span>
        </PriceEditCell>
      </div>,
    );
    await userEvent.click(screen.getByRole('button', { name: /^Editar Precio Clásica/ }));
    await userEvent.type(screen.getByRole('textbox'), '2');
    expect(onKeyDown).not.toHaveBeenCalled();
  });

  it('while a save is running the button is disabled', () => {
    setup({ saving: true });
    expect(screen.getByRole('button', { name: /^Editar Precio Clásica/ })).toBeDisabled();
  });

  it('Tab and Shift+Tab keep the focus in the open editor, which stays open', async () => {
    const { onSave } = setup();
    await userEvent.click(screen.getByRole('button', { name: /^Editar Precio Clásica/ }));
    await userEvent.tab();
    expect(screen.getByRole('textbox', { name: 'Precio Clásica' })).toHaveFocus();
    await userEvent.tab({ shift: true });
    expect(screen.getByRole('textbox', { name: 'Precio Clásica' })).toHaveFocus();
    expect(onSave).not.toHaveBeenCalled();
  });

  it('Escape puts the focus back on the price it closed', async () => {
    setup();
    await userEvent.click(screen.getByRole('button', { name: /^Editar Precio Clásica/ }));
    await userEvent.keyboard('{Escape}');
    expect(screen.getByRole('button', { name: /^Editar Precio Clásica/ })).toHaveFocus();
  });
});
