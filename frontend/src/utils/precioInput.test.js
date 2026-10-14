/**
 * Strict reading of a price typed in es-AR: a wrong number on the money path
 * must be rejected, never silently truncated (parseFloat('120.000') is 120).
 */
import { describe, it, expect } from 'vitest';
import { parsePrecioInput, formatPrecioInput, parseMarkupInput, formatMarkupInput } from './precioInput';

describe('parsePrecioInput', () => {
  it.each([
    ['120000', 120000],
    ['120000,5', 120000.5],
    ['120000,50', 120000.5],
    ['120.000', 120000],
    ['120.000,50', 120000.5],
    ['1.234.567,89', 1234567.89],
    ['999', 999],
    ['0', 0],
    ['0,99', 0.99],
    ['  120000  ', 120000],
  ])('reads %j as %d', (text, expected) => {
    expect(parsePrecioInput(text)).toBe(expected);
  });

  it.each([
    ['', 'empty'],
    ['   ', 'blank'],
    ['12abc', 'trailing letters'],
    ['abc', 'letters'],
    ['120000.5', 'a dot that is not a thousands separator'],
    ['1.5', 'a dot before fewer than 3 digits'],
    ['12.0000', 'a dot before more than 3 digits'],
    ['1234.567', 'a first group longer than 3 digits'],
    ['120.000.5', 'a broken last group'],
    ['120,5,5', 'two commas'],
    ['120,555', 'more than 2 decimals'],
    ['1.000,', 'a comma without decimals'],
    [',5', 'no integer part'],
    ['-100', 'a negative price'],
    ['$100', 'a currency sign'],
    ['1 000', 'an inner space'],
    ['1e5', 'an exponent'],
  ])('rejects %j (%s)', (text) => {
    expect(parsePrecioInput(text)).toBeNull();
  });

  it('rejects anything that is not text', () => {
    expect(parsePrecioInput(null)).toBeNull();
    expect(parsePrecioInput(undefined)).toBeNull();
  });
});

describe('formatPrecioInput', () => {
  it.each([
    [98500.5, '98500,5'],
    [120000, '120000'],
    [0.99, '0,99'],
    [null, ''],
    [undefined, ''],
  ])('writes %j as %j, which reads back to the same price', (value, text) => {
    expect(formatPrecioInput(value)).toBe(text);
    if (value != null) expect(parsePrecioInput(text)).toBe(value);
  });

  it.each([
    [98500.123, '98500,12'],
    [0.1 + 0.2, '0,3'],
  ])('rounds %j to 2 decimals (%j) so an untouched save is never refused', (value, text) => {
    expect(formatPrecioInput(value)).toBe(text);
    expect(parsePrecioInput(text)).not.toBeNull();
  });
});

describe('parseMarkupInput', () => {
  it.each([
    ['25', 25],
    ['25,5', 25.5],
    ['25,55', 25.55],
    ['0', 0],
    ['-0', 0],
    ['-3', -3],
    ['-3,5', -3.5],
    ['120', 120],
    ['  18  ', 18],
    ['25%', 25],
    ['25,5 %', 25.5],
  ])('reads %j as %d', (text, expected) => {
    expect(parseMarkupInput(text)).toBe(expected);
  });

  it.each([
    ['', 'empty'],
    ['   ', 'blank'],
    ['abc', 'letters'],
    ['25abc', 'trailing letters'],
    ['25.5', 'a decimal dot'],
    ['1.000', 'a thousands separator'],
    ['25,555', 'more than 2 decimals'],
    ['25,', 'a comma without decimals'],
    [',5', 'no integer part'],
    ['--3', 'two signs'],
    ['+3', 'a plus sign'],
    ['3-', 'a trailing sign'],
    ['- 3', 'a detached sign'],
    ['1e2', 'an exponent'],
    ['25%%', 'two percent signs'],
    ['%25', 'a leading percent sign'],
  ])('rejects %j (%s)', (text) => {
    expect(parseMarkupInput(text)).toBeNull();
  });

  it('rejects anything that is not text', () => {
    expect(parseMarkupInput(null)).toBeNull();
    expect(parseMarkupInput(25)).toBeNull();
  });
});

describe('formatMarkupInput', () => {
  it.each([
    [18.4, '18,4'],
    [-2, '-2'],
    [22.346, '22,35'],
    [0, '0'],
    [null, ''],
    [undefined, ''],
  ])('writes %j as %j, which the parser reads back', (value, text) => {
    expect(formatMarkupInput(value)).toBe(text);
    if (value != null) expect(parseMarkupInput(text)).not.toBeNull();
  });
});
