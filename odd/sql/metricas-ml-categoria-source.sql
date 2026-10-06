-- Read-only. Measures whether productos_erp.categoria is a usable parent for subcategoria.
-- Q1: products / with categoria / with subcategoria
SELECT count(*) AS productos,
       count(*) FILTER (WHERE nullif(trim(categoria),'') IS NOT NULL) AS con_categoria,
       count(*) FILTER (WHERE subcategoria_id IS NOT NULL) AS con_subcategoria,
       count(*) FILTER (WHERE subcategoria_id IS NOT NULL AND nullif(trim(categoria),'') IS NULL) AS subcat_sin_categoria
FROM productos_erp;

-- Q2: subcategorias whose products map to MORE THAN ONE productos_erp.categoria (case/space-insensitive)
SELECT p.subcategoria_id, sg.nombre_subcategoria, sg.nombre_categoria AS categoria_del_grupo,
       count(DISTINCT upper(trim(coalesce(p.categoria,'')))) AS categorias_distintas,
       array_agg(DISTINCT upper(trim(coalesce(p.categoria,'')))) AS categorias,
       count(*) AS productos
FROM productos_erp p
LEFT JOIN subcategorias_grupos sg ON sg.subcat_id = p.subcategoria_id
WHERE p.subcategoria_id IS NOT NULL
GROUP BY p.subcategoria_id, sg.nombre_subcategoria, sg.nombre_categoria
HAVING count(DISTINCT upper(trim(coalesce(p.categoria,'')))) > 1
ORDER BY productos DESC;

-- Q3: products whose productos_erp.categoria differs from their subcategory's nombre_categoria
SELECT count(*) AS productos_con_categoria_distinta,
       count(DISTINCT p.subcategoria_id) AS subcategorias_afectadas
FROM productos_erp p
JOIN subcategorias_grupos sg ON sg.subcat_id = p.subcategoria_id
WHERE upper(trim(coalesce(p.categoria,''))) <> upper(trim(coalesce(sg.nombre_categoria,'')));

-- Q3b: the top 20 mismatching (categoria del producto, categoria del grupo) pairs
SELECT upper(trim(coalesce(p.categoria,''))) AS categoria_producto,
       upper(trim(coalesce(sg.nombre_categoria,''))) AS categoria_grupo,
       count(*) AS productos, count(DISTINCT p.subcategoria_id) AS subcategorias
FROM productos_erp p
JOIN subcategorias_grupos sg ON sg.subcat_id = p.subcategoria_id
WHERE upper(trim(coalesce(p.categoria,''))) <> upper(trim(coalesce(sg.nombre_categoria,'')))
GROUP BY 1,2 ORDER BY productos DESC LIMIT 20;

-- Q4: products with a subcategoria_id that has no row in subcategorias_grupos
SELECT count(*) AS productos_con_subcat_huerfana
FROM productos_erp p LEFT JOIN subcategorias_grupos sg ON sg.subcat_id = p.subcategoria_id
WHERE p.subcategoria_id IS NOT NULL AND sg.subcat_id IS NULL;
