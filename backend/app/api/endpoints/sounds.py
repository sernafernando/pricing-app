"""
Generador de sonidos TTS.

Endpoint para generar archivos MP3 de voz a partir de texto usando gTTS.
Los archivos se guardan en frontend/public/sounds/ para uso desde el browser.
"""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import get_current_user
from app.models.usuario import Usuario

router = APIRouter()

# Directorio donde se guardan los MP3 (project_root/frontend/public/sounds/)
SOUNDS_DIR = Path(__file__).resolve().parents[4] / "frontend" / "public" / "sounds"


# ── Schemas ──────────────────────────────────────────────────────────


class GenerateSoundRequest(BaseModel):
    """Generar un solo sonido."""

    text: str = Field(min_length=1, max_length=500, description="Texto a convertir en audio")
    filename: str = Field(
        min_length=1, max_length=100,
        pattern=r"^[a-zA-Z0-9_\-]+$",
        description="Nombre del archivo sin extensión (solo alfanuméricos, _ y -)",
    )
    lang: str = Field(default="es", description="Código de idioma (es, en, pt, etc.)")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"text": "Caja veintidós", "filename": "caja_22", "lang": "es"}
        }
    )


class GenerateRangeRequest(BaseModel):
    """Generar un rango de sonidos numéricos."""

    prefix: str = Field(
        default="",
        max_length=50,
        description="Prefijo para el nombre del archivo (ej: 'caja_'). Vacío = solo números.",
    )
    text_prefix: str = Field(
        default="",
        max_length=50,
        description="Prefijo de texto hablado (ej: 'Caja '). Vacío = solo el número.",
    )
    from_num: int = Field(ge=0, le=9999, description="Número inicial")
    to_num: int = Field(ge=0, le=9999, description="Número final (inclusive)")
    lang: str = Field(default="es", description="Código de idioma")
    overwrite: bool = Field(default=False, description="Sobreescribir archivos existentes")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "prefix": "caja_",
                "text_prefix": "Caja ",
                "from_num": 9,
                "to_num": 30,
                "lang": "es",
                "overwrite": False,
            }
        }
    )


class SoundFile(BaseModel):
    """Info de un archivo de sonido."""

    filename: str
    size_kb: float
    url: str


class GenerateResponse(BaseModel):
    """Resultado de generación."""

    ok: bool = True
    generated: int
    skipped: int
    files: list[str]


# ── Helpers ──────────────────────────────────────────────────────────


def _generate_mp3(text: str, filename: str, lang: str = "es", overwrite: bool = False) -> bool:
    """
    Genera un MP3 con gTTS. Retorna True si se generó, False si ya existía y no overwrite.
    """
    from gtts import gTTS

    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = SOUNDS_DIR / f"{filename}.mp3"

    if filepath.exists() and not overwrite:
        return False

    tts = gTTS(text=text, lang=lang, slow=False)
    tts.save(str(filepath))
    return True


# ── Endpoints ────────────────────────────────────────────────────────


@router.get(
    "/sounds",
    response_model=list[SoundFile],
    summary="Listar archivos de sonido disponibles",
)
def list_sounds(
    search: Optional[str] = Query(None, description="Filtrar por nombre"),
    current_user: Usuario = Depends(get_current_user),
) -> list[SoundFile]:
    """Lista todos los MP3 en el directorio de sonidos."""
    if not SOUNDS_DIR.exists():
        return []

    files = sorted(SOUNDS_DIR.glob("*.mp3"))

    if search:
        search_lower = search.lower()
        files = [f for f in files if search_lower in f.stem.lower()]

    return [
        SoundFile(
            filename=f.stem,
            size_kb=round(f.stat().st_size / 1024, 1),
            url=f"/sounds/{f.name}",
        )
        for f in files
    ]


@router.post(
    "/sounds/generate",
    response_model=GenerateResponse,
    summary="Generar un sonido TTS",
)
def generate_sound(
    payload: GenerateSoundRequest,
    current_user: Usuario = Depends(get_current_user),
) -> GenerateResponse:
    """
    Genera un archivo MP3 a partir de texto usando gTTS.
    Si el archivo ya existe, no lo sobreescribe (usar generate-range con overwrite=true).
    """
    try:
        created = _generate_mp3(payload.text, payload.filename, payload.lang, overwrite=True)
    except Exception as e:
        raise HTTPException(500, f"Error generando audio: {str(e)}")

    return GenerateResponse(
        ok=True,
        generated=1 if created else 0,
        skipped=0 if created else 1,
        files=[payload.filename] if created else [],
    )


@router.post(
    "/sounds/generate-range",
    response_model=GenerateResponse,
    summary="Generar rango de sonidos numéricos",
)
def generate_range(
    payload: GenerateRangeRequest,
    current_user: Usuario = Depends(get_current_user),
) -> GenerateResponse:
    """
    Genera MP3s para un rango de números.

    Ejemplos:
    - prefix="", text_prefix="", from=1, to=500 → archivos "1.mp3"..."500.mp3" con voz "uno"..."quinientos"
    - prefix="caja_", text_prefix="Caja ", from=9, to=30 → "caja_9.mp3"..."caja_30.mp3" con voz "Caja nueve"..."Caja treinta"
    """
    if payload.to_num < payload.from_num:
        raise HTTPException(422, "to_num debe ser >= from_num")

    if (payload.to_num - payload.from_num) > 1000:
        raise HTTPException(422, "Rango máximo: 1000 archivos por request")

    generated = []
    skipped = 0

    try:
        for n in range(payload.from_num, payload.to_num + 1):
            filename = f"{payload.prefix}{n}"
            text = f"{payload.text_prefix}{n}"
            created = _generate_mp3(text, filename, payload.lang, payload.overwrite)
            if created:
                generated.append(filename)
            else:
                skipped += 1
    except Exception as e:
        raise HTTPException(500, f"Error generando audio en número {n}: {str(e)}")

    return GenerateResponse(
        ok=True,
        generated=len(generated),
        skipped=skipped,
        files=generated,
    )


@router.delete(
    "/sounds/{filename}",
    response_model=dict,
    summary="Eliminar un archivo de sonido",
)
def delete_sound(
    filename: str,
    current_user: Usuario = Depends(get_current_user),
) -> dict:
    """Elimina un archivo MP3 del directorio de sonidos."""
    # Sanitizar para evitar path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(400, "Nombre de archivo inválido")

    filepath = SOUNDS_DIR / f"{filename}.mp3"
    if not filepath.exists():
        raise HTTPException(404, f"Archivo {filename}.mp3 no encontrado")

    filepath.unlink()
    return {"ok": True, "deleted": filename}
