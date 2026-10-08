import { describe, it, expect } from 'vitest';

import * as kitColumnPicker from './ColumnPicker';
import * as kitPagination from './Pagination';
import * as kitFacetChips from './FacetChips';
import * as kitKpiStrip from './KpiStrip';
import * as kitStatusPill from './StatusPill';
import * as kitCopyButton from './CopyButton';
import * as kitUseColumnResize from './useColumnResize';
import * as kitSegmentedControl from './SegmentedControl';
import * as kitToggleChips from './ToggleChips';
import * as kitSwitchChip from './SwitchChip';
import * as kitSparkline from './Sparkline';

import * as oldColumnPicker from '../ventasMl/ColumnPicker';
import * as oldPagination from '../ventasMl/Pagination';
import * as oldFacetChips from '../ventasMl/FacetChips';
import * as oldKpiStrip from '../ventasMl/KpiStrip';
import * as oldStatusPill from '../ventasMl/StatusPill';
import * as oldCopyButton from '../ventasMl/CopyButton';
import * as oldUseColumnResize from '../ventasMl/useColumnResize';
import * as oldSegmentedControl from '../metricasMl/SegmentedControl';
import * as oldToggleChips from '../metricasMl/ToggleChips';
import * as oldSwitchChip from '../metricasMl/SwitchChip';
import * as oldSparkline from '../metricasMl/Sparkline';

// The legacy paths are re-export shims: they must resolve to the SAME
// function as the kit module, for the default export and every named one.
const PAIRS = [
  ['ventasMl/ColumnPicker', oldColumnPicker, kitColumnPicker, ['default']],
  ['ventasMl/Pagination', oldPagination, kitPagination, ['default']],
  ['ventasMl/FacetChips', oldFacetChips, kitFacetChips, ['default']],
  ['ventasMl/KpiStrip', oldKpiStrip, kitKpiStrip, ['default']],
  ['ventasMl/StatusPill', oldStatusPill, kitStatusPill, ['default']],
  ['ventasMl/CopyButton', oldCopyButton, kitCopyButton, ['default']],
  ['ventasMl/useColumnResize', oldUseColumnResize, kitUseColumnResize, ['useColumnResize']],
  ['metricasMl/SegmentedControl', oldSegmentedControl, kitSegmentedControl, ['default']],
  ['metricasMl/ToggleChips', oldToggleChips, kitToggleChips, ['default']],
  ['metricasMl/SwitchChip', oldSwitchChip, kitSwitchChip, ['default']],
  ['metricasMl/Sparkline', oldSparkline, kitSparkline, ['default']],
];

describe('kit re-export shims', () => {
  it.each(PAIRS)('%s resolves to the same function as the kit module', (_name, oldMod, kitMod, names) => {
    for (const name of names) {
      expect(typeof kitMod[name]).toBe('function');
      expect(oldMod[name]).toBe(kitMod[name]);
    }
    // Same export surface: the shim neither drops nor adds names.
    expect(Object.keys(oldMod).sort()).toEqual(Object.keys(kitMod).sort());
  });
});
