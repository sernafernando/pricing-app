"""Unit tests for OC-match extract/match/excel/acta (no live Gemini)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.models.tb_brand import TBBrand
from app.models.tb_category import TBCategory
from app.models.tb_item import TBItem
from app.models.tb_subcategory import TBSubCategory
from app.services.oc_match import acta as acta_mod
from app.services.oc_match import candidatos as candidatos_mod
from app.services.oc_match import match as match_mod
from app.services.oc_match.acta import acta_cierre
from app.services.oc_match.candidatos import match_fabricante_exacto
from app.services.oc_match.excel import RechazoExcel, generar
from app.services.oc_match.maestro import Articulo, cargar_maestro, es_combo_interno, sin_combos_internos
from app.services.oc_match.match import match_renglones

_SERVICES = Path(__file__).resolve().parents[2] / "app" / "services" / "oc_match"


def _art(
    item_id: str = "101",
    ean: str = "7790123456789",
    desc: str = "Mouse Logitech M196 Negro",
    fabricante: str = "",
) -> Articulo:
    return Articulo(
        item_id=item_id,
        ean=ean,
        descripcion=desc,
        categoria="Perifericos",
        subcategoria="Mouse",
        marca="Logitech",
        fabricante=fabricante,
    )


def _usd_ok_matched(*, tipo_cambio: object = None) -> dict[str, Any]:
    return {
        "proveedor_razon_social": "Prov USD",
        "moneda": "USD",
        "tipo_cambio": tipo_cambio,
        "renglones": [
            {
                "descripcion": "Mouse Logitech M196 Negro",
                "cantidad": 1,
                "precio_unitario": 10,
                "moneda": "USD",
                "match": {
                    "estado": "ok",
                    "via": "gemini",
                    "item_id": "101",
                    "ean": "7790123456789",
                    "descripcion_gbp": "Mouse Logitech M196 Negro",
                    "confianza": "alta",
                    "motivo": "ok",
                },
            }
        ],
        "resumen": {"ok": 1, "no_hallado": 0, "omitido": 0},
    }


class TestSkipFabricanteExacto:
    def test_match_renglones_does_not_call_fabricante_exacto(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Even if fab exact would hit, Gemini path is used and the helper is not called."""
        art = _art(fabricante="M196-UNIQUE")
        extraido = {
            "moneda": "ARS",
            "renglones": [
                {
                    "descripcion": "Mouse Logitech M196 Negro",
                    "cantidad": 1,
                    "precio_unitario": 10,
                    "moneda": "ARS",
                    "codigo_fabricante": "M196-UNIQUE",
                    "ean": "7790123456789",
                    "omitir": False,
                }
            ],
        }
        assert match_fabricante_exacto(extraido["renglones"][0], {"M196UNIQUE": [art]}) is art

        spy = MagicMock(side_effect=AssertionError("match_fabricante_exacto must not be used"))
        monkeypatch.setattr(candidatos_mod, "match_fabricante_exacto", spy)
        monkeypatch.setattr(match_mod, "match_fabricante_exacto", spy, raising=False)

        pool = MagicMock()
        pool.generate_json.return_value = {
            "decisiones": [
                {
                    "indice": 0,
                    "item_id": "101",
                    "ean": "7790123456789",
                    "confianza": "alta",
                    "motivo": "gemini",
                }
            ]
        }
        result = match_renglones(extraido, [art], pool)
        spy.assert_not_called()
        assert result["renglones"][0]["match"]["via"] == "gemini"
        assert result["renglones"][0]["match"]["estado"] == "ok"

    def test_match_module_source_has_no_fabricante_exact_call(self) -> None:
        source = (_SERVICES / "match.py").read_text(encoding="utf-8")
        assert "match_fabricante_exacto(" not in source
        assert "indice_fabricante(" not in source
        assert "from app.services.oc_match.candidatos import" in source
        assert "match_fabricante_exacto" not in source.split("def match_renglones", 1)[-1]


class TestMaestroNotProductosErp:
    def test_maestro_source_uses_tb_item_not_productos_erp(self) -> None:
        source = (_SERVICES / "maestro.py").read_text(encoding="utf-8")
        assert "TBItem" in source
        assert "item_code" in source
        assert "ProductoERP" not in source
        assert "from app.models.producto" not in source

    def test_sin_combos_internos_filters_config_ean(self) -> None:
        arts = [
            _art(item_id="1", ean="7790123456789"),
            _art(item_id="2", ean="7790123456789-16"),
        ]
        kept = sin_combos_internos(arts)
        assert [a.item_id for a in kept] == ["1"]
        assert es_combo_interno("7790123456789-16")

    def test_cargar_maestro_from_tb_item(self, db) -> None:
        db.add_all(
            [
                TBBrand(comp_id=1, brand_id=7, brand_desc="Logitech"),
                TBCategory(comp_id=1, cat_id=3, cat_desc="Perifericos"),
                TBSubCategory(comp_id=1, cat_id=3, subcat_id=4, subcat_desc="Mouse"),
                TBItem(
                    comp_id=1,
                    item_id=101,
                    item_code="7790123456789",
                    item_desc="Mouse Logitech M196 Negro",
                    cat_id=3,
                    subcat_id=4,
                    brand_id=7,
                ),
            ]
        )
        db.flush()
        arts = cargar_maestro(db)
        assert len(arts) == 1
        assert arts[0].ean == "7790123456789"
        assert arts[0].item_id == "101"
        assert arts[0].fabricante == ""
        assert arts[0].marca == "Logitech"
        assert arts[0].categoria == "Perifericos"
        assert arts[0].subcategoria == "Mouse"


