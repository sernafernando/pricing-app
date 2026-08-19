import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import DuplicateGroupCard from './DuplicateGroupCard';

function baseRow(overrides = {}) {
  return {
    ean: '333',
    verdict: 'DUPLICADO',
    tn_presence: 'not_in_tn',
    tn_matches: [
      { product_id: 10, variant_id: 1, variant_sku: '333', published: true, tn_admin_url: 'https://tn/10' },
      { product_id: 11, variant_id: 1, variant_sku: '333', published: null, tn_admin_url: 'https://tn/11' },
    ],
    ...overrides,
  };
}

describe('DuplicateGroupCard — group header', () => {
  it('shows the EAN, the conflict count and a short presence label, never a run-on sentence', () => {
    render(<DuplicateGroupCard row={baseRow()} />);

    const header = screen.getByTestId('duplicado-group-header');
    expect(within(header).getByText('333')).toBeInTheDocument();
    expect(within(header).getByText('2 en conflicto')).toBeInTheDocument();
    expect(within(header).getByText('Sin presencia en TN')).toBeInTheDocument();
  });

  it('labels "existe en TN" when tn_presence is not "not_in_tn"', () => {
    render(<DuplicateGroupCard row={baseRow({ tn_presence: 'published' })} />);
    expect(within(screen.getByTestId('duplicado-group-header')).getByText('Existe en TN')).toBeInTheDocument();
  });

  it('falls back to the ERP description, visibly tagged, when there is no ml_title', () => {
    render(<DuplicateGroupCard row={baseRow({ erp_desc: 'Producto ERP X' })} />);
    const header = screen.getByTestId('duplicado-group-header');
    expect(within(header).getByText('Producto ERP X')).toBeInTheDocument();
    expect(within(header).getByText('ERP')).toBeInTheDocument();
  });

  it('carries no link — linking one conflicting match would implicitly recommend it', () => {
    render(<DuplicateGroupCard row={baseRow()} />);
    expect(within(screen.getByTestId('duplicado-group-header')).queryByRole('link')).not.toBeInTheDocument();
  });
});

describe('DuplicateGroupCard — conflicting match rows', () => {
  it('renders one row per conflicting TN match, each with its own "Editar en TN" link', () => {
    render(<DuplicateGroupCard row={baseRow()} />);

    const matchRows = screen.getAllByTestId('duplicado-match-row');
    expect(matchRows).toHaveLength(2);

    const links = screen.getAllByRole('link', { name: /editar en tn/i });
    expect(links).toHaveLength(2);
    expect(links.map((l) => l.getAttribute('href')).sort()).toEqual(['https://tn/10', 'https://tn/11']);
    expect(links[0]).toHaveAttribute('target', '_blank');
    expect(links[0]).toHaveAttribute('rel', expect.stringContaining('noopener'));
  });

  it('renders the bare product_id / variant_id pair, without the old redundant "product_id:" prefix', () => {
    render(<DuplicateGroupCard row={baseRow()} />);
    const matchRows = screen.getAllByTestId('duplicado-match-row');
    expect(matchRows[0]).toHaveTextContent('10 / 1');
    expect(screen.queryByText(/product_id:/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/variant_id:/i)).not.toBeInTheDocument();
  });

  it('renders a Publicado/Borrador/Desconocido badge from the match\'s own tri-state `published`', () => {
    render(<DuplicateGroupCard row={baseRow()} />);
    const matchRows = screen.getAllByTestId('duplicado-match-row');
    expect(within(matchRows[0]).getByText('Publicado')).toBeInTheDocument();
    expect(within(matchRows[1]).getByText('Desconocido')).toBeInTheDocument();
  });

  it('renders "Borrador" for published: false, distinct from "Desconocido" (published: null)', () => {
    const row = baseRow({
      tn_matches: [{ product_id: 20, variant_id: 1, variant_sku: 'X', published: false, tn_admin_url: null }],
    });
    render(<DuplicateGroupCard row={row} />);
    expect(screen.getByText('Borrador')).toBeInTheDocument();
  });

  it('renders a dash, never a broken link, when a match has no tn_admin_url', () => {
    const row = baseRow({
      tn_matches: [{ product_id: 20, variant_id: 1, variant_sku: 'X', published: false, tn_admin_url: null }],
    });
    render(<DuplicateGroupCard row={row} />);
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('renders no match rows (an empty group body) when tn_matches is empty', () => {
    render(<DuplicateGroupCard row={baseRow({ tn_matches: [] })} />);
    expect(screen.queryAllByTestId('duplicado-match-row')).toHaveLength(0);
  });

  it('carries no selection/highlight/recommendation affordance on any match row', () => {
    render(<DuplicateGroupCard row={baseRow()} />);
    expect(screen.queryAllByRole('radio')).toHaveLength(0);
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
    for (const matchRow of screen.getAllByTestId('duplicado-match-row')) {
      expect(matchRow.className || '').not.toMatch(/selected|recommended|highlight/i);
    }
  });
});
