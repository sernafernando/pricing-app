/**
 * Tests for Novedades.jsx (odd/tasks/novedades-changelog.md, T1).
 *
 * `../novedades/loadNovedades` is mocked so tests control the entry set
 * directly, independent of `import.meta.glob` and any real `.md` files.
 */
import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
import { renderWithRouter } from '../test/renderWithRouter';
import Novedades from './Novedades';

const mockLoadNovedades = vi.fn();

vi.mock('../novedades/loadNovedades', () => ({
  loadNovedades: () => mockLoadNovedades(),
}));

describe('Novedades page', () => {
  it('renders each entry title and an article with id=slug', () => {
    mockLoadNovedades.mockReturnValue([
      {
        slug: 'oc-match',
        date: new Date(2026, 8, 21),
        title: 'OC Match',
        bodyMarkdown: 'Some **body** text.',
      },
      {
        slug: 'otra-novedad',
        date: new Date(2026, 7, 1),
        title: 'Otra Novedad',
        bodyMarkdown: 'More body.',
      },
    ]);

    renderWithRouter(<Novedades />);

    expect(screen.getByText('OC Match')).toBeInTheDocument();
    expect(screen.getByText('Otra Novedad')).toBeInTheDocument();

    const article = document.getElementById('oc-match');
    expect(article).not.toBeNull();
    expect(article.tagName).toBe('ARTICLE');
  });

  it('shows an empty state when there are no entries', () => {
    mockLoadNovedades.mockReturnValue([]);

    renderWithRouter(<Novedades />);

    expect(document.querySelectorAll('article')).toHaveLength(0);
    expect(screen.getByText(/no hay novedades/i)).toBeInTheDocument();
  });

  it('sanitizes rendered body HTML: no <script> element and no onerror attribute survive', () => {
    mockLoadNovedades.mockReturnValue([
      {
        slug: 'xss-entry',
        date: new Date(2026, 0, 1),
        title: 'XSS Entry',
        bodyMarkdown: '<script>alert(1)</script>\n\n<img src=x onerror="alert(1)">',
      },
    ]);

    renderWithRouter(<Novedades />);

    const article = document.getElementById('xss-entry');
    expect(article.querySelector('script')).toBeNull();
    expect(article.innerHTML.toLowerCase()).not.toContain('onerror');
  });
});
