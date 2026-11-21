import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import EditableCell from './EditableCell';

describe('EditableCell format', () => {
  it('shows the formatted value while not editing', () => {
    render(<EditableCell type="number" value={860000} format={(v) => `$ ${Number(v).toLocaleString('es-AR')}`} />);

    expect(screen.getByText('$ 860.000')).toBeTruthy();
  });

  it('shows the placeholder, not a formatted empty value', () => {
    render(<EditableCell type="number" value="" placeholder="Sin costo" format={() => '$ 0'} />);

    expect(screen.getByText('Sin costo')).toBeTruthy();
  });

  it('without format shows the raw value as before', () => {
    render(<EditableCell type="number" value={860000} />);

    expect(screen.getByText('860000')).toBeTruthy();
  });
});
