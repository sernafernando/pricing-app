/**
 * Shared UI kit — named exports for every kit component, so a page imports
 * `{ SplitPanelLayout, TableShell } from '../components/kit'`. The legacy
 * `ventasMl/` and `metricasMl/` paths keep re-exporting the same modules.
 */
export { default as ColumnPicker } from './ColumnPicker';
export { default as CopyButton } from './CopyButton';
export { default as FacetChips } from './FacetChips';
export { default as KpiStrip } from './KpiStrip';
export { default as Pagination } from './Pagination';
export { default as SegmentedControl } from './SegmentedControl';
export { default as SplitPanelLayout } from './SplitPanelLayout';
export { default as Sparkline } from './Sparkline';
export { default as StatusPill } from './StatusPill';
export { default as SwitchChip } from './SwitchChip';
export { default as TableShell } from './TableShell';
export { default as ToggleChips } from './ToggleChips';
export { useColumnResize } from './useColumnResize';
