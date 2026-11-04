import { describe, it, expect } from 'vitest';
import { render, fireEvent, screen } from '@testing-library/react';
import { setTheme } from './visualHelpers';
import ProductFiltersPanel from '../../components/shared/ProductFiltersPanel';

const OPTIONS = {
  marcas: [],
  categorias: [],
  subcategorias: [{ nombre: 'Impresoras', subcategorias: [{ id: 10, nombre: 'Laser' }, { id: 11, nombre: 'Tinta' }] }],
  pms: [],
};

describe('a partly ticked category (visual, pubml-filtros S2)', () => {
  for (const theme of ['light', 'dark']) {
    it(`draws a dash in its checkbox (${theme})`, () => {
      setTheme(theme);
      const { unmount } = render(
        <ProductFiltersPanel value={{ marcas: [], categorias: [], subcategorias: [10], pms: [] }} onChange={() => {}} options={OPTIONS} />,
      );
      try {
        fireEvent.click(screen.getByRole('button', { name: /^Subcategoría/ }));
        const box = screen.getByRole('checkbox', { name: /^Impresoras/ });
        const mark = getComputedStyle(box, '::after');
        expect(mark.content).not.toBe('none');
        expect(Number.parseFloat(mark.width)).toBeGreaterThan(Number.parseFloat(mark.height));
        expect(getComputedStyle(box).borderTopColor).toBe(getComputedStyle(screen.getByRole('checkbox', { name: 'Laser' })).borderTopColor);
      } finally {
        unmount();
      }
    });
  }
});
