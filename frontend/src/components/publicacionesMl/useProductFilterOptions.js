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

/**
 * The option lists of the product filters, from the endpoints Productos uses for the same filters: the brands
 * narrowed by the picked subcategories and PMs, the subcategories (grouped by category) by the picked brands and
 * PMs, every category, and the PMs that hold a brand. They are the catalog's lists, not counts of this screen.
 *
 * @param {{marcas: string[], subcategorias: number[], pms: number[]}} value  the panel's value (plain names, ids)
 */
export default function useProductFilterOptions(value) {
  const marcaParams = csvParams([
    ['subcategorias', value.subcategorias],
    ['pms', value.pms],
  ]);
  const subcategoriaParams = csvParams([
    ['marcas', value.marcas],
    ['pms', value.pms],
  ]);
  const marcas = useOptionList(
    () => productosAPI.marcas(marcaParams).then((response) => response.data?.marcas),
    JSON.stringify(marcaParams),
  );
  const subcategorias = useOptionList(
    () => productosAPI.subcategorias(subcategoriaParams).then((response) => response.data?.categorias),
    JSON.stringify(subcategoriaParams),
  );
  const categorias = useOptionList(() => productosAPI.categorias().then((response) => response.data?.categorias), 'all');
  const pms = useOptionList(
    () => productosAPI.pms().then((response) => (Array.isArray(response.data) ? response.data.map(({ id, nombre }) => ({ id, nombre })) : NONE)),
    'all',
  );
  return { marcas, categorias, subcategorias, pms };
}
