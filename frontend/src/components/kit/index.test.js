import { describe, it, expect } from 'vitest';
import * as kit from './index';
import SplitPanelLayout from './SplitPanelLayout';
import TableShell from './TableShell';

describe('kit/index named exports', () => {
  it('exposes every kit component and hook', () => {
    expect(Object.keys(kit).sort()).toEqual(
      [
        'ColumnPicker',
        'CopyButton',
        'FacetChips',
        'KpiStrip',
        'Pagination',
        'SegmentedControl',
        'Sparkline',
        'SplitPanelLayout',
        'StatusPill',
        'SwitchChip',
        'TableShell',
        'ToggleChips',
        'useColumnResize',
      ].sort(),
    );
  });

  it('re-exports the same function, not a copy', () => {
    expect(kit.SplitPanelLayout).toBe(SplitPanelLayout);
    expect(kit.TableShell).toBe(TableShell);
  });
});
