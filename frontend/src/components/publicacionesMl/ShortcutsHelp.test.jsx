/**
 * The `?` help of Publicaciones ML lists every shortcut the screen answers (usePublicacionesMLKeyboard), grouped by
 * what each key acts on.
 */
import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ShortcutsHelp from './ShortcutsHelp';

const entry = (what) => screen.getByText(what).closest('div');
const keysOf = (what) => Array.from(entry(what).querySelectorAll('kbd')).map((kbd) => kbd.textContent);
const termsOf = (group) =>
  within(screen.getByRole('region', { name: group }))
    .getAllByRole('term')
    .map((term) => term.textContent);

describe('ShortcutsHelp', () => {
  it('groups the shortcuts by what they act on, every key kept', () => {
    render(<ShortcutsHelp onClose={() => {}} />);
    const groups = screen.getAllByRole('heading', { level: 3 }).map((heading) => heading.textContent);
    expect(groups).toEqual([
      'Lista',
      'Precios de la fila',
      'Producto de la fila',
      'Copiar',
      'Colores',
      'Sobre los marcados o filtrados',
      'Abrir un filtro',
      'Pantalla',
      'Operadores de búsqueda',
    ]);
    expect(termsOf('Lista')).toEqual([
      '↓ o ↑',
      'RePág o AvPág',
      'Inicio o Fin',
      'Shift+↓ o Shift+↑',
      'Enter',
      'Ctrl+Enter',
      'Alt+Enter o Alt+Espacio',
      'Shift+Enter o Shift+Espacio',
      'Esc',
    ]);
    expect(termsOf('Precios de la fila')).toEqual(['→ o ←', 'Espacio', 'Tab o Shift+Tab', 'Esc']);
    expect(termsOf('Producto de la fila')).toEqual(['Ctrl+I', 'R', 'W', 'O']);
    expect(termsOf('Copiar')).toEqual(['Ctrl+F1 o Ctrl+Shift+1', 'Ctrl+F2 o Ctrl+Shift+2', 'Ctrl+F3 o Ctrl+Shift+3']);
    expect(termsOf('Colores')).toEqual(['1–7', '0', 'F6 o F7']);
    expect(termsOf('Sobre los marcados o filtrados')).toEqual(['Ctrl+K', 'Ctrl+Shift+P']);
    expect(termsOf('Abrir un filtro')).toEqual(['Alt+M o Alt+S o Alt+P', 'Alt+A', 'Alt+C o Alt+F']);
    expect(termsOf('Pantalla')).toEqual(['Ctrl+F', 'Alt+V', 'Alt+R', 'Ctrl+E', '?']);
  });

  it("lists Productos' Alt+A (Auditoría) and Alt+C / Alt+F (Presencia) filter keys", () => {
    render(<ShortcutsHelp onClose={() => {}} />);
    expect(keysOf('Auditoría')).toEqual(['Alt+A']);
    expect(keysOf('Presencia (los Avanzados de Productos)')).toEqual(['Alt+C', 'Alt+F']);
  });

  it("lists Productos' Ctrl+I, the focused row's product information", () => {
    render(<ShortcutsHelp onClose={() => {}} />);
    expect(keysOf('Ver su información')).toEqual(['Ctrl+I']);
  });

  // The row's Enter / Space reach `handleRowClick` with their modifiers, as a click does (TableShell's `activateOnKey`).
  it('lists Alt and Shift with Enter or Space, the seller panel listing and promotions of the row', () => {
    render(<ShortcutsHelp onClose={() => {}} />);
    expect(keysOf('Abrir la publicación en el panel de vendedores')).toEqual(['Alt+Enter', 'Alt+Espacio']);
    expect(keysOf('Abrir sus promociones en el panel de vendedores')).toEqual(['Shift+Enter', 'Shift+Espacio']);
  });

  it("lists Productos' Esc, leaving the navigation mode", () => {
    render(<ShortcutsHelp onClose={() => {}} />);
    expect(keysOf('Salir del modo navegación')).toEqual(['Esc']);
  });

  it('lists the search operators, as Productos does', () => {
    render(<ShortcutsHelp onClose={() => {}} />);
    expect(termsOf('Operadores de búsqueda')).toEqual([
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
    const section = screen.getByRole('region', { name: 'Operadores de búsqueda' });
    expect(within(section).getByText('La descripción contiene el texto (sin guiones ni espacios)')).toBeInTheDocument();
    expect(
      within(section).getByText('Promoción activa de ese tipo (DEAL, SMART…) o cuyo nombre contiene el texto'),
    ).toBeInTheDocument();
    expect(within(section).getByText('Empieza con 123 (título, descripción, marca o código)')).toBeInTheDocument();
  });
});
