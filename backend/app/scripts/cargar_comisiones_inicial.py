import sys

sys.path.append("/var/www/html/pricing-app/backend")

from app.core.database import SessionLocal
from app.models.comision_config import GrupoComision, SubcategoriaGrupo, ComisionListaGrupo


def cargar_datos():
    db = SessionLocal()

    try:
        print("Limpiando datos existentes...")
        db.query(ComisionListaGrupo).delete()
        db.query(SubcategoriaGrupo).delete()
        db.query(GrupoComision).delete()

        print("Creando grupos...")
        for i in range(1, 9):
            db.add(GrupoComision(id=i, nombre=f"Grupo {i}"))

        print("Asignando subcategorías a grupos...")
        subcat_to_group = {
            3821: 2,
            3820: 2,
            3882: 2,
            3819: 2,
            3818: 2,
            3885: 2,
            3879: 2,
            3869: 3,
            3870: 3,
            3919: 3,
            3915: 3,
            3841: 3,
            3858: 3,
            3957: 3,
            3907: 3,
            3922: 4,
            3860: 4,
            3861: 4,
            3902: 5,
            3866: 5,
            3856: 5,
            3893: 5,
            3886: 5,
            3887: 5,
            3924: 5,
            3921: 5,
            3920: 5,
            3912: 5,
            3913: 5,
            3878: 5,
            3875: 5,
            3876: 5,
            3880: 5,
            3894: 5,
            3853: 5,
            3931: 5,
            3926: 5,
            3891: 7,
            3843: 7,
            3918: 7,
            3849: 7,
            3888: 8,
            3852: 8,
            3899: 8,
            3838: 8,
            3895: 8,
            3896: 8,
        }

        for subcat_id, grupo_id in subcat_to_group.items():
            db.add(SubcategoriaGrupo(subcat_id=subcat_id, grupo_id=grupo_id))

        print("Cargando comisiones por lista-grupo...")
        # pricelist4: [4, 5, 17, 14, 13, 23, 9, 10, 11, 15, 16, 12, 18, 19, 20, 21, 22, 6]
        pricelists = [4, 5, 17, 14, 13, 23, 9, 10, 11, 15, 16, 12, 18, 19, 20, 21, 22, 6]

        # Comisiones por grupo (cada lista tiene 18 valores, uno por pricelist)
        comisiones_por_grupo = {
            1: [
                15.5,
                None,
                27.3,
                35,
                42.9,
                50.5,
                None,
                4.83,
                13.73,
                19.73,
                24.73,
                15.5,
                27.3,
                35,
                42.9,
                50.5,
                30.33,
                29.5,
            ],
            2: [
                12.15,
                None,
                23.95,
                31.65,
                39.55,
                47.15,
                None,
                4.83,
                13.73,
                19.73,
                24.73,
                12.15,
                23.95,
                31.65,
                39.55,
                47.15,
                30.33,
                26.15,
            ],
            3: [
                12.65,
                None,
                24.45,
                32.15,
                40.05,
                47.65,
                None,
                4.83,
                13.73,
                19.73,
                24.73,
                12.65,
                24.45,
                32.15,
                40.05,
                47.65,
                30.33,
                26.65,
            ],
            4: [
                13.65,
                None,
                25.45,
                33.15,
                41.05,
                48.65,
                None,
                4.83,
                13.73,
                19.73,
                24.73,
                13.65,
                25.45,
                33.15,
                41.05,
                48.65,
                30.33,
                27.65,
            ],
            5: [14, None, 25.8, 33.5, 41.4, 49, None, 4.83, 13.73, 19.73, 24.73, 14, 25.8, 33.5, 41.4, 49, 30.33, 28],
            6: [
                14.5,
                None,
                26.3,
                34,
                41.9,
                49.5,
                None,
                4.83,
                13.73,
                19.73,
                24.73,
                14.5,
                26.3,
                34,
                41.9,
                49.5,
                30.33,
                28.5,
            ],
            7: [15, None, 26.8, 34.5, 42.4, 50, None, 4.83, 13.73, 19.73, 24.73, 15, 26.8, 34.5, 42.4, 50, 30.33, 29],
            8: [16, None, 27.8, 35.5, 43.4, 51, None, 4.83, 13.73, 19.73, 24.73, 16, 27.8, 35.5, 43.4, 51, 30.33, 30],
        }

        for grupo_id, comisiones in comisiones_por_grupo.items():
            for i, pricelist_id in enumerate(pricelists):
                comision = comisiones[i]
                if comision is not None:  # Saltar None
                    db.add(
                        ComisionListaGrupo(pricelist_id=pricelist_id, grupo_id=grupo_id, comision_porcentaje=comision)
                    )

        db.commit()
        print("✅ Datos cargados exitosamente")

    except Exception as e:
        db.rollback()
        print(f"❌ Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    cargar_datos()
