// Throwaway probe for the incremental CI skip (closed without merging).
import { expect, test } from 'vitest';

test('ci probe frontend', () => {
  expect(1 + 1).toBe(3);
});
