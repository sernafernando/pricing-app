import {
  Laptop,
  Wifi,
  Printer,
  Keyboard,
  Speaker,
  Smartphone,
  HardDrive,
  Home,
  Monitor,
  MemoryStick,
  Zap,
  CircuitBoard,
  Box,
  Cpu,
  Plug,
  Snowflake,
  Puzzle,
  Mouse,
  Watch,
  Package,
  Heart,
  Wrench,
} from 'lucide-react';

/**
 * categoryIcon — `item_category` → icon lookup (ventas-ml-rediseno PR14.T5,
 * LISTING R28, design D13).
 *
 * `item_category` is `productos_erp.categoria`, free-text ERP data with no
 * enum backing it (verified live: "NOTEBOOK", "CELULAR, TABLET y EBOOK",
 * "AUDIO Y PARLANTES", "MONITORES Y TV STICKS", ...). Matching is by
 * KEYWORD, not exact equality — a future ERP category with a slightly
 * different label (e.g. a new "CELULARES" without the rest of the phrase)
 * must still resolve, and an entirely new category falls back to `Package`
 * rather than throwing or rendering nothing.
 *
 * Order matters: longer/more specific keywords are checked before shorter
 * ones that could otherwise shadow them (e.g. "TABLET" before a bare "PC").
 */
const CATEGORY_ICON_RULES = [
  [/NOTEBOOK/, Laptop],
  [/CONECTIVIDAD/, Wifi],
  [/IMPRESORA/, Printer],
  [/TECLADO/, Keyboard],
  [/MOUSE/, Mouse],
  [/AUDIO|PARLANTE/, Speaker],
  [/CELULAR|TABLET|EBOOK|SMARTPHONE/, Smartphone],
  [/ALMACENAMIENTO/, HardDrive],
  [/MUEBLE|HOGAR/, Home],
  [/MONITOR|\bTV\b/, Monitor],
  [/MEMORIA/, MemoryStick],
  [/ELECTRICIDAD/, Zap],
  [/MOTHER/, CircuitBoard],
  [/GABINETE/, Box],
  [/PROCESADOR|^PC ARMADA/, Cpu],
  [/FUENTE/, Plug],
  [/REFRIGERACION/, Snowflake],
  [/ACCESORIO/, Puzzle],
  [/PERIFERICO/, Mouse],
  [/SMARTWATCH/, Watch],
  [/CUIDADO PERSONAL/, Heart],
  [/HERRAMIENTA/, Wrench],
  [/PLACA DE VIDEO/, Cpu],
  [/ELECTRO/, Zap],
];

export function getCategoryIcon(category) {
  if (!category) return Package;
  const normalized = String(category).trim().toUpperCase();
  if (!normalized) return Package;
  for (const [pattern, Icon] of CATEGORY_ICON_RULES) {
    if (pattern.test(normalized)) return Icon;
  }
  return Package;
}
