import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { NodeTitle } from './NodeCells';

const row = { node: { key: '4101', label: 'Router Archer AX55 con un nombre largo', kind: 'producto', codigo: 'AX55' }, expanded: false };

// "Filas finas" cuts the name to one line: only the name, never the badges beside it.
describe('NodeTitle', () => {
  it('keeps the badges outside the name that gets cut, the whole name in its tooltip', () => {
    render(<NodeTitle row={row} onToggle={() => {}} badges={<span data-testid="badge">2 listas</span>} />);
    const name = screen.getByTitle('Router Archer AX55 con un nombre largo');
    expect(name).toHaveTextContent(/^Router Archer AX55 con un nombre largo$/);
    expect(name.contains(screen.getByTestId('badge'))).toBe(false);
  });
});
