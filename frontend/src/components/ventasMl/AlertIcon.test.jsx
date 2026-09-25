import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import AlertIcon from './AlertIcon';

// ventas-ml-rediseno PR14.T5 (LISTING R29, design D13): `alert_level` is
// the unified per-row alert the backend already computes (`_alert_level`
// in `ml_ventas_ops.py`: `"error" | "warning" | "ok"` — NOT "danger",
// verified against the actual function), replacing ad-hoc per-field FE
// flags. `ok` renders NOTHING — a row with nothing wrong gets no icon, not
// a green checkmark cluttering every row.
describe('AlertIcon', () => {
  it('renders nothing for alert_level="ok"', () => {
    const { container } = render(<AlertIcon level="ok" />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders a warning icon for alert_level="warning"', () => {
    const { container } = render(<AlertIcon level="warning" />);
    expect(container.querySelector('[data-alert-level="warning"]')).toBeInTheDocument();
  });

  it('renders a distinct error icon for alert_level="error"', () => {
    const { container: warnContainer } = render(<AlertIcon level="warning" />);
    const { container: errorContainer } = render(<AlertIcon level="error" />);
    expect(errorContainer.querySelector('[data-alert-level="error"]')).toBeInTheDocument();
    // warning and error must not render the same icon markup
    expect(errorContainer.innerHTML).not.toBe(warnContainer.innerHTML);
  });

  it('carries the reason as an accessible title when provided', () => {
    const { container } = render(<AlertIcon level="error" reason="Margen negativo detectado" />);
    expect(container.querySelector('[title="Margen negativo detectado"]')).toBeInTheDocument();
  });

  // A `title` ATTRIBUTE on an `<svg>` element renders no native tooltip in
  // browsers — only a `<title>` CHILD element does, or a `title` attribute
  // on an ordinary (non-SVG) host element. The real, hoverable tooltip must
  // live on a wrapping element, never on the svg attribute alone.
  it('puts the hoverable title on a real (non-svg) wrapping element, not only on the svg attribute', () => {
    const { container } = render(<AlertIcon level="error" reason="Margen negativo detectado" />);
    const titled = container.querySelector('[title="Margen negativo detectado"]');
    expect(titled).toBeInTheDocument();
    expect(titled.tagName.toLowerCase()).not.toBe('svg');
  });

  it('renders nothing for an unrecognised level, failing safe instead of throwing', () => {
    const { container } = render(<AlertIcon level="something_new" />);
    expect(container).toBeEmptyDOMElement();
  });
});
