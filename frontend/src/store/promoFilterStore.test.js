import { describe, it, expect, beforeEach } from 'vitest';
import { usePromoFilterStore } from './promoFilterStore';

describe('promoFilterStore', () => {
  beforeEach(() => {
    usePromoFilterStore.setState({ selectedTypes: [], selectedNames: {} });
  });

  it('starts with no types selected (show all)', () => {
    expect(usePromoFilterStore.getState().selectedTypes).toEqual([]);
  });

  it('toggleType adds a type when not selected', () => {
    usePromoFilterStore.getState().toggleType('SMART');
    expect(usePromoFilterStore.getState().selectedTypes).toEqual(['SMART']);
  });

  it('toggleType removes a type when already selected', () => {
    usePromoFilterStore.getState().toggleType('SMART');
    usePromoFilterStore.getState().toggleType('SMART');
    expect(usePromoFilterStore.getState().selectedTypes).toEqual([]);
  });

  it('toggleType supports multiple selected types', () => {
    usePromoFilterStore.getState().toggleType('SMART');
    usePromoFilterStore.getState().toggleType('DEAL');
    expect(usePromoFilterStore.getState().selectedTypes).toEqual(['SMART', 'DEAL']);
  });

  it('clear empties selectedTypes', () => {
    usePromoFilterStore.getState().toggleType('SMART');
    usePromoFilterStore.getState().clear();
    expect(usePromoFilterStore.getState().selectedTypes).toEqual([]);
  });

  it('starts with no selectedNames (show all names)', () => {
    expect(usePromoFilterStore.getState().selectedNames).toEqual({});
  });

  it('toggleName adds a name under its type', () => {
    usePromoFilterStore.getState().toggleName('DEAL', '2x1');
    expect(usePromoFilterStore.getState().selectedNames).toEqual({ DEAL: ['2x1'] });
  });

  it('toggleName removes a name and drops the key entirely when the last name is removed', () => {
    usePromoFilterStore.getState().toggleName('DEAL', '2x1');
    usePromoFilterStore.getState().toggleName('DEAL', '2x1');
    expect(usePromoFilterStore.getState().selectedNames).toEqual({});
  });

  it('toggleName supports multiple names for the same type', () => {
    usePromoFilterStore.getState().toggleName('DEAL', '2x1');
    usePromoFilterStore.getState().toggleName('DEAL', '3x2');
    expect(usePromoFilterStore.getState().selectedNames).toEqual({ DEAL: ['2x1', '3x2'] });
  });

  it('toggleName keeps other types untouched', () => {
    usePromoFilterStore.getState().toggleName('DEAL', '2x1');
    usePromoFilterStore.getState().toggleName('SMART', 'Promo Smart');
    expect(usePromoFilterStore.getState().selectedNames).toEqual({
      DEAL: ['2x1'],
      SMART: ['Promo Smart'],
    });
  });

  it('clearNamesForType removes only that type', () => {
    usePromoFilterStore.getState().toggleName('DEAL', '2x1');
    usePromoFilterStore.getState().toggleName('SMART', 'Promo Smart');
    usePromoFilterStore.getState().clearNamesForType('DEAL');
    expect(usePromoFilterStore.getState().selectedNames).toEqual({ SMART: ['Promo Smart'] });
  });

  it('toggleType does NOT prune selectedNames for the deselected type', () => {
    usePromoFilterStore.getState().toggleName('DEAL', '2x1');
    usePromoFilterStore.getState().toggleType('DEAL');
    usePromoFilterStore.getState().toggleType('DEAL');
    expect(usePromoFilterStore.getState().selectedNames).toEqual({ DEAL: ['2x1'] });
  });

  it('clear() resets both selectedTypes and selectedNames', () => {
    usePromoFilterStore.getState().toggleType('SMART');
    usePromoFilterStore.getState().toggleName('DEAL', '2x1');
    usePromoFilterStore.getState().clear();
    expect(usePromoFilterStore.getState().selectedTypes).toEqual([]);
    expect(usePromoFilterStore.getState().selectedNames).toEqual({});
  });
});
