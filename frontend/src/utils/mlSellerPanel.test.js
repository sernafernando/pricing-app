import { describe, it, expect } from 'vitest';
import { buildMlSellerListingUrl, buildMlSellerPromosUrl, mlaNumber } from './mlSellerPanel';

const LISTING = 'https://vendedores.mercadolibre.com.ar/publicaciones?page=1&sort=DEFAULT&search=';
const PROMOS = 'https://vendedores.mercadolibre.com.ar/publicaciones/listado/promos?page=1&search=';

describe('mlaNumber', () => {
  it.each([
    ['MLA1173065146', '1173065146'],
    ['mla1173065146', '1173065146'],
    ['Mla42', '42'],
    ['  MLA42  ', '42'],
    ['1173065146', '1173065146'],
    [1173065146, '1173065146'],
    ['MLAMLA1', 'MLA1'],
    ['', null],
    ['MLA', null],
    ['   ', null],
    [null, null],
    [undefined, null],
  ])('%j -> %j', (input, expected) => {
    expect(mlaNumber(input)).toBe(expected);
  });
});

describe('seller panel URLs', () => {
  it.each([
    ['MLA1173065146', `${LISTING}1173065146`, `${PROMOS}1173065146`],
    ['mla99', `${LISTING}99`, `${PROMOS}99`],
    ['MLA1 & 2', `${LISTING}1%20%26%202`, `${PROMOS}1%20%26%202`],
    ['MLA', null, null],
    [null, null, null],
  ])('%j -> listing %j, promos %j', (input, listing, promos) => {
    expect(buildMlSellerListingUrl(input)).toBe(listing);
    expect(buildMlSellerPromosUrl(input)).toBe(promos);
  });
});
