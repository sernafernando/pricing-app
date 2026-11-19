/**
 * Auditoría de stock: "Markup actual c/ SISO" next to "Actual" (pubml-markup-siso S1, S3, S4). A product or brand row
 * shows the range of its publications' markup with sell in / sell out; a publication row draws the list's cell.
 */
import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import StockAuditTable from './StockAuditTable';
import { flattenAudit } from './stockAuditRows';
import { auditColumnOptions } from './auditOptions';
import { STOCK_AUDIT_SORTS } from '../../../hooks/usePublicacionesMLFilters';
import { AUDIT_NOTEBOOK, AUDIT_BRAND_DEMO } from '../../../test/visual/stockAuditFixtures';

const renderAudit = (rows, { canSeeMargin = true, canSeeSales = true, nivel = 'producto' } = {}) =>
  render(
    <StockAuditTable
      audit={{ rows, data: { tipo_cambio: 1000 }, toggle: () => {}, loadMore: () => {} }}
      canSeeSales={canSeeSales}
      canSeeMargin={canSeeMargin}
      arrange={(columns) => columns}
      nivel={nivel}
      onDrill={() => {}}
      sort={null}
      onSort={() => {}}
      onSelectItem={() => {}}
    />,
  );

const headers = () => screen.getAllByRole('columnheader').map((th) => th.textContent.trim());
const sisoCell = (container) => container.querySelector('tbody td[data-column="markup_siso"]');

describe('Markup actual c/ SISO on Auditoría de stock', () => {
  it('sits right after Actual, sortable, with ver_ganancia only', () => {
    const { unmount } = renderAudit(flattenAudit([{ ...AUDIT_NOTEBOOK, markup_siso: null }], new Set(), {}));
    const shown = headers();
    expect(shown.indexOf('Actual c/ SISO')).toBe(shown.indexOf('Actual') + 1);
    expect(STOCK_AUDIT_SORTS).toContain('markup_siso');
    unmount();
    renderAudit(flattenAudit([AUDIT_NOTEBOOK], new Set(), {}), { canSeeMargin: false });
    expect(headers()).not.toContain('Actual c/ SISO');
  });

  it('is in the column picker next to Actual, only with ver_ganancia, and Real 30D is not duplicated', () => {
    const ids = auditColumnOptions({ canSeeSales: true, canSeeMargin: true }).map((option) => option.id);
    expect(ids.slice(ids.indexOf('markup'), ids.indexOf('markup') + 3)).toEqual(['markup', 'markup_siso', 'markup_30d']);
    expect(ids).not.toContain('markup_sell_30d');
    expect(auditColumnOptions({ canSeeSales: true }).map((option) => option.id)).not.toContain('markup_siso');
  });

  it('a product row shows the range of its publications', () => {
    const { container } = renderAudit(flattenAudit([{ ...AUDIT_NOTEBOOK, markup_siso: { min: -2.5, max: 30 } }], new Set(), {}));
    expect(within(sisoCell(container)).getByText('-2,5% – 30,0%')).toHaveAttribute('data-negative', '');
  });

  it('a brand row (Marca level) shows the range of its products', () => {
    const { container } = renderAudit(flattenAudit([{ ...AUDIT_BRAND_DEMO, markup_siso: { min: 11, max: 32 } }], new Set(), {}), { nivel: 'marca' });
    expect(within(sisoCell(container)).getByText('11,0% – 32,0%')).toBeInTheDocument();
  });

  it('a row without a value reads "—"', () => {
    const { container } = renderAudit(flattenAudit([{ ...AUDIT_NOTEBOOK, markup_siso: null }], new Set(), {}));
    expect(sisoCell(container)).toHaveTextContent('—');
  });

  it('a publication row draws the list cell from its own markup_siso', () => {
    const item = { ...AUDIT_NOTEBOOK, item_id: 'MLA1', markup_siso: { min: 12, max: 12, worst: 12, pending: 0, applies: true } };
    const { container } = renderAudit([{ type: 'item', id: 'p#MLA1', depth: 1, item, owner: AUDIT_NOTEBOOK }]);
    expect(within(sisoCell(container)).getByText('12,0%')).toHaveAttribute('title', 'Con sell in / sell out al precio de hoy');
  });
});
