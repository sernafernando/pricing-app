import { describe, it, expect, beforeEach } from 'vitest';
import { usePromoFilterStore } from './promoFilterStore';

describe('promoFilterStore', () => {
  beforeEach(() => {
    usePromoFilterStore.setState({ selectedTypes: [] });
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
});
