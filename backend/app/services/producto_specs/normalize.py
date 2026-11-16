"""Turn the three pre-load sources of a product's specs into typed, normalized values (abm-specs-productos S3/S4).

- `ml_specs`: the attributes of one ML publication (`ml_items.raw->'attributes'`). They are dirty: number fields
  sometimes carry a bare ML id ("2491679") instead of "15.6 \"", resolutions come in many spellings, models in any
  case. A number without its unit or out of the field's range is dropped, never stored.
- `nombre_erp_specs`: the ERP product name (`NB LENOVO V15 G5 IRL I7-13620H 16GB D5 1T SSD 15.6" FHD FDOS (7425)`).
- `combo_specs`: the components of a PC combo, by the ERP category of each component.

Every function returns only the fields it could read, as {field: value}; the caller decides precedence and origin.
Nothing here guesses: a notebook whose name does not name a GPU gets no GPU from it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Iterable, Optional

from app.services.producto_specs.campos import POR_NOMBRE, campos_de, en_rango

# ---------------------------------------------------------------------------------------------------------------
# Shared parsers
# ---------------------------------------------------------------------------------------------------------------

_SPACES = re.compile(r"\s+")
_TRADEMARKS = re.compile(r"[™®©]")


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = _SPACES.sub(" ", _TRADEMARKS.sub("", str(value))).strip()
    return text or None


def _upper(value: Optional[str]) -> Optional[str]:
    text = _clean(value)
    return text.upper() if text else None


def _decimal(raw: str) -> Optional[Decimal]:
    """`15.6`, `23,8`; `1.024` (a dot before exactly three digits) is a thousands separator, so 1024."""
    if re.fullmatch(r"\d{1,3}\.\d{3}", raw):
        raw = raw.replace(".", "")
    try:
        return Decimal(raw.replace(",", "."))
    except InvalidOperation:
        return None


_NUMBER_UNIT = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(GB|TB|MB|KB|\"|HZ|W)\s*$", re.IGNORECASE)


def _number_unit(value: Optional[str]) -> tuple[Optional[Decimal], Optional[str]]:
    """An ML `number_unit` value: "16 GB", "15.6 \"", "144 Hz". A bare number (an ML id) has no unit: (None, None)."""
    match = _NUMBER_UNIT.match(value or "")
    if not match:
        return None, None
    return _decimal(match.group(1)), match.group(2).upper()


def _ranged(field: str, value: Optional[Decimal]):
    """The value as the field stores it (int, or Decimal with the field's decimals), or None when out of range."""
    if value is None:
        return None
    campo = POR_NOMBRE[field]
    if not en_rango(campo, value):
        return None
    if campo.decimales:
        return value.quantize(Decimal(1).scaleb(-campo.decimales))
    if value != value.to_integral_value():
        return None
    return int(value)


def _gb(value: Optional[Decimal], unit: Optional[str]) -> Optional[Decimal]:
    if value is None:
        return None
    if unit == "GB":
        return value
    if unit in ("TB", "T"):
        return value * 1024
    return None  # MB, KB: never a notebook's RAM, disk or video memory


# --- resolution ----------------------------------------------------------------------------------------------

_RES_NUMBERS = re.compile(r"(\d{3,4})\s*(?:PX)?\s*[X*×]\s*(\d{3,4})", re.IGNORECASE)
_RES_KEYWORDS = (
    (re.compile(r"\bWQXGA\b"), "2560x1600"),
    (re.compile(r"\bWUXGA\b"), "1920x1200"),
    (re.compile(r"\b(?:QHD|2K)\b"), "2560x1440"),
    (re.compile(r"\b(?:UHD|4K)\b"), "3840x2160"),
    (re.compile(r"\b(?:FHD|FULL\s*HD)\b"), "1920x1080"),
    (re.compile(r"\bHD\+"), "1600x900"),
    (re.compile(r"\bHD\b"), "1366x768"),
)


def resolucion(value: Optional[str]) -> Optional[str]:
    text = _upper(value)
    if not text:
        return None
    match = _RES_NUMBERS.search(text)
    if match:
        width, height = int(match.group(1)), int(match.group(2))
        if 800 <= width <= 7680 and 480 <= height <= 4320:
            return f"{width}x{height}"
        return None
    for pattern, canonical in _RES_KEYWORDS:
        if pattern.search(text):
            return canonical
    return None


# --- panel, RAM type, disk type, OS ----------------------------------------------------------------------------


def panel(value: Optional[str]) -> Optional[str]:
    text = _upper(value)
    if not text:
        return None
    if "OLED" in text:
        return "OLED"
    if re.search(r"\bIPS\b", text):
        return "IPS"
    if re.search(r"\bS?VA\b", text):
        return "VA"
    if re.search(r"\bTN\b", text):
        return "TN"
    if "LED" in text:
        return "LED"
    if "LCD" in text:
        return "LCD"
    return None


_RAM_TYPE = re.compile(r"(LP)?D{1,3}R{0,2}([3-6])(X)?(?![0-9])")


def ram_tipo(value: Optional[str]) -> Optional[str]:
    """`DDR4 SDRAM`, `DD4`, `DDDR4`, `DRR4`, `DDR4-3200` are DDR4; `LPDDR5-5500` is LPDDR5. Needs a D and a digit."""
    text = _upper(value)
    if not text:
        return None
    match = _RAM_TYPE.search(text.replace(" ", ""))
    if not match or "D" not in match.group(0):
        return None
    return f"{match.group(1) or ''}DDR{match.group(2)}{match.group(3) or ''}"


def disco_tipo(value: Optional[str]) -> Optional[str]:
    text = _upper(value)
    if not text:
        return None
    if "HÍBRIDO" in text or "HIBRIDO" in text or "HYBRID" in text:
        return "Híbrido"
    if re.search(r"\bSSD\b|\bNVME\b|\bM\.?2\b", text):
        return "SSD"
    if re.search(r"\bHDD\b", text):
        return "HDD"
    return None


def so_nombre(value: Optional[str]) -> Optional[str]:
    text = _upper(value)
    if not text:
        return None
    if "WINDOWS" in text or re.search(r"\bW1[01]", text):
        return "Windows"
    if re.search(r"FREE\s*DOS|\bFDOS\b|^FREE$", text):
        return "FreeDOS"
    if "MAC" in text:
        return "macOS"
    if "LINUX" in text or "UBUNTU" in text:
        return "Linux"
    if "CHROME" in text:
        return "ChromeOS"
    if text.startswith("SIN S"):
        return "Sin sistema operativo"
    return None


def so_edicion(value: Optional[str]) -> Optional[str]:
    text = _upper(value)
    if not text:
        return None
    for token, canonical in (
        ("PRO", "Pro"),
        ("HOME", "Home"),
        ("EDUCATION", "Education"),
        ("ENTERPRISE", "Enterprise"),
    ):
        if re.search(rf"\b{token}\b", text):
            return canonical
    return None


# --- processor -------------------------------------------------------------------------------------------------

_CPU_BRANDS = {"INTEL": "Intel", "AMD": "AMD", "APPLE": "Apple", "MEDIATEK": "MediaTek", "QUALCOMM": "Qualcomm"}


def cpu_marca(value: Optional[str]) -> Optional[str]:
    text = _upper(value)
    if not text:
        return None
    for token, canonical in _CPU_BRANDS.items():
        if token in text:
            return canonical
    return None


def cpu_linea(value: Optional[str]) -> Optional[str]:
    text = _upper(value)
    if not text:
        return None
    if match := re.search(r"\bULTRA\s*([579])\b", text):
        return f"Core Ultra {match.group(1)}"
    if match := re.search(r"\bRYZEN\s*([3579])\b|\bR([3579])\b", text):
        return f"Ryzen {match.group(1) or match.group(2)}"
    if match := re.search(r"\bI([3579])\b", text):
        return f"Core i{match.group(1)}"
    if match := re.search(r"\bCORE\s*([3579])\b", text):
        return f"Core {match.group(1)}"
    for family in ("CELERON", "PENTIUM", "ATHLON"):
        if family in text:
            return family.title()
    if match := re.search(r"\b(A\d{2}|M[1-5])\b", text):
        return match.group(1)
    return None


_CPU_PREFIXES = re.compile(r"\b(?:INTEL|AMD|CORE|RYZEN|ULTRA|PROCESSOR|PROCESADOR)\b|\b[IR][3579](?:-|\s|\b)")
_CPU_MODEL = re.compile(r"\b([A-Z]{0,2}\d{2,5}[A-Z]{0,3}\d?)\b")


def cpu_modelo(value: Optional[str]) -> Optional[str]:
    """`7730u` -> 7730U, `i7-1255U` -> 1255U, `R7-260` -> 260, `Ryzen 7 5700G` -> 5700G; `i3` alone has no model."""
    text = _upper(value)
    if not text:
        return None
    if apple := re.search(r"\b(A\d{2})\s*(PRO)?\b", text):
        if "APPLE" in text or text.startswith("A"):
            return f"{apple.group(1)} Pro" if apple.group(2) else apple.group(1)
    match = _CPU_MODEL.search(_CPU_PREFIXES.sub(" ", text))
    return match.group(1) if match else None


# --- GPU -------------------------------------------------------------------------------------------------------

_NVIDIA_MODEL = re.compile(r"\b(RTX|GTX|MX)\s*-?\s*(\d{3,4})\s*(TI)?\b")
_NVIDIA_BARE = re.compile(r"^\s*(\d{4})\s*(TI)?\b")
_AMD_DEDICATED = re.compile(r"\bRX\s*(\d{4})\s*(XT)?\b")


def _gpu_marca(text: str) -> Optional[str]:
    if re.search(r"NVIDIA|GEFORCE|\bRTX|\bGTX|\bMX\s*\d", text):
        return "NVIDIA"
    if re.search(r"RADEON|\bAMD\b|VEGA", text):
        return "AMD"
    if re.search(r"INTEL|IRIS|\bUHD\b|\bARC\b", text):
        return "Intel"
    return None


def gpu_dedicada(brand: Optional[str], model: Optional[str]) -> Optional[tuple[str, Optional[str]]]:
    """(brand, model) of a dedicated GPU, or None when the text does not name one (an Intel UHD is integrated)."""
    text = " ".join(t for t in (_upper(brand), _upper(model)) if t)
    if not text:
        return None
    if match := _NVIDIA_MODEL.search(text):
        return "NVIDIA", f"{match.group(1)} {match.group(2)}{' Ti' if match.group(3) else ''}"
    marca = _gpu_marca(text)
    if marca == "NVIDIA":
        bare = _NVIDIA_BARE.match(_upper(model) or "")
        if bare:
            family = "GTX" if bare.group(1).startswith("16") else "RTX"
            return "NVIDIA", f"{family} {bare.group(1)}{' Ti' if bare.group(2) else ''}"
        return "NVIDIA", None
    if match := _AMD_DEDICATED.search(text):
        return "AMD", f"Radeon RX {match.group(1)}{' XT' if match.group(2) else ''}"
    return None


def gpu_integrada(*texts: Optional[str]) -> Optional[tuple[Optional[str], Optional[str]]]:
    """(brand, model) of an integrated GPU, or None when nothing says which. Models only from known patterns."""
    text = " ".join(t for t in (_upper(x) for x in texts) if t)
    if not text:
        return None
    marca = _gpu_marca(text)
    modelo = None
    if match := re.search(r"VEGA\s*(\d{1,2})\b", text):
        modelo = f"Radeon Vega {match.group(1)}"
    elif match := re.search(r"\b(\d{3})M\b", text):
        modelo = f"Radeon {match.group(1)}M"
    elif "IRIS XE" in text:
        modelo = "Iris Xe"
    elif "UHD" in text:
        number = re.search(r"\bUHD(?:\s*GRAPHICS)?\s*(\d{3})\b|\b(\d{3})\b", text)
        modelo = f"UHD Graphics {number.group(1) or number.group(2)}" if number else "UHD Graphics"
    elif marca == "AMD" and "RADEON" in text:
        modelo = "Radeon Graphics"
    if marca is None and modelo is None:
        return ("", None) if "INTEGRAD" in text else None
    if marca is None and modelo and modelo.startswith("Radeon"):
        marca = "AMD"
    return marca, modelo


# --- brand and model of a component ---------------------------------------------------------------------------

_PARENS = re.compile(r"\([^)]*\)")


def marca_libre(value: Optional[str]) -> Optional[str]:
    text = _upper(value)
    return text or None


def modelo_libre(value: Optional[str], *, quitar: Iterable[str] = ()) -> Optional[str]:
    """A component model: upper case, without parenthesized ERP codes and without the words in `quitar` (the
    component word and its brand, e.g. "MOTHER MSI A520M-A PRO" with brand MSI -> "A520M-A PRO")."""
    text = _upper(value)
    if not text:
        return None
    text = _PARENS.sub(" ", text)
    for word in quitar:
        if word:
            text = re.sub(rf"(?<![\w-]){re.escape(word.upper())}(?![\w-])", " ", text)
    text = _SPACES.sub(" ", text).strip(" -/")
    return text or None


# ---------------------------------------------------------------------------------------------------------------
# Source 1: ML attributes
# ---------------------------------------------------------------------------------------------------------------


def _attrs(attributes: list[dict]) -> dict[str, Optional[str]]:
    out: dict[str, Optional[str]] = {}
    for attribute in attributes or ():
        if isinstance(attribute, dict) and attribute.get("id"):
            out[attribute["id"]] = _clean(attribute.get("value_name"))
    return out


def _put(specs: dict, field: str, value) -> None:
    if value is not None and value != "":
        specs[field] = value


def _only(specs: dict, tipo: str) -> dict:
    allowed = {c.nombre for c in campos_de(tipo)}
    return {k: v for k, v in specs.items() if k in allowed}


def _number(field: str, raw: Optional[str], unit: str) -> Optional[object]:
    value, found = _number_unit(raw)
    if found != unit:
        return None
    return _ranged(field, value)


def _capacity(field: str, raw: Optional[str]) -> Optional[int]:
    value, unit = _number_unit(raw)
    return _ranged(field, _gb(value, unit))


def ml_specs(attributes: list[dict], tipo: str) -> dict:
    a = _attrs(attributes)
    specs: dict = {}

    _put(specs, "cpu_marca", cpu_marca(a.get("PROCESSOR_BRAND")))
    _put(specs, "cpu_linea", cpu_linea(a.get("PROCESSOR_LINE")) or cpu_linea(a.get("PROCESSOR_MODEL")))
    _put(specs, "cpu_modelo", cpu_modelo(a.get("PROCESSOR_MODEL")))

    _put(specs, "ram_gb", _capacity("ram_gb", a.get("RAM_MEMORY_MODULE_TOTAL_CAPACITY")))
    _put(specs, "ram_tipo", ram_tipo(a.get("RAM_MEMORY_TYPE")))

    _put(specs, "pantalla_pulgadas", _number("pantalla_pulgadas", a.get("DISPLAY_SIZE"), '"'))
    _put(specs, "pantalla_resolucion", resolucion(a.get("DISPLAY_RESOLUTION")))
    _put(specs, "pantalla_panel", panel(a.get("DISPLAY_TYPE")))
    _put(specs, "pantalla_hz", _number("pantalla_hz", a.get("DISPLAY_REFRESH_RATE"), "HZ"))

    disco = None
    for attr_id in ("TOTAL_DISK_CAPACITY", "SSD_DATA_STORAGE_CAPACITY", "DRIVE_CAPACITY", "HDD_SIZE"):
        disco = _capacity("disco_gb", a.get(attr_id))
        if disco is not None:
            break
    _put(specs, "disco_gb", disco)
    tipo_disco = disco_tipo(a.get("DISK_TYPE"))
    if tipo_disco is None and disco is not None and attr_id == "SSD_DATA_STORAGE_CAPACITY":
        tipo_disco = "SSD"
    _put(specs, "disco_tipo", tipo_disco)

    nombre_so = so_nombre(a.get("OS_NAME"))
    _put(specs, "so_nombre", nombre_so)
    if nombre_so == "Windows":
        _put(specs, "so_edicion", so_edicion(a.get("OS_EDITION")))

    dedicada = gpu_dedicada(a.get("DEDICATED_GRAPHIC_CARD_BRAND"), a.get("DEDICATED_GRAPHIC_CARD_MODEL"))
    if dedicada is None:
        dedicada = (
            gpu_dedicada(None, a.get("GRAPHIC_CARD"))
            if _NVIDIA_MODEL.search(_upper(a.get("GRAPHIC_CARD")) or "")
            else None
        )
    if dedicada:
        specs["gpu_tipo"] = "Dedicada"
        _put(specs, "gpu_marca", dedicada[0])
        _put(specs, "gpu_modelo", dedicada[1])
        _put(specs, "gpu_vram_gb", _capacity("gpu_vram_gb", a.get("VIDEO_MEMORY")))
    else:
        integrada = gpu_integrada(
            a.get("INTEGRATED_GRAPHIC_CARD_BRAND"), a.get("INTEGRATED_GRAPHIC_CARD_MODEL"), a.get("GRAPHIC_CARD")
        )
        if integrada is not None:
            specs["gpu_tipo"] = "Integrada"
            _put(specs, "gpu_marca", integrada[0])
            _put(specs, "gpu_modelo", integrada[1])

    _component(specs, "gabinete", a.get("COMPUTER_CASE_BRAND"), a.get("COMPUTER_CASE_MODEL"), ("GABINETE",))
    _component(specs, "mother", a.get("MOTHERBOARD_BRAND"), a.get("MOTHERBOARD_MODEL"), ("MOTHER", "MOTHERBOARD"))
    fuente_modelo = a.get("POWER_SUPPLY_MODEL")
    _put(
        specs, "fuente_watts", _number("fuente_watts", a.get("POWER_SUPPLY_POWER_OUTPUT"), "W") or _watts(fuente_modelo)
    )
    _component(specs, "fuente", a.get("POWER_SUPPLY_BRAND"), _sin_watts(fuente_modelo), ("FUENTE",))
    if _component(specs, "refrigeracion", a.get("COOLER_BRAND"), a.get("COOLER_MODEL"), ("COOLER",)):
        specs["refrigeracion_tipo"] = refrigeracion_tipo(a.get("COOLER_BRAND"), a.get("COOLER_MODEL"))

    return _only(specs, tipo)


def _component(specs: dict, prefix: str, brand: Optional[str], model: Optional[str], words: tuple[str, ...]) -> bool:
    marca = marca_libre(brand)
    modelo = modelo_libre(model, quitar=(*words, marca or ""))
    _put(specs, f"{prefix}_marca", marca)
    _put(specs, f"{prefix}_modelo", modelo)
    return bool(marca or modelo)


_WATTS = re.compile(r"\b(\d{3,4})\s*W\b", re.IGNORECASE)


def _watts(text: Optional[str]) -> Optional[int]:
    match = _WATTS.search(text or "")
    return _ranged("fuente_watts", Decimal(match.group(1))) if match else None


def _sin_watts(text: Optional[str]) -> Optional[str]:
    return _WATTS.sub(" ", text) if text else None


def refrigeracion_tipo(*texts: Optional[str]) -> str:
    """A cooler that does not say liquid is an air cooler (the stock ones are)."""
    text = " ".join(t for t in (_upper(x) for x in texts) if t)
    return "Líquida" if re.search(r"LIQUID|WATER|\bAIO\b", text) else "Aire"


# ---------------------------------------------------------------------------------------------------------------
# Source 2: the ERP name
# ---------------------------------------------------------------------------------------------------------------

_SIZES = re.compile(r"(\d+(?:[.,]\d+)?)\s*(GB|TB|T)\b")
_RAM_TYPE_NAME = re.compile(r"\b(LP)?DDR([345])(X)?\b|\bD([345])\b")
_SCREEN_INCHES = re.compile(r"(?<![\d.,])(\d{2}(?:[.,]\d)?)\s*(?:\"|”|''|PUL)|(?<![\d.,])(1\d(?:[.,]\d)?)\s*(?=FHD|HD)")
_HZ = re.compile(r"\b(\d{2,3})\s?HZ\b")


def _cpu_from_name(text: str) -> dict:
    specs: dict = {}
    if match := re.search(r"\bULTRA\s*([579])[\s-]+(\d{3}[A-Z]{0,2})\b", text):
        specs.update(cpu_marca="Intel", cpu_linea=f"Core Ultra {match.group(1)}", cpu_modelo=match.group(2))
    elif match := re.search(r"\bI([3579])[\s-]?(\d{3,5}[A-Z]{0,2}\d?)\b", text):
        specs.update(cpu_marca="Intel", cpu_linea=f"Core i{match.group(1)}", cpu_modelo=match.group(2))
    elif match := re.search(r"\bR(?:YZEN)?\s*([3579])\b", text):
        specs.update(cpu_marca="AMD", cpu_linea=f"Ryzen {match.group(1)}")
        # The model follows the line, unless what follows is the screen (R5 15") or the RAM (RYZEN 7 16GB).
        model = re.match(r"[\s-]+(\d{2,4}[A-Z]{0,2})\b(?!\s*(?:\"|”|''|PUL))", text[match.end() :])
        if model and not re.fullmatch(r"\d+(?:GB|TB)", model.group(1)):
            specs["cpu_modelo"] = model.group(1)
    elif match := re.search(r"\bR(\d{4}G)\b", text):
        specs.update(cpu_marca="AMD", cpu_modelo=match.group(1))
    elif match := re.search(r"\bATHLON\s*(\d{4}[A-Z]?)\b", text):
        specs.update(cpu_marca="AMD", cpu_linea="Athlon", cpu_modelo=match.group(1))
    elif match := re.search(r"\bCELERON\s*(N?\d{4})?\b", text):
        specs.update(cpu_marca="Intel", cpu_linea="Celeron")
        _put(specs, "cpu_modelo", match.group(1))
    elif match := re.search(r"\bN(\d{3,4})\b", text):
        specs.update(cpu_marca="Intel", cpu_modelo=f"N{match.group(1)}")
    elif "MACBOOK" in text and (match := re.search(r"\b(A\d{2})\s*(PRO)?", text)):
        specs.update(cpu_marca="Apple", cpu_linea=match.group(1))
        specs["cpu_modelo"] = f"{match.group(1)} Pro" if match.group(2) else match.group(1)
    return specs


def _os_from_name(text: str) -> dict:
    if re.search(r"\bW1[01]\s*P(?:RO)?\b|\bWP\b", text):
        return {"so_nombre": "Windows", "so_edicion": "Pro"}
    if re.search(r"\bW1[01]\s*H(?:OME)?\b|\bWH\b", text):
        return {"so_nombre": "Windows", "so_edicion": "Home"}
    if re.search(r"\bW1[01]\b|\bWINDOWS\b", text):
        return {"so_nombre": "Windows"}
    if re.search(r"\bFDOS\b|\bFD\b|FREE\s*DOS", text):
        return {"so_nombre": "FreeDOS"}
    if "MACBOOK" in text:
        return {"so_nombre": "macOS"}
    return {}


def nombre_erp_specs(nombre: Optional[str], tipo: str) -> dict:
    text = _upper(nombre)
    if not text:
        return {}
    # Glued tokens in real names: "I5-13420H32GB" (CPU and RAM), "15.6FHD" (size and resolution).
    text = re.sub(r"([A-Z])(\d+(?:GB|TB)\b)", r"\1 \2", text)
    text = re.sub(r"(\d)(FHD|QHD|UHD|HD)\b", r"\1 \2", text)
    specs = _cpu_from_name(text)

    sizes = [(_gb(_decimal(m.group(1)), m.group(2)), m) for m in _SIZES.finditer(text)]
    ram_at = None
    for index, (gb, _) in enumerate(sizes):
        if gb is not None and gb <= 128:
            _put(specs, "ram_gb", _ranged("ram_gb", gb))
            ram_at = index
            break
    for gb, _ in sizes[(ram_at + 1 if ram_at is not None else 0) :]:
        if gb is not None and gb >= 64:
            _put(specs, "disco_gb", _ranged("disco_gb", gb))
            break

    if match := _RAM_TYPE_NAME.search(text):
        number = match.group(2) or match.group(4)
        specs["ram_tipo"] = f"{match.group(1) or ''}DDR{number}{match.group(3) or ''}"
    _put(specs, "disco_tipo", disco_tipo(text))

    if match := _SCREEN_INCHES.search(text):
        _put(specs, "pantalla_pulgadas", _ranged("pantalla_pulgadas", _decimal(match.group(1) or match.group(2))))
    _put(specs, "pantalla_resolucion", resolucion(text))
    if match := _HZ.search(text):
        _put(specs, "pantalla_hz", _ranged("pantalla_hz", Decimal(match.group(1))))

    specs.update(_os_from_name(text))

    if dedicada := _dedicated_in_text(text):
        specs.update(gpu_tipo="Dedicada", gpu_marca=dedicada[0], gpu_modelo=dedicada[1])

    return _only(specs, tipo)


def _dedicated_in_text(text: str) -> Optional[tuple[str, str]]:
    if match := _NVIDIA_MODEL.search(text):
        return "NVIDIA", f"{match.group(1)} {match.group(2)}{' Ti' if match.group(3) else ''}"
    if match := _AMD_DEDICATED.search(text):
        return "AMD", f"Radeon RX {match.group(1)}{' XT' if match.group(2) else ''}"
    return None


# ---------------------------------------------------------------------------------------------------------------
# Source 3: the components of a PC combo
# ---------------------------------------------------------------------------------------------------------------

CAT_PROCESADORES = 48
CAT_REFRIGERACION = 49
CAT_MOTHER = 50
CAT_MEMORIAS = 51
CAT_ALMACENAMIENTO = 52
CAT_PLACAS_VIDEO = 53
CAT_GABINETES = 54
CAT_FUENTES = 55
CATEGORIAS_COMPONENTE = (
    CAT_PROCESADORES,
    CAT_REFRIGERACION,
    CAT_MOTHER,
    CAT_MEMORIAS,
    CAT_ALMACENAMIENTO,
    CAT_PLACAS_VIDEO,
    CAT_GABINETES,
    CAT_FUENTES,
)


@dataclass(frozen=True)
class Componente:
    cat_id: int
    descripcion: Optional[str]
    marca: Optional[str]
    cantidad: Decimal


def combo_specs(componentes: Iterable[Componente]) -> dict:
    """The specs a PC's combo components give, in a deterministic order (category, then description)."""
    specs: dict = {}
    ram_total = Decimal(0)
    disco_total = Decimal(0)
    for comp in sorted(componentes, key=lambda c: (c.cat_id, c.descripcion or "")):
        text = _upper(comp.descripcion) or ""
        marca = marca_libre(comp.marca)
        cantidad = comp.cantidad if comp.cantidad and comp.cantidad > 0 else Decimal(1)
        if comp.cat_id == CAT_PROCESADORES and "cpu_modelo" not in specs:
            cpu = _cpu_from_name(text)
            for field in ("cpu_marca", "cpu_linea", "cpu_modelo"):
                _put(specs, field, cpu.get(field))
            if "cpu_marca" not in specs:
                _put(specs, "cpu_marca", cpu_marca(marca))
        elif comp.cat_id == CAT_MEMORIAS:
            if match := re.search(r"(\d+)\s*GB\b", text):
                ram_total += Decimal(match.group(1)) * cantidad
            if "ram_tipo" not in specs and (match := _RAM_TYPE_NAME.search(text)):
                specs["ram_tipo"] = f"{match.group(1) or ''}DDR{match.group(2) or match.group(4)}{match.group(3) or ''}"
        elif comp.cat_id == CAT_ALMACENAMIENTO:
            if match := _SIZES.search(text):
                disco_total += (_gb(_decimal(match.group(1)), match.group(2)) or 0) * cantidad
            if "disco_tipo" not in specs:
                _put(
                    specs, "disco_tipo", disco_tipo(text) or ("HDD" if "DISCO" in text and "SSD" not in text else None)
                )
        elif comp.cat_id == CAT_PLACAS_VIDEO and "gpu_tipo" not in specs:
            if dedicada := _dedicated_in_text(text):
                specs.update(gpu_tipo="Dedicada", gpu_marca=dedicada[0], gpu_modelo=dedicada[1])
                if match := re.search(r"\b(\d{1,2})\s*GB\b", text):
                    _put(specs, "gpu_vram_gb", _ranged("gpu_vram_gb", Decimal(match.group(1))))
        elif comp.cat_id == CAT_MOTHER and "mother_marca" not in specs:
            _component(specs, "mother", marca, text, ("MOTHER", "MOTHERBOARD", "PLACA MADRE"))
        elif comp.cat_id == CAT_GABINETES and "gabinete_marca" not in specs:
            _component(specs, "gabinete", marca, text, ("GABINETE",))
        elif comp.cat_id == CAT_FUENTES and "fuente_marca" not in specs:
            _put(specs, "fuente_watts", _watts(text))
            _component(specs, "fuente", marca, _sin_watts(text), ("FUENTE",))
        elif comp.cat_id == CAT_REFRIGERACION and "refrigeracion_marca" not in specs:
            _component(specs, "refrigeracion", marca, text, ("COOLER", "REFRIGERACION", "REFRIGERACIÓN"))
            specs["refrigeracion_tipo"] = refrigeracion_tipo(text)
    _put(specs, "ram_gb", _ranged("ram_gb", ram_total) if ram_total else None)
    _put(specs, "disco_gb", _ranged("disco_gb", disco_total) if disco_total else None)
    return specs


# ---------------------------------------------------------------------------------------------------------------
# The winning publication when a product links to several
# ---------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidatoMl:
    mla: str
    actualizado: Optional[datetime]
    specs: dict


def ganador(candidatos: Iterable[CandidatoMl]) -> Optional[CandidatoMl]:
    """The most complete publication (most fields read), then the most recently updated on ML, then the lowest
    MLA id: deterministic, so a re-preload with the same data picks the same one."""
    ordered = sorted(
        candidatos,
        key=lambda c: (-len(c.specs), -(c.actualizado.timestamp() if c.actualizado else 0), c.mla),
    )
    return ordered[0] if ordered else None
