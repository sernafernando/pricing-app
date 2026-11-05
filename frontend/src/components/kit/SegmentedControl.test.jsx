import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SegmentedControl from './SegmentedControl';

const OPTIONS = [
  { value: 'product_ads', label: 'Product Ads' },
  { value: 'display', label: 'Display' },
];

describe('SegmentedControl', () => {
  it('switches to another option and marks the current one, as always', async () => {
    const onChange = vi.fn();
    render(<SegmentedControl label="Canal" options={OPTIONS} value="product_ads" onChange={onChange} />);
    expect(screen.getByRole('button', { name: 'Product Ads' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Display' })).toBeEnabled();
    await userEvent.click(screen.getByRole('button', { name: 'Display' }));
    expect(onChange).toHaveBeenCalledWith('display');
  });

  it('keeps its value when disabled', async () => {
    const onChange = vi.fn();
    render(<SegmentedControl label="Canal" options={OPTIONS} value="display" onChange={onChange} disabled />);
    expect(screen.getByRole('button', { name: 'Display' })).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(screen.getByRole('button', { name: 'Product Ads' }));
    expect(onChange).not.toHaveBeenCalled();
  });
});
