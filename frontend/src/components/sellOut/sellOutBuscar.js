import { productosAPI } from '../../services/api';

/** The catalog search of the sell-out product pickers (per-product amounts, reparto): `SellInBuscador` options. */
export const buscarProductos = (search) =>
  productosAPI.listar({ search, page_size: 10 }).then(({ data }) =>
    (data?.productos ?? []).map((p) => ({ key: p.item_id, label: `${p.codigo} · ${p.descripcion}`, sub: p.marca, producto: p })),
  );
