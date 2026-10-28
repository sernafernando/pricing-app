/**
 * ColorFilterChips (P6): Productos' color filter -- several colors at once, plus "Sin color" -- as chips.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ColorFilterChips from './ColorFilterChips';

const setup = (value = []) => {
  const onChange = vi.fn();
  render(<ColorFilterChips value={value} onChange={onChange} />);
  return { onChange, user: userEvent.setup() };
};

describe('ColorFilterChips', () => {
  it("offers Productos' seven colors and Sin color, none pressed by default", () => {
    setup();
    const chips = screen.getAllByRole('button');
    expect(chips.map((chip) => chip.getAttribute('aria-label'))).toEqual([
      'Urgente',
      'Advertencia',
      'Atención',
      'OK',
      'Info',
      'Revisión',
      'Inactivo',
      'Sin color',
    ]);
    expect(chips.every((chip) => chip.getAttribute('aria-pressed') === 'false')).toBe(true);
    expect(screen.getByRole('group', { name: 'Filtrar por color' })).toBeInTheDocument();
  });

  it('adds a color to the ones picked, and Sin color is `sin_color`', async () => {
    const { onChange, user } = setup(['rojo']);
    expect(screen.getByRole('button', { name: 'Urgente' })).toHaveAttribute('aria-pressed', 'true');
    await user.click(screen.getByRole('button', { name: 'Sin color' }));
    expect(onChange).toHaveBeenCalledWith(['rojo', 'sin_color']);
  });

  it('a picked color goes away on a second click', async () => {
    const { onChange, user } = setup(['rojo', 'azul']);
    await user.click(screen.getByRole('button', { name: 'Urgente' }));
    expect(onChange).toHaveBeenCalledWith(['azul']);
  });
});
