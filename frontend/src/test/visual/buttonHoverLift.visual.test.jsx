/**
 * The global button lift versus a button that positions itself.
 *
 * `theme.css` lifts every button on hover with `transform: translateY(-1px)`.
 * `transform` is ONE property: that lift does not compose with a centring
 * transform, it replaces it. A search field's clear button centres itself with
 * `translateY(-50%)`, so while the global rule outranked it — `button:hover` is
 * (0,1,1) against `.clearBtn`'s (0,1,0) — hovering the button dropped it by half
 * its own height, out from under the pointer that was about to click it. You had
 * to hover it, watch it fall, and chase it down. Four buttons across several
 * screens behaved that way.
 *
 * DOM GEOMETRY, not CSS text, and on purpose. Asserting the computed
 * `transform` string would go green the moment someone writes `translateY(-50%)`
 * into a hover rule by hand in one file, which fixes nothing in the other three.
 * What must hold is that the button does not MOVE, so that is what is measured —
 * in a real browser, with a real pointer, against the real stylesheet.
 */

import { describe, it, expect, afterEach } from 'vitest';
import { userEvent } from 'vitest/browser';
import { mount } from './visualHelpers';

let host;
const styles = [];

afterEach(() => {
  host?.remove();
  host = undefined;
  while (styles.length) styles.pop().remove();
});

/**
 * The centring MUST come from a class, not a `style=` attribute. An inline style
 * beats every selector, so the global rule would never compete and this test
 * would pass with the bug still in place — verified: it did, on the first
 * attempt. `.probeClear` is (0,1,0), exactly what `.clearBtn` is, which is the
 * contest that actually happens on screen.
 */
const withStyle = (css, html) => {
  const style = document.createElement('style');
  style.textContent = css;
  document.head.append(style);
  styles.push(style);
  return mount(html);
};

describe('a positioned button is not displaced by the global hover lift', () => {
  it('keeps its centre when hovered', async () => {
    host = withStyle(
      '.probeClear { position: absolute; right: 6px; top: 50%; transform: translateY(-50%); }',
      '<div style="position: relative; height: 32px; width: 200px;">'
        + '<button type="button" class="probeClear" id="probe-clear">x</button></div>',
    );
    const button = host.querySelector('#probe-clear');
    const before = button.getBoundingClientRect().top;

    await userEvent.hover(button);

    // Half of a ~20px button is ~10px, so the bug this pins shows up as an
    // order-of-magnitude larger jump than this sub-pixel tolerance.
    expect(button.getBoundingClientRect().top).toBeCloseTo(before, 1);
  });

  it('still lifts a button that positions nothing, so the global rule survives', async () => {
    host = mount('<button type="button" id="probe-plain">go</button>');
    const button = host.querySelector('#probe-plain');
    const before = button.getBoundingClientRect().top;

    await userEvent.hover(button);

    // Deleting the global rule would be the lazy "fix" for the bug above and
    // would silently drop an interaction affordance from every button.
    expect(button.getBoundingClientRect().top).toBeCloseTo(before - 1, 1);
  });
});
