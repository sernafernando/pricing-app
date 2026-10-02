import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import Sparkline from './Sparkline';

describe('Sparkline', () => {
  it('draws one path through the known points and marks the last one', () => {
    const { container } = render(<Sparkline values={[1, 3, 2, 5]} width={100} height={20} label="Tendencia" />);
    const path = container.querySelector('path');
    expect(path.getAttribute('d').match(/[ML]/g)).toHaveLength(4);
    expect(container.querySelector('circle')).not.toBeNull();
    expect(container.querySelector('svg').getAttribute('aria-label')).toBe('Tendencia');
  });

  it('skips missing points instead of drawing them as zero', () => {
    const { container } = render(<Sparkline values={[10, null, null, 20]} width={100} height={20} />);
    expect(container.querySelector('path').getAttribute('d').match(/[ML]/g)).toHaveLength(2);
  });

  it('draws a flat dashed baseline and no path when nothing is known', () => {
    const { container } = render(<Sparkline values={[null, null]} width={100} height={20} />);
    expect(container.querySelector('path')).toBeNull();
    expect(container.querySelector('line')).not.toBeNull();
  });

  it('carries its tone as a data attribute for the stylesheet', () => {
    const { container } = render(<Sparkline values={[1, 2]} tone="down" />);
    expect(container.querySelector('svg').dataset.tone).toBe('down');
  });
});
