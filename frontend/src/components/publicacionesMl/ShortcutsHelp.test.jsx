/**
 * The `?` help of Publicaciones ML lists every shortcut the screen answers (usePublicacionesMLKeyboard).
 */
import { render, screen } from '@testing-library/react';
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

  it("lists Productos' Esc, leaving the navigation mode", () => {
    render(<ShortcutsHelp onClose={() => {}} />);
    expect(keysOf('Salir del modo navegación (deja la fila)')).toEqual(['Esc']);
  });
});
