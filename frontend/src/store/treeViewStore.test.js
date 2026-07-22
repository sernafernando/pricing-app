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
