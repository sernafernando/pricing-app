"""The spec fields of a product (notebooks and PCs first): one typed column per field in `producto_specs`.

Numeric fields hold a number in a fixed unit (GB, inches, Hz, W) and accept only a plausible range; categorical
fields hold one value of the field's normalized list (`producto_spec_valores`), so a filter shows "DDR4" once.
A PC has the notebook's fields minus the screen, plus case, power supply, motherboard and cooling.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

NOTEBOOK = "notebook"
PC = "pc"
TIPOS = (NOTEBOOK, PC)

# ERP category of each product type, and the notebook subcategories that are accessories, not notebooks.
CATEGORIAS = {46: NOTEBOOK, 47: PC}
SUBCATEGORIAS_EXCLUIDAS = (3908, 3964)  # FUNDAS, BASE REFRIGERANTE

# Where a field's value came from. `manual` and `no_aplica` (set by hand: the field does not apply to this product, its
# value stays empty and it counts as complete) are never overwritten by a pre-load.
ORIGEN_ML = "ml"
ORIGEN_NOMBRE_ERP = "erp_name"
ORIGEN_COMBO = "combo"
ORIGEN_MANUAL = "manual"
ORIGEN_NO_APLICA = "no_aplica"
ORIGENES = (ORIGEN_ML, ORIGEN_NOMBRE_ERP, ORIGEN_COMBO, ORIGEN_MANUAL, ORIGEN_NO_APLICA)
ORIGENES_A_MANO = (ORIGEN_MANUAL, ORIGEN_NO_APLICA)

NUMERICO = "numerico"
CATEGORICO = "categorico"


@dataclass(frozen=True)
class Campo:
    nombre: str
    grupo: str
    etiqueta: str
    tipo: str  # NUMERICO | CATEGORICO
    unidad: Optional[str] = None
    minimo: Optional[Decimal] = None
    maximo: Optional[Decimal] = None
    decimales: int = 0
    solo_pc: bool = False
    solo_notebook: bool = False

    def aplica(self, tipo_producto: str) -> bool:
        if self.solo_pc:
            return tipo_producto == PC
        if self.solo_notebook:
            return tipo_producto == NOTEBOOK
        return True


def _num(nombre, grupo, etiqueta, unidad, minimo, maximo, decimales=0, **kw) -> Campo:
    return Campo(nombre, grupo, etiqueta, NUMERICO, unidad, Decimal(str(minimo)), Decimal(str(maximo)), decimales, **kw)


def _cat(nombre, grupo, etiqueta, **kw) -> Campo:
    return Campo(nombre, grupo, etiqueta, CATEGORICO, **kw)


PROCESADOR = "Procesador"
MEMORIA = "Memoria"
PANTALLA = "Pantalla"
ALMACENAMIENTO = "Almacenamiento"
SISTEMA_OPERATIVO = "Sistema operativo"
PLACA_DE_VIDEO = "Placa de video"
GABINETE = "Gabinete"
FUENTE = "Fuente"
MOTHER = "Mother"
REFRIGERACION = "Refrigeración"

CAMPOS: tuple[Campo, ...] = (
    _cat("cpu_marca", PROCESADOR, "Marca"),
    _cat("cpu_linea", PROCESADOR, "Línea"),
    _cat("cpu_modelo", PROCESADOR, "Modelo"),
    _num("ram_gb", MEMORIA, "Capacidad", "GB", 1, 256),
    _cat("ram_tipo", MEMORIA, "Tipo"),
    _num("pantalla_pulgadas", PANTALLA, "Tamaño", "pulgadas", 7, 40, decimales=1, solo_notebook=True),
    _cat("pantalla_resolucion", PANTALLA, "Resolución", solo_notebook=True),
    _cat("pantalla_panel", PANTALLA, "Tipo de panel", solo_notebook=True),
    _num("pantalla_hz", PANTALLA, "Frecuencia", "Hz", 30, 500, solo_notebook=True),
    _num("disco_gb", ALMACENAMIENTO, "Capacidad total", "GB", 16, 16384),
    _cat("disco_tipo", ALMACENAMIENTO, "Tipo"),
    _cat("so_nombre", SISTEMA_OPERATIVO, "Sistema"),
    _cat("so_edicion", SISTEMA_OPERATIVO, "Edición"),
    _cat("gpu_tipo", PLACA_DE_VIDEO, "Tipo"),
    _cat("gpu_marca", PLACA_DE_VIDEO, "Marca"),
    _cat("gpu_modelo", PLACA_DE_VIDEO, "Modelo"),
    _num("gpu_vram_gb", PLACA_DE_VIDEO, "Memoria de video", "GB", 1, 48),
    _cat("gabinete_marca", GABINETE, "Marca", solo_pc=True),
    _cat("gabinete_modelo", GABINETE, "Modelo", solo_pc=True),
    _cat("fuente_marca", FUENTE, "Marca", solo_pc=True),
    _cat("fuente_modelo", FUENTE, "Modelo", solo_pc=True),
    _num("fuente_watts", FUENTE, "Potencia", "W", 100, 2000, solo_pc=True),
    _cat("mother_marca", MOTHER, "Marca", solo_pc=True),
    _cat("mother_modelo", MOTHER, "Modelo", solo_pc=True),
    _cat("refrigeracion_tipo", REFRIGERACION, "Tipo", solo_pc=True),
    _cat("refrigeracion_marca", REFRIGERACION, "Marca", solo_pc=True),
    _cat("refrigeracion_modelo", REFRIGERACION, "Modelo", solo_pc=True),
)

POR_NOMBRE: dict[str, Campo] = {c.nombre: c for c in CAMPOS}
NOMBRES: tuple[str, ...] = tuple(POR_NOMBRE)
CATEGORICOS: tuple[str, ...] = tuple(c.nombre for c in CAMPOS if c.tipo == CATEGORICO)
NUMERICOS: tuple[str, ...] = tuple(c.nombre for c in CAMPOS if c.tipo == NUMERICO)

# Seeded normalized lists of the fields whose vocabulary is closed in practice. Brands and models are open: their
# lists grow with what the pre-load finds and what an operator adds.
VALORES_INICIALES: dict[str, tuple[str, ...]] = {
    "cpu_marca": ("Intel", "AMD", "Apple", "MediaTek", "Qualcomm"),
    "ram_tipo": ("DDR3", "DDR4", "DDR5", "LPDDR4", "LPDDR4X", "LPDDR5", "LPDDR5X"),
    "pantalla_panel": ("IPS", "OLED", "VA", "TN", "LED", "LCD"),
    "disco_tipo": ("SSD", "HDD", "Híbrido"),
    "so_nombre": ("Windows", "FreeDOS", "macOS", "Linux", "ChromeOS", "Sin sistema operativo"),
    "so_edicion": ("Home", "Pro", "Education", "Enterprise"),
    "gpu_tipo": ("Integrada", "Dedicada"),
    "gpu_marca": ("NVIDIA", "AMD", "Intel", "Apple"),
    "refrigeracion_tipo": ("Aire", "Líquida"),
}


def campos_de(tipo_producto: str) -> tuple[Campo, ...]:
    return tuple(c for c in CAMPOS if c.aplica(tipo_producto))


def clave(valor: str) -> str:
    """The identity of a categorical value: case and spacing do not make two values ("16 gb" is "16 GB")."""
    return " ".join(valor.split()).casefold()


def en_rango(campo: Campo, valor: Decimal) -> bool:
    return campo.minimo <= valor <= campo.maximo
