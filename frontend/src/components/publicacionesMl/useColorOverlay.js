import { useCallback, useState } from 'react';

const EMPTY = new Map();

/**
 * The product colors painted since the rows loaded (S8), by product id, on the layer on show (`equipo`, '' = the
 * global one): what this screen paints and what anyone paints (`producto_color:changed`, applied as Productos
 * applies it). An event of the layer on show sets the color (`marcado`); one of the global layer while a team's is on
 * show sets the hint (`hintGlobal`); another team's and the Tienda colors are not shown here. Another layer, or other
 * rows (`rowsKey`: the filters the rows were asked with), starts empty: those rows come with their own colors.
 *
 * `apply` takes the SSE event (`{ data: { equipo_id, is_global, item_ids, vista, color } }`).
 */
export default function useColorOverlay(equipo, rowsKey = '') {
  const key = `${equipo}|${rowsKey}`;
  const [overlay, setOverlay] = useState({ key, colors: EMPTY });

  const apply = useCallback(
    (event) => {
      const data = event?.data;
      if (!data || data.vista !== 'ml' || !data.item_ids?.length) return;
      const onShow = equipo ? !data.is_global && String(data.equipo_id) === String(equipo) : Boolean(data.is_global);
      const field = onShow ? 'marcado' : data.is_global && equipo ? 'hintGlobal' : null;
      if (!field) return;
      setOverlay((current) => {
        const colors = new Map(current.key === key ? current.colors : EMPTY);
        for (const id of data.item_ids) colors.set(String(id), { ...colors.get(String(id)), [field]: data.color ?? null });
        return { key, colors };
      });
    },
    [equipo, key],
  );

  return { colors: overlay.key === key ? overlay.colors : EMPTY, apply };
}
