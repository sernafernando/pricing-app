"""Product specs (abm-specs-productos T1, S3/S4): the dirty ML attributes, the ERP name and the combo components of a
notebook or PC become typed, normalized values. Out-of-range or unreadable values are left empty, never stored.

The examples are the ones measured in prod (2026-11-16).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.producto_specs import normalize as n
from app.services.producto_specs.campos import NOTEBOOK, PC


def attr(attr_id: str, value_name):
    return {"id": attr_id, "value_name": value_name}


def ml(*attrs, tipo=NOTEBOOK) -> dict:
    return n.ml_specs(list(attrs), tipo)


class TestMlNumbers:
    @pytest.mark.parametrize("raw", ["2491679", '2491677 "', '1.59 "', "7876751"])
    def test_a_screen_size_out_of_range_or_without_unit_is_left_empty(self, raw):
        assert "pantalla_pulgadas" not in ml(attr("DISPLAY_SIZE", raw))

    def test_a_screen_size_in_inches_is_a_number(self):
        assert ml(attr("DISPLAY_SIZE", '15.6 "'))["pantalla_pulgadas"] == Decimal("15.6")

    @pytest.mark.parametrize("raw", ["579564", "98857", "19054354"])
    def test_ram_garbage_ids_are_rejected(self, raw):
        assert "ram_gb" not in ml(attr("RAM_MEMORY_MODULE_TOTAL_CAPACITY", raw))

    def test_ram_in_gb(self):
        assert ml(attr("RAM_MEMORY_MODULE_TOTAL_CAPACITY", "16 GB"))["ram_gb"] == 16

    @pytest.mark.parametrize("raw", ["7873264", "0 Hz", "13631016"])
    def test_refresh_rate_garbage_is_rejected(self, raw):
        assert "pantalla_hz" not in ml(attr("DISPLAY_REFRESH_RATE", raw))

    def test_refresh_rate(self):
        assert ml(attr("DISPLAY_REFRESH_RATE", "144 Hz"))["pantalla_hz"] == 144

    @pytest.mark.parametrize(("raw", "gb"), [("512 GB", 512), ("1 TB", 1024), ("2 TB", 2048)])
    def test_disk_capacity_in_gb(self, raw, gb):
        assert ml(attr("TOTAL_DISK_CAPACITY", raw))["disco_gb"] == gb

    @pytest.mark.parametrize("raw", ["0", "0 MB", "1 GB", "1.024 TB", "6724461"])
    def test_disk_capacity_garbage_is_rejected(self, raw):
        assert "disco_gb" not in ml(attr("TOTAL_DISK_CAPACITY", raw))

    def test_the_ssd_capacity_fills_the_disk_when_the_total_is_unreadable_and_says_ssd(self):
        specs = ml(attr("TOTAL_DISK_CAPACITY", "0"), attr("SSD_DATA_STORAGE_CAPACITY", "480 GB"))
        assert (specs["disco_gb"], specs["disco_tipo"]) == (480, "SSD")

    @pytest.mark.parametrize("raw", ["0 KB", "384 GB", "7873270"])
    def test_video_memory_garbage_is_rejected(self, raw):
        specs = ml(attr("DEDICATED_GRAPHIC_CARD_MODEL", "RTX 3050"), attr("VIDEO_MEMORY", raw))
        assert "gpu_vram_gb" not in specs

    def test_power_supply_watts(self):
        assert ml(attr("POWER_SUPPLY_POWER_OUTPUT", "550 W"), tipo=PC)["fuente_watts"] == 550


class TestMlCategories:
    @pytest.mark.parametrize("raw", ["1366px x 768px", "1366 px x 768 px", "1366 PX X 768 PX", "HD"])
    def test_resolution_spellings_become_one_value(self, raw):
        assert ml(attr("DISPLAY_RESOLUTION", raw))["pantalla_resolucion"] == "1366x768"

    @pytest.mark.parametrize(
        "raw", ["1920x1080", "1920 x 1080", "1920X1080P", "1920*1080 IPS Full HD", "FHD (1920x1080)", "FHD"]
    )
    def test_full_hd_spellings(self, raw):
        assert ml(attr("DISPLAY_RESOLUTION", raw))["pantalla_resolucion"] == "1920x1080"

    @pytest.mark.parametrize(
        ("raw", "panel"),
        [("IPS LCD", "IPS"), ("LCD/LED", "LED"), ("LCD LED SVA", "VA"), ("TN", "TN"), ("OLED", "OLED")],
    )
    def test_panel_types(self, raw, panel):
        assert ml(attr("DISPLAY_TYPE", raw))["pantalla_panel"] == panel

    @pytest.mark.parametrize("raw", ["FHD", "pantalla panorámica 16:9"])
    def test_a_panel_that_is_not_a_panel_type_is_left_empty(self, raw):
        assert "pantalla_panel" not in ml(attr("DISPLAY_TYPE", raw))

    @pytest.mark.parametrize(
        ("raw", "tipo"),
        [
            ("DDR4", "DDR4"),
            ("DDR4 SDRAM", "DDR4"),
            ("DD4", "DDR4"),
            ("DDDR4", "DDR4"),
            ("DRR4", "DDR4"),
            ("LPDDR5-5500", "LPDDR5"),
            ("LPDDR4X", "LPDDR4X"),
            ("DDR4-3200", "DDR4"),
        ],
    )
    def test_ram_types(self, raw, tipo):
        assert ml(attr("RAM_MEMORY_TYPE", raw))["ram_tipo"] == tipo

    @pytest.mark.parametrize("raw", ["SODIMM", "8gb"])
    def test_a_ram_type_that_is_not_one_is_left_empty(self, raw):
        assert "ram_tipo" not in ml(attr("RAM_MEMORY_TYPE", raw))

    @pytest.mark.parametrize(
        ("line", "canonical"),
        [
            ("Intel Core i7", "Core i7"),
            ("INTEL CORE I5", "Core i5"),
            ("i5 i5-1335U", "Core i5"),
            ("CORE 3", "Core 3"),
            ("Ultra 5", "Core Ultra 5"),
            ("Razen", None),
            ("Ryzen 7", "Ryzen 7"),
            ("Processor", None),
        ],
    )
    def test_processor_lines(self, line, canonical):
        assert ml(attr("PROCESSOR_LINE", line)).get("cpu_linea") == canonical

    @pytest.mark.parametrize(
        ("model", "canonical"),
        [
            ("7730u", "7730U"),
            ("7330U", "7330U"),
            ("i7-1255U", "1255U"),
            ("R7-260", "260"),
            ("R5 3400G", "3400G"),
            ("Ryzen 7 5700G", "5700G"),
            ("1165G7", "1165G7"),
            ("Athlon 3000G", "3000G"),
            ("i3", None),
        ],
    )
    def test_processor_models(self, model, canonical):
        assert ml(attr("PROCESSOR_MODEL", model)).get("cpu_modelo") == canonical

    def test_the_line_comes_from_the_model_when_the_line_attribute_is_missing(self):
        assert ml(attr("PROCESSOR_MODEL", "Ryzen 7 5700G"))["cpu_linea"] == "Ryzen 7"

    def test_os_name_and_edition(self):
        specs = ml(attr("OS_NAME", "Windows 11"), attr("OS_EDITION", "Home"))
        assert (specs["so_nombre"], specs["so_edicion"]) == ("Windows", "Home")

    def test_a_freedos_has_no_edition(self):
        specs = ml(attr("OS_NAME", "FreeDOS"), attr("OS_EDITION", "Sin S.O."))
        assert specs["so_nombre"] == "FreeDOS" and "so_edicion" not in specs

    @pytest.mark.parametrize(
        ("brand", "model", "expected"),
        [
            ("NVIDIA", "RTX 3050", "RTX 3050"),
            ("NVIDIA", "5070 8GB", "RTX 5070"),
            ("NVIDIA", "3050 Ti", "RTX 3050 Ti"),
            ("GeForce RTX™ 4050", None, "RTX 4050"),
            (None, "GTX 1650", "GTX 1650"),
        ],
    )
    def test_dedicated_gpus(self, brand, model, expected):
        specs = ml(attr("DEDICATED_GRAPHIC_CARD_BRAND", brand), attr("DEDICATED_GRAPHIC_CARD_MODEL", model))
        assert (specs["gpu_tipo"], specs["gpu_marca"], specs["gpu_modelo"]) == ("Dedicada", "NVIDIA", expected)

    def test_an_intel_brand_in_the_dedicated_attribute_is_not_a_dedicated_gpu(self):
        specs = ml(
            attr("DEDICATED_GRAPHIC_CARD_BRAND", "Intel UHD Graphics"), attr("INTEGRATED_GRAPHIC_CARD_BRAND", "intel")
        )
        assert (specs["gpu_tipo"], specs["gpu_marca"]) == ("Integrada", "Intel")

    @pytest.mark.parametrize(
        ("text", "brand", "model"),
        [
            ("AMD Radeon Graphics RX Vega 6 (integrada)", "AMD", "Radeon Vega 6"),
            ("Gráficos AMD Radeon 610M", "AMD", "Radeon 610M"),
            ("Intel Iris Xe Graphics G7 80EUs", "Intel", "Iris Xe"),
            ("Intel Graphics UHD 620", "Intel", "UHD Graphics 620"),
        ],
    )
    def test_integrated_gpus(self, text, brand, model):
        specs = ml(attr("GRAPHIC_CARD", text))
        assert (specs["gpu_tipo"], specs["gpu_marca"], specs["gpu_modelo"]) == ("Integrada", brand, model)

    def test_video_memory_alone_is_a_dedicated_gpu(self):
        # Real case, MLA1168328626 (item 280): only VIDEO_MEMORY, no GPU brand or model.
        specs = ml(attr("VIDEO_MEMORY", "6 GB"))
        assert (specs["gpu_tipo"], specs["gpu_vram_gb"]) == ("Dedicada", 6)
        assert "gpu_marca" not in specs and "gpu_modelo" not in specs

    def test_video_memory_is_kept_with_an_integrated_gpu_and_does_not_make_it_dedicated(self):
        # Real case, MLA1341354513 (item 395).
        specs = ml(attr("GRAPHIC_CARD", "Intel UHD Graphics Xe G4 48EUs"), attr("VIDEO_MEMORY", "4 GB"))
        assert (specs["gpu_tipo"], specs["gpu_vram_gb"]) == ("Integrada", 4)

    def test_video_memory_with_a_dedicated_gpu(self):
        specs = ml(attr("DEDICATED_GRAPHIC_CARD_MODEL", "RTX 3050"), attr("VIDEO_MEMORY", "4 GB"))
        assert (specs["gpu_tipo"], specs["gpu_vram_gb"]) == ("Dedicada", 4)

    @pytest.mark.parametrize("raw", ["0 KB", "7873270"])
    def test_unreadable_video_memory_does_not_make_a_gpu(self, raw):
        assert "gpu_tipo" not in ml(attr("VIDEO_MEMORY", raw))

    def test_pc_components(self):
        specs = ml(
            attr("COMPUTER_CASE_BRAND", "Kelyx"),
            attr("COMPUTER_CASE_MODEL", "GABINETE KIT MELODY MKG550-11"),
            attr("MOTHERBOARD_BRAND", "MSI"),
            attr("MOTHERBOARD_MODEL", "MOTHER MSI A520M-A PRO DDR4"),
            attr("COOLER_BRAND", "AMD"),
            attr("COOLER_MODEL", "Cooler Stock"),
            tipo=PC,
        )
        assert specs["gabinete_marca"] == "KELYX"
        assert specs["gabinete_modelo"] == "KIT MELODY MKG550-11"
        assert (specs["mother_marca"], specs["mother_modelo"]) == ("MSI", "A520M-A PRO DDR4")
        assert (specs["refrigeracion_tipo"], specs["refrigeracion_marca"], specs["refrigeracion_modelo"]) == (
            "Aire",
            "AMD",
            "STOCK",
        )

    def test_a_notebook_takes_no_pc_component_and_a_pc_no_screen(self):
        assert "mother_marca" not in ml(attr("MOTHERBOARD_BRAND", "MSI"))
        assert "pantalla_pulgadas" not in ml(attr("DISPLAY_SIZE", '23.8 "'), tipo=PC)


class TestErpName:
    def test_the_owner_example(self):
        specs = n.nombre_erp_specs('NB LENOVO V15 G5 IRL I7-13620H 16GB D5 1T SSD 15.6" FHD FDOS (7425)', NOTEBOOK)
        assert specs == {
            "cpu_marca": "Intel",
            "cpu_linea": "Core i7",
            "cpu_modelo": "13620H",
            "ram_gb": 16,
            "ram_tipo": "DDR5",
            "disco_gb": 1024,
            "disco_tipo": "SSD",
            "pantalla_pulgadas": Decimal("15.6"),
            "pantalla_resolucion": "1920x1080",
            "so_nombre": "FreeDOS",
        }

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            (
                'NB HP 255 G10 R3 7335U 8GB D5 512GB 15" W11H (2993)',
                {
                    "cpu_linea": "Ryzen 3",
                    "cpu_modelo": "7335U",
                    "so_nombre": "Windows",
                    "so_edicion": "Home",
                    "pantalla_pulgadas": Decimal("15"),
                },
            ),
            (
                'NB ASUS E1504FA 15.6" R5-40 8GB D5 512GB  W11H',
                {"cpu_linea": "Ryzen 5", "cpu_modelo": "40", "ram_gb": 8},
            ),
            (
                "NB LENOVO THINKBOOK 16 G8 I5 210H 8GB D5-5600 512GB M.2 W11P 1Y (3377-WP)",
                {
                    "cpu_linea": "Core i5",
                    "cpu_modelo": "210H",
                    "ram_tipo": "DDR5",
                    "disco_tipo": "SSD",
                    "so_edicion": "Pro",
                },
            ),
            (
                'NB LENOVO V15 G5 IRL I5-13420H32GB D5 512GB SSD 15.6" FHD FD (7432)',
                {"cpu_modelo": "13420H", "ram_gb": 32, "disco_gb": 512, "so_nombre": "FreeDOS"},
            ),
            (
                "NB HP VICTUS GAMING CG3N4LA R5-7535HS RTX3050 8GB D5 512GB 144HZ 15.6FHD W11H",
                {
                    "gpu_tipo": "Dedicada",
                    "gpu_marca": "NVIDIA",
                    "gpu_modelo": "RTX 3050",
                    "pantalla_hz": 144,
                    "pantalla_pulgadas": Decimal("15.6"),
                    "pantalla_resolucion": "1920x1080",
                },
            ),
            ('NB HP 250R G10 I5-120U 8GB 5600MHZ 512GB M2 15" W11H (0294-WH)', {"ram_gb": 8, "disco_gb": 512}),
            (
                "PC ARMADA GAMER RYZEN 7 5700G A520 32GB 480GB",
                {"cpu_marca": "AMD", "cpu_linea": "Ryzen 7", "cpu_modelo": "5700G", "ram_gb": 32, "disco_gb": 480},
            ),
            ("PC ARMADA ATHLON 3000G AM4 8GB 128GB SSD KIT W11H", {"cpu_linea": "Athlon", "cpu_modelo": "3000G"}),
        ],
    )
    def test_names(self, name, expected):
        specs = n.nombre_erp_specs(name, PC if name.startswith("PC") else NOTEBOOK)
        assert {k: specs.get(k) for k in expected} == expected

    @pytest.mark.parametrize(
        ("name", "inches"),
        [
            ('NB BANGHO MAX L5 R5 15" 8GB 480GB W11 HOME (6370)', Decimal("15")),
            ("NB LENOVO RYZEN 7 16GB 512SSD FDOS 15PUL", Decimal("15")),
        ],
    )
    def test_a_screen_size_or_a_capacity_after_the_cpu_line_is_not_the_cpu_model(self, name, inches):
        specs = n.nombre_erp_specs(name, NOTEBOOK)
        assert "cpu_modelo" not in specs
        assert specs["cpu_linea"] in ("Ryzen 5", "Ryzen 7")
        assert specs["pantalla_pulgadas"] == inches

    def test_a_number_without_inches_is_not_a_screen(self):
        assert "pantalla_pulgadas" not in n.nombre_erp_specs(
            "NB HP 14-EP0029LA I3-1215U 8GB D4 512GB 14 W11H", NOTEBOOK
        )

    def test_mhz_is_not_a_refresh_rate(self):
        assert "pantalla_hz" not in n.nombre_erp_specs("NB HP I5-120U 8GB 5600MHZ 512GB M2", NOTEBOOK)


class TestCombo:
    def test_pc_components_from_the_combo(self):
        specs = n.combo_specs(
            [
                n.Componente(48, "PC CPU AMD RYZEN 5 4600G 100-100000147BOX", "AMD", Decimal(1)),
                n.Componente(50, "MOTHER BIOSTAR AM4 B450M HP BOX M-ATX", "BIOSTAR", Decimal(1)),
                n.Componente(51, "MEMORIA DDR4 HIKSEMI 8GB 3200 MHZ SINGLE TRAY", "HIKSEMI", Decimal(2)),
                n.Componente(52, "DISCO SSD 480GB HIKSEMI WAVE S", "HIKSEMI", Decimal(1)),
                n.Componente(54, "GABINETE SENTEY K20 (1234)", "SENTEY", Decimal(1)),
                n.Componente(55, "FUENTE LNZ SX600-TS 600W", "LNZ", Decimal(1)),
                n.Componente(49, "COOLER ID-COOLING FROSTFLOW 240 LIQUID", "ID-COOLING", Decimal(1)),
                n.Componente(57, "KIT GMX-115 FUENTE 500W/TECLADO/MOUSE", "GMX", Decimal(1)),
            ]
        )
        assert specs == {
            "cpu_marca": "AMD",
            "cpu_linea": "Ryzen 5",
            "cpu_modelo": "4600G",
            "mother_marca": "BIOSTAR",
            "mother_modelo": "AM4 B450M HP BOX M-ATX",
            "ram_gb": 16,
            "ram_tipo": "DDR4",
            "disco_gb": 480,
            "disco_tipo": "SSD",
            "gabinete_marca": "SENTEY",
            "gabinete_modelo": "K20",
            "fuente_marca": "LNZ",
            "fuente_modelo": "SX600-TS",
            "fuente_watts": 600,
            "refrigeracion_tipo": "Líquida",
            "refrigeracion_marca": "ID-COOLING",
            "refrigeracion_modelo": "FROSTFLOW 240 LIQUID",
        }

    def test_a_dedicated_gpu_component(self):
        specs = n.combo_specs([n.Componente(53, "PLACA DE VIDEO MSI RTX 4060 VENTUS 8GB", "MSI", Decimal(1))])
        assert (specs["gpu_tipo"], specs["gpu_marca"], specs["gpu_modelo"], specs["gpu_vram_gb"]) == (
            "Dedicada",
            "NVIDIA",
            "RTX 4060",
            8,
        )


class TestWinner:
    def test_the_most_complete_publication_wins_then_the_most_recent_then_the_lowest_mla(self):
        from datetime import datetime

        old, new = datetime(2026, 1, 1), datetime(2026, 6, 1)
        candidatos = [
            n.CandidatoMl("MLA3", new, {"ram_gb": 8}),
            n.CandidatoMl("MLA2", old, {"ram_gb": 8, "disco_gb": 512}),
            n.CandidatoMl("MLA1", new, {"ram_gb": 16, "disco_gb": 256}),
            n.CandidatoMl("MLA0", new, {"ram_gb": 16, "disco_gb": 256}),
        ]
        assert n.ganador(candidatos).mla == "MLA0"
        assert n.ganador(candidatos[:3]).mla == "MLA1"
        assert n.ganador([]) is None
