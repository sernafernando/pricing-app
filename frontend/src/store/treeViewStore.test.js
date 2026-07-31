import { describe, it, expect, beforeEach } from 'vitest';
import { useTreeViewStore } from './treeViewStore';

describe('treeViewStore', () => {
  beforeEach(() => {
    localStorage.clear();
    useTreeViewStore.setState({ showFamilia: false });
  });

  it('defaults showFamilia to false (familia grouping hidden by default)', () => {
    expect(useTreeViewStore.getState().showFamilia).toBe(false);
  });

  it('toggleFamilia flips the value', () => {
    useTreeViewStore.getState().toggleFamilia();
    expect(useTreeViewStore.getState().showFamilia).toBe(true);
    useTreeViewStore.getState().toggleFamilia();
    expect(useTreeViewStore.getState().showFamilia).toBe(false);
  });

  it('setShowFamilia sets the value explicitly', () => {
    useTreeViewStore.getState().setShowFamilia(true);
    expect(useTreeViewStore.getState().showFamilia).toBe(true);
  });

  it('persists showFamilia to localStorage under a namespaced key', () => {
    useTreeViewStore.getState().setShowFamilia(true);
    const raw = localStorage.getItem('tree-view-store');
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw);
    expect(parsed.state.showFamilia).toBe(true);
  });
});

describe('treeViewStore — global collapse toggle', () => {
  beforeEach(() => {
    localStorage.clear();
    useTreeViewStore.setState({ showFamilia: false, collapseEpoch: 0, collapseMode: 'manual' });
  });

  it('defaults collapseEpoch to 0 and collapseMode to manual', () => {
    const state = useTreeViewStore.getState();
    expect(state.collapseEpoch).toBe(0);
    expect(state.collapseMode).toBe('manual');
  });

  it('expandAll increments collapseEpoch and sets collapseMode to all-open', () => {
    useTreeViewStore.getState().expandAll();
    const state = useTreeViewStore.getState();
    expect(state.collapseEpoch).toBe(1);
    expect(state.collapseMode).toBe('all-open');
  });

  it('collapseAll increments collapseEpoch and sets collapseMode to all-closed', () => {
    useTreeViewStore.getState().collapseAll();
    const state = useTreeViewStore.getState();
    expect(state.collapseEpoch).toBe(1);
    expect(state.collapseMode).toBe('all-closed');
  });

  it('each call increments the epoch, even repeating the same mode', () => {
    useTreeViewStore.getState().expandAll();
    useTreeViewStore.getState().expandAll();
    expect(useTreeViewStore.getState().collapseEpoch).toBe(2);
  });

  it('does not persist collapseEpoch/collapseMode to localStorage (ephemeral view state)', () => {
    useTreeViewStore.getState().expandAll();
    const raw = localStorage.getItem('tree-view-store');
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw);
    expect(parsed.state.collapseEpoch).toBeUndefined();
    expect(parsed.state.collapseMode).toBeUndefined();
    expect(parsed.state.showFamilia).toBe(false);
  });
});
