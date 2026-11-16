/**
 * The approved ABM de productos mock's own data (handoffs/diseno-abm-productos/mock-aprobado.html, real prod
 * products), shaped as the backend answers it, so the real screen can be put next to the mock section by section.
 */

const fila = (item_id, nombre, ean, stock, tipo = null, specs_completos = null, specs_total = null) => ({
  item_id,
  codigo: ean,
  ean,
  nombre,
  marca: null,
  stock,
  tipo,
  specs_completos,
  specs_total,
});

export const LISTA = [
  fila(4444, 'IMPRESORA XEROX B110 LASER B/N USB WIFI (2367)', '095205052367', 1433),
  fila(455, 'Adaptador Bluetooth 5.0 TP-Link UB500 Nano USB', '4897098683446', 964),
  fila(70, 'CAMARA IP WIFI TP LINK TAPO C200 SD DAY/NIGHT MOV REMOTO', '1210002615013', 944),
  fila(646, 'RESMA PUNAX A4 210X297MM 500H 75GRS', '7792540294805', 743),
  fila(22, 'EXTENSOR DE RANGO WIFI TP LINK RE200 AC750', '6935364080433', 708),
  fila(4486, 'LAMPARA SMART TP LINK TAPO L530E RGB E27 (3217)', '1210002613217', 694),
  fila(4874, 'NB ASUS E1504FA 15.6" R5-40 8GB D5 512GB  FDOS (9921)', '4711636459921', 131, 'notebook', 9, 17),
  fila(4897, 'NB ASUS E1504FA 15.6" R5-40 8GB D5 512GB  W11H', '4711636459921-WH', 131, 'notebook', 17, 17),
  fila(4500, 'NB HP 255 G10 R3 7335U 8GB D5 512GB 15" W11H (2993)', '199642202993', 128, 'notebook', 12, 17),
  fila(4900, 'NB HP 250R G10 I5-120U 16GB D5-5200 512GB 15.6" FDOS (2653)', '821844832653', 99, 'notebook', 11, 17),
  fila(4907, 'NB HP 250R G10 I5-120U 16GB D5-5200 512GB 15.6" W11H (2653)', '821844832653-WH', 99, 'notebook', 9, 17),
  fila(4908, 'NB HP 250R G10 I5-120U 16GB D5-5200 512GB 15.6" W11P (2653)', '821844832653-WP', 99, 'notebook', 10, 17),
  fila(4193, 'NB LENOVO V15 G5 IRL I3-1315U 8GB D5 512GB SSD 15.6" FHD FDOS (7449)', '199271947449', 98, 'notebook', 16, 17),
  fila(4237, 'NB ASUS ZENBOOK 14 R7-8840HS 16GB D5 1TB SSD W11H (1131)', '4711387961131', 94, 'notebook', 16, 17),
  fila(4626, 'PC ARMADA ATHLON 3000G AM4 8GB 128GB SSD KIT W11H', 'PC-3000G-A-8G-128', 15, 'pc', 16, 23),
  fila(466, 'PC ARMADA GAMER R4600G A320M 16GB 240GB', 'PC-R4600G-A-16G', 0, 'pc', 5, 23),
  fila(468, 'PC ARMADA GAMER R5600G A320M 16GB 240GB', 'PC-R5600G-A-16G', 0, 'pc', 5, 23),
];

export const TOTALES = { todos: 4561, notebook: 671, pc: 133 };

const campo = (valor, gbp = valor, extra = {}) => ({ valor, gbp, overrideado: valor !== gbp, ...extra });

const ML_TITULO_455 = 'Adaptador Bluetooth 5.0 Usb Nano Tp-link Ub500 Para Pc Notebook';
const ML_DESC_455 =
  'Adaptador Nano Tp. Link UB500 SB Bluetooth 5.0 Marca: Tp-link Color: Negro SKu: UB500 Requisitos del sistema: Los sistemas operativos compatibles incluyen Win 11 / 10 / 8.1 / 7 Estándares y Protocolos: Bluetooth 5.0 Interfaz: USB 2.0 Conectividad inalámbrica : proporciona una comunicación estable y conveniente entre los dispositivos Bluetooth y su PC o ordenador portátil Contenido del Paquete: Ada';
const GBP_DESC_455 =
  'ADAPTADOR BLUETOOTH USB NANO TP-LINK UB400 NOTEBOOK PC ESPECIFICACIONES TÉCNICAS - Marca: Tp-link - Modelo: Ub400 - Estándares y Protocolos Bluetooth 4.0 - Interfaz USB 2.0 - Dimensiones 14.8 × 6.8 × 18.9 mm (0.58 × 0.27 × 0.74 in) - Certificaciones FCC, CE, RoHS - Contenido del Paquete UB400 Adaptador nano USB Bluetooth 4.0. - Guía de Instalación Rápida - Requisitos del sistema Windows 10/8.1/8/7';
