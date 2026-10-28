import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import ShortcutsHelp from './ShortcutsHelp';

describe('ShortcutsHelp', () => {
  it('lists the search operators, as Productos does', () => {
    render(<ShortcutsHelp onClose={vi.fn()} />);
    const section = screen.getByRole('region', { name: 'Operadores de búsqueda' });
    const operators = within(section).getAllByRole('term').map((term) => term.textContent);
    expect(operators).toEqual(['MLA123456', 'ean:123456', 'codigo:ABC123', 'marca:Samsung', 'desc:texto o descripcion:texto', '*123', '123*', 'texto']);
    expect(within(section).getByText('Búsqueda en la descripción del producto (contiene, sin guiones ni espacios)')).toBeInTheDocument();
    expect(within(section).getByText('Comienza con "123" (título, descripción, marca o código)')).toBeInTheDocument();
  });

  it('keeps the keyboard shortcuts', () => {
    render(<ShortcutsHelp onClose={vi.fn()} />);
    expect(screen.getByText('Mostrar u ocultar esta ayuda')).toBeInTheDocument();
  });
});
