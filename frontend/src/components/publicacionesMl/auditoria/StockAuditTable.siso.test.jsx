/**
 * Auditoría de stock: "Markup actual c/ SISO" next to "Actual" (pubml-markup-siso S1, S3, S4). A product or variant
 * row shows the range of its publications' markup with sell in / sell out; a publication row draws the list's cell.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { buildAuditColumns } from './StockAuditTable';
import { auditColumnOptions } from './auditOptions';
import { STOCK_AUDIT_SORTS } from '../../../hooks/usePublicacionesMLFilters';

const columnsFor = (permissions) => buildAuditColumns({ rate: 1000, onToggle: () => {}, onMore: () => {}, ...permissions });
const sisoOf = (permissions) => columnsFor(permissions).find((column) => column.key === 'markup_siso');

describe('Markup actual c/ SISO on Auditoría de stock', () => {
  it('sits right after Actual, under Markup, sortable, with ver_ganancia only', () => {
    const keys = columnsFor({ canSeeMargin: true, canSeeSales: true }).map((column) => column.key);
    expect(keys.indexOf('markup_siso')).toBe(keys.indexOf('markup') + 1);
    expect(sisoOf({ canSeeMargin: true })).toMatchObject({ header: 'Actual c/ SISO', label: 'Markup actual c/ SISO', sortable: true });
    expect(sisoOf({ canSeeMargin: false, canSeeSales: true })).toBeUndefined();
    expect(STOCK_AUDIT_SORTS).toContain('markup_siso');
  });

  it('is in the column picker next to Actual, only with ver_ganancia, and Real 30D is not duplicated', () => {
    const ids = auditColumnOptions({ canSeeSales: true, canSeeMargin: true }).map((option) => option.id);
    expect(ids.slice(ids.indexOf('markup'), ids.indexOf('markup') + 3)).toEqual(['markup', 'markup_siso', 'markup_30d']);
    expect(ids).not.toContain('markup_sell_30d');
    expect(auditColumnOptions({ canSeeSales: true }).map((option) => option.id)).not.toContain('markup_siso');
  });

  it('a product row shows the range of its publications', () => {
    const row = { type: 'product', node: { markup_siso: { min: -2.5, max: 30 } } };
    render(sisoOf({ canSeeMargin: true }).render(row));
    expect(screen.getByText('-2,5% – 30,0%')).toHaveAttribute('data-negative', '');
  });

  it('a row without a value reads "—"', () => {
    render(sisoOf({ canSeeMargin: true }).render({ type: 'product', node: { markup_siso: null } }));
    expect(screen.getByText('—')).toBeInTheDocument();
  });

  it('a publication row draws the list cell from its own markup_siso', () => {
    const item = { markup_siso: { min: 12, max: 12, worst: 12, pending: 0, applies: true } };
    render(sisoOf({ canSeeMargin: true }).render({ type: 'item', item }));
    expect(screen.getByText('12,0%')).toHaveAttribute('title', 'Con sell in / sell out al precio de hoy');
  });
});