const TN_455 = 'Adaptador TP-Link Nano USB Bluetooth 5.0 UB500';

export const MAESTRO = {
  455: {
    item_id: 455,
    codigo: '4897098683446',
    tipo_specs: null,
    campos: {
      nombre: campo('Adaptador Bluetooth 5.0 TP-Link UB500 Nano USB', 'BLUETOOTH TPLINK NANO USB UB500 BT 5.0'),
      ean: campo('4897098683446'),
      codigo_fabricante: campo('UB500'),
      marca_id: campo(12, 12, { nombre: 'TP-LINK', gbp_nombre: 'TP-LINK' }),
      categoria_id: campo(61, 61, { nombre: 'CONECTIVIDAD', gbp_nombre: 'CONECTIVIDAD' }),
      subcategoria_id: campo(3855, 3855, { nombre: 'ANTENAS WIFI', gbp_nombre: 'ANTENAS WIFI' }),
      garantia_dias: campo(180),
      peso_g: campo(35),
      ancho_cm: campo(14),
      largo_cm: campo(9),
      alto_cm: campo(3),
    },
    unidades_caja: null,
    textos: {
      titulo_ml: { fuente: 'ml', elegida: false, valor: ML_TITULO_455, fuentes: { ml: ML_TITULO_455, tn: TN_455, gbp: 'Adaptador Bluetooth Usb Nano Tp-link Ub400 Para Notebook Pc' } },
      titulo_web: { fuente: 'tn', elegida: false, valor: TN_455, fuentes: { tn: TN_455, ml: ML_TITULO_455, nombre: 'Adaptador Bluetooth 5.0 TP-Link UB500 Nano USB' } },
      descripcion_ml: { fuente: 'ml', elegida: false, valor: ML_DESC_455, fuentes: { ml: ML_DESC_455, tn: null, gbp: GBP_DESC_455 } },
      descripcion_web: { fuente: 'tn', elegida: true, valor: null, fuentes: { tn: null, ml: ML_DESC_455, gbp: GBP_DESC_455 } },
    },
    mla_ganadora: 'MLA1824169308',
    lectura: {
      costo: 4.6606,
      moneda_costo: 'USD',
      iva: 10.5,
      stock: 964,
      precio_lista_ml: 11999,
      proveedor: 'PC-ARTS ARGENTINA S.A.',
      publicaciones_ml: 29,
      tn_producto_id: 266585719,
      tn_publicado: true,
    },
    can_edit: true,
    can_edit_unidades: true,
  },
  4874: {
    item_id: 4874,
    codigo: '4711636459921',
    tipo_specs: 'notebook',
    campos: {
      nombre: campo('NB ASUS E1504FA 15.6" R5-40 8GB D5 512GB  FDOS (9921)'),
      ean: campo('4711636459921'),
      codigo_fabricante: campo('E1504FA-BQ2783'),
      marca_id: campo(7, 7, { nombre: 'ASUS', gbp_nombre: 'ASUS' }),
      categoria_id: campo(46, 46, { nombre: 'NOTEBOOK', gbp_nombre: 'NOTEBOOK' }),
      subcategoria_id: campo(3901, 3901, { nombre: 'OFICINA', gbp_nombre: 'OFICINA' }),
      garantia_dias: campo(180),
      peso_g: campo(2700),
      ancho_cm: campo(49),
      largo_cm: campo(7),
      alto_cm: campo(29),
    },
    unidades_caja: null,
    textos: {
      titulo_ml: { fuente: 'ml', elegida: false, valor: 'Asus E1504fa 15.6 R5-40 8gb 512gb Fdos', fuentes: { ml: 'Asus E1504fa 15.6 R5-40 8gb 512gb Fdos', tn: null, gbp: 'NB ASUS ZENBOOK I5-1135G7 8GB 512GB W10 ESP (0109)' } },
      titulo_web: { fuente: 'ml', elegida: false, valor: 'Asus E1504fa 15.6 R5-40 8gb 512gb Fdos', fuentes: { tn: null, ml: 'Asus E1504fa 15.6 R5-40 8gb 512gb Fdos', nombre: 'NB ASUS E1504FA 15.6" R5-40 8GB D5 512GB  FDOS (9921)' } },
      descripcion_ml: { fuente: null, elegida: false, valor: null, fuentes: { ml: null, tn: null, gbp: null } },
      descripcion_web: { fuente: null, elegida: false, valor: null, fuentes: { tn: null, ml: null, gbp: null } },
    },
    mla_ganadora: 'MLA2255804121',
    lectura: { costo: 487.31, moneda_costo: 'USD', iva: 10.5, stock: 131, precio_lista_ml: null, proveedor: 'AIR S.R.L.', publicaciones_ml: 5, tn_producto_id: null, tn_publicado: null },
    can_edit: true,
    can_edit_unidades: true,
  },
};

