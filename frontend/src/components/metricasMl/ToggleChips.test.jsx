import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import ToggleChips from './ToggleChips';

const OPTIONS = ['active', 'paused'];
const LABELS = { active: 'Activa', paused: 'Pausada' };

function Harness({ onChange }) {
  const [selected, setSelected] = useState([]);
  const [excluded, setExcluded] = useState([]);
  return (
    <ToggleChips
      label="Estado"
      options={OPTIONS}
      labels={LABELS}
      counts={{ active: 10, paused: 3 }}
      selected={selected}
      excluded={excluded}
      onChange={(nextSelected, nextExcluded) => {
        onChange?.(nextSelected, nextExcluded);
        setSelected(nextSelected);
        setExcluded(nextExcluded);
      }}
    />
  );
}

describe('ToggleChips tri-state', () => {
  it('cycles neutral -> include -> exclude -> neutral', async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    const chip = () => screen.getByRole('button', { name: /Pausada/ });

    expect(chip()).toHaveAttribute('aria-pressed', 'false');
    expect(chip()).toHaveAttribute('data-state', 'neutral');

    await userEvent.click(chip());
    expect(onChange).toHaveBeenLastCalledWith(['paused'], []);
    expect(chip()).toHaveAttribute('data-state', 'include');
    expect(chip()).toHaveAttribute('aria-pressed', 'true');

    await userEvent.click(chip());
    expect(onChange).toHaveBeenLastCalledWith([], ['paused']);
    expect(chip()).toHaveAttribute('data-state', 'exclude');

    await userEvent.click(chip());
    expect(onChange).toHaveBeenLastCalledWith([], []);
    expect(chip()).toHaveAttribute('data-state', 'neutral');
  });

  it('an excluded chip is announced as "Ocultar <x>" and keeps its count visible', async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole('button', { name: /Pausada/ }));
    await userEvent.click(screen.getByRole('button', { name: /Pausada/ }));

    const chip = screen.getByRole('button', { name: 'Ocultar Pausada' });
    expect(chip).toHaveAttribute('aria-pressed', 'true');
    expect(chip).toHaveTextContent('3');
  });

  it('chips are independent: excluding one leaves the other untouched', async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);

    await userEvent.click(screen.getByRole('button', { name: /Activa/ }));
    await userEvent.click(screen.getByRole('button', { name: /Pausada/ }));
    await userEvent.click(screen.getByRole('button', { name: /Pausada/ }));

    expect(onChange).toHaveBeenLastCalledWith(['active'], ['paused']);
  });
});
