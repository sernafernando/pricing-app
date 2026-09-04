from pydantic import ValidationError
import pytest

from app.api.endpoints.productos_shared import ConfigCuotasMasivoRequest, ConfigCuotasMasivoResponse
from app.api.endpoints.pricing import (
    AplicarMarkupMasivoRequest,
    AplicarMarkupMasivoResponse,
    AplicarMarkupMasivoItemResult,
)


def test_aplicar_markup_masivo_requiere_markup_positivo():
    with pytest.raises(ValidationError):
        AplicarMarkupMasivoRequest(markup_objetivo=0, item_ids=[1])


def test_aplicar_markup_masivo_acepta_porcentaje():
    req = AplicarMarkupMasivoRequest(markup_objetivo=5, item_ids=[10, 20])
    assert req.markup_objetivo == 5
    assert req.pricelist_id == 4
    assert req.recalcular_cuotas is True


def test_aplicar_markup_masivo_rechaza_lista_vacia():
    with pytest.raises(ValidationError):
        AplicarMarkupMasivoRequest(markup_objetivo=5, item_ids=[])


def test_aplicar_markup_masivo_acepta_hasta_100_items():
    req = AplicarMarkupMasivoRequest(markup_objetivo=5, item_ids=list(range(1, 101)))
    assert len(req.item_ids) == 100


def test_aplicar_markup_masivo_rechaza_mas_de_100_items():
    with pytest.raises(ValidationError):
        AplicarMarkupMasivoRequest(markup_objetivo=5, item_ids=list(range(1, 102)))


def test_config_cuotas_masivo_requiere_items():
    with pytest.raises(ValidationError):
        ConfigCuotasMasivoRequest(item_ids=[])


def test_config_cuotas_masivo_rechaza_mas_de_100_items():
    with pytest.raises(ValidationError):
        ConfigCuotasMasivoRequest(item_ids=list(range(1, 102)))


def test_config_cuotas_masivo_null_explicito_queda_en_dump():
    req = ConfigCuotasMasivoRequest(item_ids=[1], markup_adicional_cuotas_custom=None)
    dumped = req.model_dump(exclude_unset=True)
    assert dumped["markup_adicional_cuotas_custom"] is None


def test_config_cuotas_masivo_no_incluye_campos_omitidos():
    req = ConfigCuotasMasivoRequest(item_ids=[1], markup_adicional_cuotas_custom=3)
    dumped = req.model_dump(exclude_unset=True)
    assert dumped["markup_adicional_cuotas_custom"] == 3
    assert "markup_adicional_cuotas_pvp_custom" not in dumped
    assert "recalcular_cuotas_auto" not in dumped


def test_aplicar_markup_masivo_response_schema():
    res = AplicarMarkupMasivoResponse(
        total=1,
        ok=1,
        errores=0,
        resultados=[AplicarMarkupMasivoItemResult(item_id=10, codigo="ABC", ok=True, precio_nuevo=15000)],
    )
    assert res.ok == 1
    assert res.resultados[0].item_id == 10


def test_config_cuotas_masivo_response_schema():
    res = ConfigCuotasMasivoResponse(ok=3, total=3)
    assert res.ok == 3
    assert res.total == 3
