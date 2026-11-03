import { useCallback, useState } from 'react';

const EMPTY = new Map();

/**
 * The colors painted since the rows loaded (S8), on the layer on show (`equipo`, '' = the global one): what this
 * screen paints and what anyone paints, applied as Productos applies it. `colors` holds the products' colors by product
 * id (`producto_color:changed`); `own`, the publications' own colors by MLA (`publicacion_color:changed`,
 * seleccion-por-publicacion S3; null = unpainted, the publication falls back to its product's). An event of the layer
 * on show sets the color (`marcado`); one of the global layer while a team's is on show sets the hint (`hintGlobal`);
 * another team's and the Tienda colors are not shown here. Another layer, or other rows (`rowsKey`: the filters the
 * rows were asked with), starts empty: those rows come with their own colors.
 *
 * `apply` takes the products' SSE event (`{ data: { equipo_id, is_global, item_ids, vista, color } }`); `applyOwn`
 * the publications' (`{ data: { equipo_id, is_global, item_ids, color } }`, its `item_ids` are MLAs).
 */
export default function useColorOverlay(equipo, rowsKey = '') {
  const key = `${equipo}|${rowsKey}`;
  const [overlay, setOverlay] = useState({ key, colors: EMPTY, own: EMPTY });

  const update = useCallback(
    (data, slice) => {
      if (!data?.item_ids?.length) return;
      const onShow = equipo ? !data.is_global && String(data.equipo_id) === String(equipo) : Boolean(data.is_global);
      const field = onShow ? 'marcado' : data.is_global && equipo ? 'hintGlobal' : null;
      if (!field) return;
      setOverlay((current) => {
        const fresh = current.key === key ? current : { key, colors: EMPTY, own: EMPTY };
        // `slice`: 'colors' (keyed by product id) or 'own' (keyed by MLA).
        const next = new Map(fresh[slice]);
        for (const id of data.item_ids) next.set(String(id), { ...next.get(String(id)), [field]: data.color ?? null });
        return { ...fresh, [slice]: next };
      });
    },
    [equipo, key],
  );

  const apply = useCallback(
    (event) => {
      if (event?.data?.vista === 'ml') update(event.data, 'colors');
    },
    [update],
  );
  const applyOwn = useCallback((event) => update(event?.data, 'own'), [update]);

  const current = overlay.key === key;
  return { colors: current ? overlay.colors : EMPTY, own: current ? overlay.own : EMPTY, apply, applyOwn };
}
