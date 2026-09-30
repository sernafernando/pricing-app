/**
 * ventas-ml-kpi-strip T4: the four `include_*` toggles this screen sends
 * to BOTH the list and the KPI endpoint (T5 parity). Behaviour only —
 * `css: false` in this project's Vitest config, so no layout/style
 * assertions here (see task doc "TDD IS MANDATORY").
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import IncludeToggles from './IncludeToggles';

const VALUES = {
  includeUnknown: true,
  includeInDispute: true,
  includeMixed: true,
  includeProvisional: true,
};

const EXCLUDED = { a_revisar: 3, en_disputa: 1, mixta: 0, provisorio: 5 };

describe('IncludeToggles', () => {
  it('renders the four toggles, all checked by default', () => {
    render(<IncludeToggles values={VALUES} excludedByToggle={EXCLUDED} onChange={vi.fn()} />);
    expect(screen.getByRole('checkbox', { name: /sin clasificar/i })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /en disputa/i })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /mixta/i })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: /provisorio/i })).toBeChecked();
  });

  it('calls onChange with the toggled key and the new value', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<IncludeToggles values={VALUES} excludedByToggle={EXCLUDED} onChange={onChange} />);
    await user.click(screen.getByRole('checkbox', { name: /sin clasificar/i }));
    expect(onChange).toHaveBeenCalledWith('includeUnknown', false);
  });

  it('shows how many groups a toggle hides only while it is OFF', () => {
    render(
      <IncludeToggles
        values={{ ...VALUES, includeUnknown: false }}
        excludedByToggle={EXCLUDED}
        onChange={vi.fn()}
      />
    );
    // "Sin clasificar" is OFF and excludes 3 groups -> its count shows.
    expect(screen.getByText('+3')).toBeInTheDocument();

    // And the half that makes the assertion above mean anything: the badge
    // must be ABSENT for a toggle that is ON, even when `excludedByToggle`
    // carries a non-zero number for it. `en_disputa` is 1 and `provisorio`
    // is 5 in the fixture, and both toggles are on. Asserting only that
    // their checkboxes are checked leaves `!checked` untested — delete it
    // from the component and the old version of this test still passed.
    expect(screen.queryByText('+1')).not.toBeInTheDocument();
    expect(screen.queryByText('+5')).not.toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /provisorio/i })).toBeChecked();
  });

  it('renders with no crash when excludedByToggle is not loaded yet', () => {
    render(<IncludeToggles values={VALUES} excludedByToggle={null} onChange={vi.fn()} />);
    expect(screen.getByRole('checkbox', { name: /sin clasificar/i })).toBeInTheDocument();
  });
});
