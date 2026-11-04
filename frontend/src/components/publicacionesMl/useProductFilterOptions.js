import { useEffect, useState } from 'react';
import { productosAPI } from '../../services/api';

const NONE = [];

const csvParams = (entries) => Object.fromEntries(entries.filter(([, values]) => values.length > 0).map(([key, values]) => [key, values.join(',')]));

/** Loads one option list; on failure it stays empty (the panel still shows what is selected, so it can be unticked). */
function useOptionList(load, key) {
  const [list, setList] = useState(NONE);
  useEffect(() => {
    let active = true;
    load()
      .then((loaded) => {
        if (active) setList(loaded ?? NONE);
      })
      .catch(() => {
        if (active) setList(NONE);
      });
    return () => {
      active = false;
    };
    // `key` is what the request depends on; `load` is a fresh closure every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return list;
}

/** The catalog's grouped subcategorías kept to `ids`; a category left with none is dropped. */
const onlySubcategorias = (groups, ids) => {
  const wanted = new Set(ids);
  return groups
    .map((group) => ({ ...group, subcategorias: (group.subcategorias ?? []).filter((sub) => wanted.has(sub.id)) }))
    .filter((group) => group.subcategorias.length > 0);
};

/**
 * The option lists of the product filters. With the screen's `facet` (`/items` `facets.product`), the brands and
 * subcategorías are those of the publications under every OTHER active filter of the screen, like Productos
 * (`pubml-filtros` S2): the brands as the facet names them, the subcategorías as the catalog names and groups them,
 * kept to the facet's ids. Without it (before the first response, or when it failed) they are the catalog's,
 * from the endpoints Productos uses: the brands narrowed by the picked subcategories and PMs, the subcategories
 * (grouped by category) by the picked brands and PMs. Categories and PMs are always the catalog's whole lists.
 *
 * @param {{marcas: string[], subcategorias: number[], pms: number[]}} value  the panel's value (plain names, ids)
 * @param {{marcas: string[], subcategorias: number[]} | null} [facet]
 */
export default function useProductFilterOptions(value, facet = null) {
  const marcaParams = csvParams([
    ['subcategorias', value.subcategorias],
    ['pms', value.pms],
  ]);
  // With the facet the subcategorías are named from the whole catalog: the facet already narrows them.
  const subcategoriaParams = facet
    ? {}
    : csvParams([
        ['marcas', value.marcas],
        ['pms', value.pms],
      ]);
  const catalogMarcas = useOptionList(
    () => (facet ? Promise.resolve(NONE) : productosAPI.marcas(marcaParams).then((response) => response.data?.marcas)),
    facet ? 'facet' : JSON.stringify(marcaParams),
  );
  const catalogSubcategorias = useOptionList(
    () => productosAPI.subcategorias(subcategoriaParams).then((response) => response.data?.categorias),
    JSON.stringify(subcategoriaParams),
  );
  const categorias = useOptionList(() => productosAPI.categorias().then((response) => response.data?.categorias), 'all');
  const pms = useOptionList(
    () => productosAPI.pms().then((response) => (Array.isArray(response.data) ? response.data.map(({ id, nombre, email }) => ({ id, nombre, email })) : NONE)),
    'all',
  );
  const marcas = facet ? (facet.marcas ?? NONE) : catalogMarcas;
  const subcategorias = facet ? onlySubcategorias(catalogSubcategorias, facet.subcategorias ?? NONE) : catalogSubcategorias;
  return { marcas, categorias, subcategorias, pms };
}