export const VINCULOS = {
  455: {
    item_id: 455,
    origen: 'sku',
    tn: { tn_product_id: 266585719, nombre: TN_455, skus: ['4897098683446'], precio: 20633, published: true, item_id: 455 },
    can_edit: true,
  },
  4874: { item_id: 4874, origen: null, tn: null, can_edit: true },
};

const NOTEBOOK = [
  ['cpu_marca', 'Procesador', 'Marca', 'categorico', null],
  ['cpu_linea', 'Procesador', 'Línea', 'categorico', null],
  ['cpu_modelo', 'Procesador', 'Modelo', 'categorico', null],
  ['ram_gb', 'Memoria', 'Capacidad', 'numerico', 'GB'],
  ['ram_tipo', 'Memoria', 'Tipo', 'categorico', null],
  ['pantalla_pulgadas', 'Pantalla', 'Tamaño', 'numerico', 'pulgadas'],
  ['pantalla_resolucion', 'Pantalla', 'Resolución', 'categorico', null],
  ['pantalla_panel', 'Pantalla', 'Tipo de panel', 'categorico', null],
  ['pantalla_hz', 'Pantalla', 'Frecuencia', 'numerico', 'Hz'],
  ['disco_gb', 'Almacenamiento', 'Capacidad total', 'numerico', 'GB'],
  ['disco_tipo', 'Almacenamiento', 'Tipo', 'categorico', null],
  ['so_nombre', 'Sistema operativo', 'Sistema', 'categorico', null],
  ['so_edicion', 'Sistema operativo', 'Edición', 'categorico', null],
  ['gpu_tipo', 'Placa de video', 'Tipo', 'categorico', null],
  ['gpu_marca', 'Placa de video', 'Marca', 'categorico', null],
  ['gpu_modelo', 'Placa de video', 'Modelo', 'categorico', null],
  ['gpu_vram_gb', 'Placa de video', 'Memoria de video', 'numerico', 'GB'],
];

export const CAMPOS_SPECS = NOTEBOOK.map(([nombre, grupo, etiqueta, tipo, unidad]) => ({ nombre, grupo, etiqueta, tipo, unidad }));

const VALORES_4874 = {
  cpu_marca: ['AMD', 'erp_name'],
  cpu_linea: ['Ryzen 5', 'erp_name'],
  cpu_modelo: ['40', 'erp_name'],
  ram_gb: [8, 'erp_name'],
  ram_tipo: ['DDR5', 'erp_name'],
  pantalla_pulgadas: [15.6, 'erp_name'],
  pantalla_resolucion: ['1920x1080', 'manual'],
  disco_gb: [512, 'erp_name'],
  so_nombre: ['FreeDOS', 'erp_name'],
};

export const SPECS_4874 = {
  item_id: 4874,
  tipo: 'notebook',
  campos: NOTEBOOK.map(([c, grupo, etiqueta]) => ({ campo: c, grupo, etiqueta, valor: VALORES_4874[c]?.[0] ?? null, origen: VALORES_4874[c]?.[1] ?? null })),
  completos: 9,
  total: 17,
  can_edit: true,
};

export const MARCAS = [
  { id: 7, nombre: 'ASUS', activa: true, productos: 300 },
  { id: 20, nombre: 'GAUSS', activa: true, productos: 80 },
  { id: 3, nombre: 'HP', activa: true, productos: 120 },
  { id: 5, nombre: 'LENOVO', activa: true, productos: 150 },
  { id: 12, nombre: 'TP-LINK', activa: true, productos: 520 },
  { id: 30, nombre: 'XEROX', activa: true, productos: 40 },
];

export const CATEGORIAS = [
  { id: 61, nombre: 'CONECTIVIDAD', activa: true, subcategorias: [{ id: 3855, nombre: 'ANTENAS WIFI', activa: true }] },
  { id: 46, nombre: 'NOTEBOOK', activa: true, subcategorias: [{ id: 3901, nombre: 'OFICINA', activa: true }] },
];
