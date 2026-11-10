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

  it('keeps the kind and the code before the count', () => {
    titled({ kind: 'producto', codigo: 'AX55', count: 3 });
    expect(screen.getByText('Producto · AX55 · 3 publicaciones')).toBeInTheDocument();
  });
});

const lines = (container) => [...container.querySelectorAll('[data-summary-line]')].map((line) => line.textContent);

describe('NodeKinds', () => {
  it('lists one line per kind, count first, in the list order, a co-funded Clásica counted as Clásica', () => {
    const { container } = render(<NodeKinds node={{ kindCounts: { cuotas_6: 1, gold: 4, clasica: 2, clasica_cofinanciada: 1, cuotas_3: 3 } }} />);
    expect(lines(container)).toEqual(['3 Clásica', '3 3 cuotas', '1 6 cuotas', '4 Oro']);
  });

  it('reads "—" with no kind', () => {
    render(<NodeKinds node={{ kindCounts: {} }} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});

describe('NodeStatuses', () => {
  it('lists one line per state, lowercase, plural or singular', () => {
    const { container } = render(<NodeStatuses node={{ statusCounts: { paused: 1, active: 4, gone: 2, under_review: 1, closed: 1 } }} />);
    expect(lines(container)).toEqual(['4 activas', '1 pausada', '1 en revisión', '1 cerrada', '2 eliminadas']);
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