class TestUnmatchedPacksInActa:
    def test_acta_flags_unmatched_pack_line(self) -> None:
        matched = {
            "proveedor_razon_social": "Prov",
            "moneda": "ARS",
            "renglones": [
                {
                    "descripcion": "Cable HDMI 3 pack especial",
                    "cantidad": 1,
                    "match": {
                        "estado": "no_hallado",
                        "confianza": "baja",
                        "motivo": "pack 3 no coincide con 1-pack del maestro",
                        "candidatos": [],
                    },
                }
            ],
            "resumen": {"ok": 0, "no_hallado": 1, "omitido": 0},
        }
        text = acta_cierre(matched, {"Sucursal": "PASTORIZA"})
        assert "NO HALLADOS" in text
        assert "Cable HDMI 3 pack especial" in text
        assert "pack 3 no coincide" in text
        assert "confianza=baja" in text
        assert "Sucursal: PASTORIZA" in text
        assert "Solicitante" not in text
        assert "Tipo documento:" in text

    def test_acta_includes_tipo_documento_line(self) -> None:
        matched = {
            "proveedor_razon_social": "Prov",
            "tipo_documento": "factura",
            "nro_documento": "0001-99",
            "nro_pedido": "PED-184465",
            "renglones": [],
            "resumen": {"ok": 0, "no_hallado": 0, "omitido": 0},
        }
        text = acta_cierre(matched, {"Sucursal": "PASTORIZA"})
        assert "Tipo documento: factura" in text
        assert text.count("Tipo documento:") == 1

    def test_acta_prints_confianza_for_ok_media_and_alta(self) -> None:
        matched = {
            "proveedor_razon_social": "Prov",
            "moneda": "ARS",
            "renglones": [
                {
                    "descripcion": "Mouse Alta",
                    "cantidad": 1,
                    "match": {
                        "estado": "ok",
                        "via": "gemini",
                        "ean": "111",
                        "descripcion_gbp": "Mouse Alta GBP",
                        "confianza": "alta",
                        "motivo": "match claro",
                    },
                },
                {
                    "descripcion": "Mouse Media",
                    "cantidad": 1,
                    "match": {
                        "estado": "ok",
                        "via": "gemini",
                        "ean": "222",
                        "descripcion_gbp": "Mouse Media GBP",
                        "confianza": "media",
                        "motivo": "color ambiguo",
                    },
                },
            ],
            "resumen": {"ok": 2, "no_hallado": 0, "omitido": 0},
        }
        text = acta_cierre(matched, {"Sucursal": "PASTORIZA"})
        assert "confianza=alta" in text
        assert "confianza=media" in text
        assert "color ambiguo" in text
        assert "match claro" in text


class TestUsdSinTc:
    def test_generar_usd_sin_tc_raises_and_does_not_write_xlsx(self, tmp_path: Path) -> None:
        dest = tmp_path / "carga.xlsx"
        with pytest.raises(RechazoExcel, match="tipo de cambio"):
            generar(_usd_ok_matched(tipo_cambio=None), dest)
        assert not dest.exists()

    def test_generar_usd_con_tc_writes_xlsx(self, tmp_path: Path) -> None:
        dest = tmp_path / "carga.xlsx"
        info = generar(_usd_ok_matched(tipo_cambio=1200), dest)
        assert dest.is_file()
        assert info["filas"] == 1


class TestNoMailInPipeline:
    def test_pipeline_modules_have_no_mail_imports(self) -> None:
        files = [
            _SERVICES / "worker.py",
            _SERVICES / "extract.py",
            _SERVICES / "match.py",
            _SERVICES / "excel.py",
            _SERVICES / "acta.py",
            _SERVICES / "doc_refs.py",
            _SERVICES / "gemini_pool.py",
            _SERVICES / "maestro.py",
            _SERVICES / "candidatos.py",
        ]
        banned = ("smtp", "enviar_mail", "notificacion_service", "smtplib")
        for path in files:
            source = path.read_text(encoding="utf-8").lower()
            for token in banned:
                assert token not in source, f"{path.name} contains {token}"
        assert "asunto_cierre" not in acta_mod.__dict__
