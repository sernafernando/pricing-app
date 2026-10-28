/**
 * The `?` help of Publicaciones ML lists every shortcut the screen answers (usePublicacionesMLKeyboard).
 */
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ShortcutsHelp from './ShortcutsHelp';

const entry = (what) => screen.getByText(what).closest('div');
const keysOf = (what) => Array.from(entry(what).querySelectorAll('kbd')).map((kbd) => kbd.textContent);

describe('ShortcutsHelp', () => {
  it("lists Productos' Alt+A (Auditoría) and Alt+C / Alt+F (Presencia) filter keys", () => {
    render(<ShortcutsHelp onClose={() => {}} />);
    expect(keysOf('Abrir los filtros de Auditoría')).toEqual(['Alt+A']);
    expect(keysOf('Abrir los filtros de Presencia (los Avanzados de Productos)')).toEqual(['Alt+C', 'Alt+F']);
  });

  it("lists Productos' Ctrl+I, the focused row's product information", () => {
    render(<ShortcutsHelp onClose={() => {}} />);
    expect(keysOf('Ver la información del producto de la fila')).toEqual(['Ctrl+I']);
  });

  it('lists the search operators, as Productos does', () => {
    render(<ShortcutsHelp onClose={() => {}} />);
    const section = screen.getByRole('region', { name: 'Operadores de búsqueda' });
    const operators = within(section)
      .getAllByRole('term')
      .map((term) => term.textContent);
    expect(operators).toEqual([
      'MLA123456 o mla:MLA123456',
      'ean:123456',
      'codigo:ABC123',
      'marca:Samsung',
      'desc:texto o descripcion:texto',
      'promo:DEAL o promo:texto',
      '*123',
      '123*',
      'texto',
    ]);
    expect(
      within(section).getByText('Búsqueda en la descripción del producto (contiene, sin guiones ni espacios)'),
    ).toBeInTheDocument();
    expect(
      within(section).getByText(
        'Publicaciones con una promoción activa de ese tipo (DEAL, SMART, ...) o cuyo nombre contiene el texto',
      ),
    ).toBeInTheDocument();
    expect(within(section).getByText('Comienza con "123" (título, descripción, marca o código)')).toBeInTheDocument();
  });
});
