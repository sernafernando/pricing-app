import re

with open('TabRentabilidadFuera.jsx', 'r') as f:
    content = f.read()

# Agregar useMemo para keys
if 'const marcasKey' not in content:
    # Buscar después de la declaración de productosSeleccionados
    insert_point = content.find('  // Búsquedas en filtros')
    if insert_point > 0:
        memos = '''
  // Convertir arrays a strings para evitar re-renders infinitos
  const marcasKey = useMemo(() => marcasSeleccionadas.join(','), [marcasSeleccionadas.join(',')]);
  const categoriasKey = useMemo(() => categoriasSeleccionadas.join(','), [categoriasSeleccionadas.join(',')]);
  const subcategoriasKey = useMemo(() => subcategoriasSeleccionadas.join(','), [subcategoriasSeleccionadas.join(',')]);
  const productosKey = useMemo(() => productosSeleccionados.join(','), [productosSeleccionados.join(',')]);

'''
        content = content[:insert_point] + memos + content[insert_point:]

# Reemplazar setters
replacements = [
    # Limpiar filtros
    (r'setMarcasSeleccionadas\(\[\]\)', 'updateFilters({ marcas: [] })'),
    (r'setCategoriasSeleccionadas\(\[\]\)', 'updateFilters({ categorias: [] })'),
    (r'setSubcategoriasSeleccionadas\(\[\]\)', 'updateFilters({ subcategorias: [] })'),
    (r'setProductosSeleccionados\(\[\]\)', 'updateFilters({ productos: [] }); setProductosSeleccionadosDetalle([])'),
    
    # Agregar/quitar de arrays
    (r'setMarcasSeleccionadas\(\[\.\.\.marcasSeleccionadas, ([^\]]+)\]\)', r'updateFilters({ marcas: [...marcasSeleccionadas, \1] })'),
    (r'setCategoriasSeleccionadas\(\[\.\.\.categoriasSeleccionadas, ([^\]]+)\]\)', r'updateFilters({ categorias: [...categoriasSeleccionadas, \1] })'),
    (r'setSubcategoriasSeleccionadas\(\[\.\.\.subcategoriasSeleccionadas, ([^\]]+)\]\)', r'updateFilters({ subcategorias: [...subcategoriasSeleccionadas, \1] })'),
    
    # Filtrar arrays
    (r'setMarcasSeleccionadas\(marcasSeleccionadas\.filter\(([^)]+)\)\)', r'updateFilters({ marcas: marcasSeleccionadas.filter(\1) })'),
    (r'setCategoriasSeleccionadas\(categoriasSeleccionadas\.filter\(([^)]+)\)\)', r'updateFilters({ categorias: categoriasSeleccionadas.filter(\1) })'),
    (r'setSubcategoriasSeleccionadas\(subcategoriasSeleccionadas\.filter\(([^)]+)\)\)', r'updateFilters({ subcategorias: subcategoriasSeleccionadas.filter(\1) })'),
    
    # productosSeleccionados -> productosSeleccionadosDetalle en algunos contextos
    (r'productosSeleccionados\.length > 0 &&', 'productosSeleccionadosDetalle.length > 0 &&'),
    (r'productosSeleccionados\.map\(p =>', 'productosSeleccionadosDetalle.map(p =>'),
    (r'productosSeleccionados\.some\(p => p\.item_id', 'productosSeleccionados.includes(producto.item_id) ? true : productosSeleccionadosDetalle.some(p => p.item_id'),
    
    # useEffect dependencies
    (r'\[marcasSeleccionadas, categoriasSeleccionadas, subcategoriasSeleccionadas, productosSeleccionados\]', '[marcasKey, categoriasKey, subcategoriasKey, productosKey]'),
]

for pattern, replacement in replacements:
    content = re.sub(pattern, replacement, content)

with open('TabRentabilidadFuera.jsx', 'w') as f:
    f.write(content)

print("Reemplazos completados")
