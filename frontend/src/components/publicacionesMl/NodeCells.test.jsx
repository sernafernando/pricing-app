import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { NodeKinds, NodePrice, NodeStatuses, NodeTitle } from './NodeCells';

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

// S6: a parent row carries its publication count (and negatives) on its title's second line, and a summary of ALL its
// publications in Tipo, Estado and Precio.
describe('NodeTitle count line', () => {
  const titled = (node) => render(<NodeTitle row={{ node: { key: '1', label: 'Nodo', kind: 'marca', ...node }, expanded: false }} onToggle={() => {}} />);

  it('says the publications and, when some sell under cost, how many', () => {
    titled({ count: 1234, negativeCount: 2 });
    expect(screen.getByText(/1\.234 publicaciones/)).toBeInTheDocument();
    expect(screen.getByText('2 con markup negativo')).toBeInTheDocument();
  });

  it('is singular for one publication and leaves out zero or unknown negatives', () => {
    const { unmount } = titled({ count: 1, negativeCount: 0 });
    expect(screen.getByText(/1 publicación$/)).toBeInTheDocument();
    expect(screen.queryByText(/markup negativo/)).not.toBeInTheDocument();
    unmount();
    titled({ count: 5, negativeCount: null }); // no ver_ganancia: the backend sent none
    expect(screen.getByText(/5 publicaciones$/)).toBeInTheDocument();
    expect(screen.queryByText(/markup negativo/)).not.toBeInTheDocument();
  });

  it('carries the whole second line in its tooltip, for "Filas finas" that cuts it', () => {
    titled({ kind: 'producto', codigo: 'AX55', count: 3, negativeCount: 1 });
    expect(screen.getByTitle('Producto · AX55 · 3 publicaciones · 1 con markup negativo')).toBeInTheDocument();
  });

  it('keeps the kind and the code before the count', () => {
    titled({ kind: 'producto', codigo: 'AX55', count: 3 });
    expect(screen.getByText('Producto · AX55 · 3 publicaciones')).toBeInTheDocument();
  });
});

// Owner (2026-11-12): "Clásica puede ser solo C o 1, 3 cuotas, 3, 6 cuotas, 6, etc pones badges y achicá los
// renglones": a parent row's Tipo and Estado are compact badges on one line, the whole words in each badge's tooltip.
const chips = (container) => [...container.querySelectorAll('[data-summary-chip]')];
const shown = (container) => chips(container).map((chip) => chip.textContent);
const named = (container) => chips(container).map((chip) => chip.getAttribute('title'));

describe('NodeKinds', () => {
  it('shows one badge per kind, short label then count, in the list order, a co-funded Clásica counted as Clásica', () => {
    const { container } = render(
      <NodeKinds node={{ kindCounts: { cuotas_6: 1, gold_pro: 4, clasica: 2, clasica_cofinanciada: 1, cuotas_3: 3, cuotas_12: 24, cuotas_9: 2 } }} />,
    );
    expect(shown(container)).toEqual(['C 3', '3 3', '6 1', '9 2', '12 24', 'P 4']);
    expect(named(container)).toEqual(['3 Clásica', '3 3 cuotas', '1 6 cuotas', '2 9 cuotas', '24 12 cuotas', '4 Premium']);
  });

  it('names each badge for screen readers with its whole words', () => {
    render(<NodeKinds node={{ kindCounts: { clasica: 33 } }} />);
    expect(screen.getByRole('img', { name: '33 Clásica' })).toHaveTextContent('C 33');
  });

  it('keeps every badge in one row container, never one line per kind', () => {
    const { container } = render(<NodeKinds node={{ kindCounts: { clasica: 33, cuotas_3: 30 } }} />);
    const [first, second] = chips(container);
    expect(first.parentElement).toBe(second.parentElement);
    expect(container.querySelector('[data-summary-line]')).toBeNull();
  });

  it('reads "—" with no kind', () => {
    render(<NodeKinds node={{ kindCounts: {} }} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});

describe('NodeStatuses', () => {
  it('shows one badge per state, a coloured dot and the count, the state in words in its tooltip', () => {
    const { container } = render(<NodeStatuses node={{ statusCounts: { paused: 1, active: 111, gone: 2, under_review: 7, closed: 19 } }} />);
    expect(shown(container)).toEqual(['111', '1', '7', '19', '2']);
    expect(named(container)).toEqual(['111 activas', '1 pausada', '7 en revisión', '19 cerradas', '2 eliminadas']);
    expect(chips(container).map((chip) => chip.dataset.tone)).toEqual(['success', 'warning', 'warning', 'neutral', 'danger']);
  });

  it('names each badge for screen readers with its whole words', () => {
    render(<NodeStatuses node={{ statusCounts: { active: 111 } }} />);
    expect(screen.getByRole('img', { name: '111 activas' })).toHaveTextContent('111');
  });

  it('reads "—" with no publication', () => {
    render(<NodeStatuses node={{ statusCounts: {} }} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});

describe('NodePrice', () => {
  it('shows the range of the shown prices, one end per line so it never widens the column', () => {
    const { container } = render(<NodePrice node={{ priceMin: 900, priceMax: 5000 }} />);
    expect([...container.querySelectorAll('span')].map((end) => end.textContent)).toEqual(['900,00 –', '5.000,00']);
  });

  it('shows one figure when every price is the same', () => {
    const { container } = render(<NodePrice node={{ priceMin: 3000, priceMax: 3000 }} />);
    expect(container.textContent).toBe('3.000,00');
  });

  it('reads "—" with no price', () => {
    render(<NodePrice node={{ priceMin: null, priceMax: null }} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});
