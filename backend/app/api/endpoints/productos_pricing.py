from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, func, and_, select, tuple_
from typing import Optional, List
from app.core.database import get_db
from app.models.producto import ProductoERP, ProductoPricing
from app.models.usuario import Usuario
from pydantic import BaseModel, ConfigDict, Field
from datetime import UTC, datetime, date
from app.models.auditoria_precio import AuditoriaPrecio
from app.api.deps import get_current_user
from fastapi.responses import Response
import logging

from app.api.endpoints.productos_shared import (  # noqa: F401
    PrecioUpdate,
    RebateUpdate,
    ExportRebateRequest,
    CalculoWebMasivoRequest,
    CalculoPVPMasivoRequest,
    RecalcularCuotasMasivoRequest,
    ConfigCuotasRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.patch("/productos/{producto_id}/precio")
def actualizar_precio(
    producto_id: int,
    datos: PrecioUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Actualiza precio de un producto y registra en auditoría"""
    from app.services.permisos_service import verificar_permiso

    if not verificar_permiso(db, current_user, "productos.editar_precios"):
        raise HTTPException(status_code=403, detail="No tienes permiso para editar precios")

    producto = db.query(ProductoPricing).filter(ProductoPricing.id == producto_id).first()
    if not producto:
        raise HTTPException(404, "Producto no encontrado")

    # Guardar valores anteriores para auditoría
    precio_ant = producto.precio_lista_final
    contado_ant = producto.precio_contado_final

    # Actualizar precios
    if datos.precio_lista_final is not None:
        producto.precio_lista_final = datos.precio_lista_final
    if datos.precio_contado_final is not None:
        producto.precio_contado_final = datos.precio_contado_final

    # Registrar en auditoría SOLO si cambió algún precio
    if (datos.precio_lista_final is not None and precio_ant != datos.precio_lista_final) or (
        datos.precio_contado_final is not None and contado_ant != datos.precio_contado_final
    ):
        auditoria = AuditoriaPrecio(
            producto_id=producto_id,
            usuario_id=current_user.id,
            precio_anterior=precio_ant,
            precio_contado_anterior=contado_ant,
            precio_nuevo=producto.precio_lista_final,
            precio_contado_nuevo=producto.precio_contado_final,
            comentario=datos.comentario if hasattr(datos, "comentario") else None,
        )
        db.add(auditoria)

    db.commit()
    db.refresh(producto)

    return producto


@router.patch("/productos/{item_id}/rebate")
def actualizar_rebate(
    item_id: int, datos: RebateUpdate, db: Session = Depends(get_db), current_user=Depends(get_current_user)
):
    """Actualiza configuración de rebate de un producto"""
    from app.services.permisos_service import verificar_permiso

    if not verificar_permiso(db, current_user, "productos.toggle_rebate"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar rebate")
    from app.services.auditoria_service import registrar_auditoria
    from app.models.auditoria import TipoAccion

    pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).first()

    # Guardar valores anteriores
    valores_anteriores = {
        "participa_rebate": pricing.participa_rebate if pricing else False,
        "porcentaje_rebate": float(pricing.porcentaje_rebate)
        if pricing and pricing.porcentaje_rebate is not None
        else None,
    }

    if not pricing:
        pricing = ProductoPricing(
            item_id=item_id,
            participa_rebate=datos.participa_rebate,
            porcentaje_rebate=datos.porcentaje_rebate,
            usuario_id=current_user.id,
        )
        db.add(pricing)
    else:
        pricing.participa_rebate = datos.participa_rebate
        pricing.porcentaje_rebate = datos.porcentaje_rebate
        pricing.fecha_modificacion = datetime.now(UTC)

    db.commit()
    db.refresh(pricing)

    # Determinar tipo de acción
    if datos.participa_rebate and not valores_anteriores["participa_rebate"]:
        tipo_accion = TipoAccion.ACTIVAR_REBATE
    elif not datos.participa_rebate and valores_anteriores["participa_rebate"]:
        tipo_accion = TipoAccion.DESACTIVAR_REBATE
    else:
        tipo_accion = TipoAccion.MODIFICAR_PORCENTAJE_REBATE

    # Registrar auditoría
    registrar_auditoria(
        db=db,
        usuario_id=current_user.id,
        tipo_accion=tipo_accion,
        item_id=item_id,
        valores_anteriores=valores_anteriores,
        valores_nuevos={"participa_rebate": datos.participa_rebate, "porcentaje_rebate": datos.porcentaje_rebate},
    )

    return {
        "item_id": item_id,
        "participa_rebate": datos.participa_rebate,
        "porcentaje_rebate": datos.porcentaje_rebate,
    }


@router.patch("/productos/{item_id}/web-transferencia")
def actualizar_web_transferencia(
    item_id: int,
    participa: bool,
    porcentaje_markup: float = 6.0,
    preservar_porcentaje: bool = False,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Activa/desactiva web transferencia y calcula precio"""
    from app.services.permisos_service import verificar_permiso

    if not verificar_permiso(db, current_user, "productos.toggle_web_transferencia"):
        raise HTTPException(status_code=403, detail="No tienes permiso para gestionar web transferencia")
    from app.services.pricing_calculator import (
        calcular_precio_web_transferencia,
        obtener_tipo_cambio_actual,
        convertir_a_pesos,
    )
    from app.services.auditoria_service import registrar_auditoria
    from app.models.auditoria import TipoAccion

    producto_erp = db.query(ProductoERP).filter(ProductoERP.item_id == item_id).first()
    if not producto_erp:
        raise HTTPException(404, "Producto no encontrado")

    pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).first()

    # Guardar valores anteriores
    valores_anteriores = {
        "participa_web_transferencia": pricing.participa_web_transferencia if pricing else False,
        "porcentaje_markup_web": float(pricing.porcentaje_markup_web)
        if pricing and pricing.porcentaje_markup_web
        else None,
        "precio_web_transferencia": float(pricing.precio_web_transferencia)
        if pricing and pricing.precio_web_transferencia
        else None,
    }

    if not pricing:
        pricing = ProductoPricing(
            item_id=item_id,
            participa_web_transferencia=participa,
            porcentaje_markup_web=porcentaje_markup,
            preservar_porcentaje_web=preservar_porcentaje,
            usuario_id=current_user.id,
        )
        db.add(pricing)
    else:
        pricing.participa_web_transferencia = participa
        pricing.porcentaje_markup_web = porcentaje_markup
        pricing.preservar_porcentaje_web = preservar_porcentaje
        pricing.fecha_modificacion = datetime.now(UTC)

    precio_web = None
    markup_web_real = None

    if participa:
        tipo_cambio = None
        if producto_erp.moneda_costo == "USD":
            tipo_cambio = obtener_tipo_cambio_actual(db, "USD")

        costo_ars = convertir_a_pesos(producto_erp.costo, producto_erp.moneda_costo, tipo_cambio)

        if pricing.markup_calculado is not None and pricing.precio_lista_ml is not None:
            markup_clasica = pricing.markup_calculado / 100
        else:
            markup_clasica = 0

        markup_objetivo = markup_clasica + (porcentaje_markup / 100)

        resultado = calcular_precio_web_transferencia(
            costo_ars=costo_ars, iva=producto_erp.iva, markup_objetivo=markup_objetivo
        )

        precio_web = resultado["precio"]
        markup_web_real = resultado["markup_real"]
        pricing.precio_web_transferencia = precio_web
        pricing.markup_web_real = markup_web_real
    else:
        pricing.precio_web_transferencia = None
        pricing.markup_web_real = None

    db.commit()
    db.refresh(pricing)

    # Determinar tipo de acción
    if participa and not valores_anteriores["participa_web_transferencia"]:
        tipo_accion = TipoAccion.ACTIVAR_WEB_TRANSFERENCIA
    elif not participa and valores_anteriores["participa_web_transferencia"]:
        tipo_accion = TipoAccion.DESACTIVAR_WEB_TRANSFERENCIA
    else:
        tipo_accion = TipoAccion.MODIFICAR_PRECIO_WEB

    # Registrar auditoría
    registrar_auditoria(
        db=db,
        usuario_id=current_user.id,
        tipo_accion=tipo_accion,
        item_id=item_id,
        valores_anteriores=valores_anteriores,
        valores_nuevos={
            "participa_web_transferencia": participa,
            "porcentaje_markup_web": porcentaje_markup,
            "precio_web_transferencia": precio_web,
            "markup_web_real": markup_web_real,
        },
    )

    return {
        "item_id": item_id,
        "participa_web_transferencia": participa,
        "porcentaje_markup_web": porcentaje_markup,
        "precio_web_transferencia": precio_web,
        "markup_web_real": markup_web_real if precio_web else None,
    }


@router.post("/productos/calcular-web-masivo")
def calcular_web_masivo(
    request: CalculoWebMasivoRequest, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Calcula precio web transferencia masivamente"""
    from app.services.pricing_calculator import (
        calcular_precio_web_transferencia,
        obtener_tipo_cambio_actual,
        convertir_a_pesos,
    )

    # Obtener productos base
    query = db.query(ProductoERP, ProductoPricing).outerjoin(
        ProductoPricing, ProductoERP.item_id == ProductoPricing.item_id
    )

    # Aplicar filtros si existen
    if request.filtros:
        if request.filtros.get("search"):
            search_term = f"%{request.filtros['search']}%"
            query = query.filter((ProductoERP.descripcion.ilike(search_term)) | (ProductoERP.codigo.ilike(search_term)))

        if request.filtros.get("con_stock"):
            query = query.filter(ProductoERP.stock > 0)

        if request.filtros.get("con_precio"):
            query = query.filter(ProductoPricing.precio_lista_ml.isnot(None))

        if request.filtros.get("marcas"):
            marcas_list = request.filtros["marcas"].split(",")
            query = query.filter(ProductoERP.marca.in_(marcas_list))

        if request.filtros.get("subcategorias"):
            subcats_list = [int(s) for s in request.filtros["subcategorias"].split(",")]
            query = query.filter(ProductoERP.subcategoria_id.in_(subcats_list))

        # Filtros avanzados
        if request.filtros.get("con_rebate") is not None:
            if request.filtros["con_rebate"]:
                query = query.filter(ProductoPricing.participa_rebate == True)
            else:
                query = query.filter(
                    (ProductoPricing.participa_rebate == False) | (ProductoPricing.participa_rebate.is_(None))
                )

        if request.filtros.get("con_oferta") is not None:
            if request.filtros["con_oferta"]:
                query = query.filter(ProductoPricing.participa_oferta == True)
            else:
                query = query.filter(
                    (ProductoPricing.participa_oferta == False) | (ProductoPricing.participa_oferta.is_(None))
                )

        if request.filtros.get("con_web_transf") is not None:
            if request.filtros["con_web_transf"]:
                query = query.filter(ProductoPricing.participa_web_transferencia == True)
            else:
                query = query.filter(
                    (ProductoPricing.participa_web_transferencia == False)
                    | (ProductoPricing.participa_web_transferencia.is_(None))
                )

        # Filtros de Tienda Nube
        if request.filtros.get("tiendanube_con_descuento"):
            query = query.filter(
                ProductoPricing.descuento_tiendanube.isnot(None), ProductoPricing.descuento_tiendanube > 0
            )

        if request.filtros.get("tiendanube_sin_descuento"):
            query = query.filter(
                (ProductoPricing.descuento_tiendanube.is_(None)) | (ProductoPricing.descuento_tiendanube == 0)
            )

        if request.filtros.get("tiendanube_no_publicado"):
            # Productos con stock pero NO en Tienda Nube
            from app.models.tienda_nube_producto import TiendaNubeProducto
            from sqlalchemy.sql import exists

            subquery = exists().where(
                and_(TiendaNubeProducto.item_id == ProductoERP.item_id, TiendaNubeProducto.activo == True)
            )
            query = query.filter(and_(ProductoERP.stock > 0, ~subquery))

        # Filtros de Markup
        if request.filtros.get("markup_clasica_positivo") is not None:
            if request.filtros["markup_clasica_positivo"]:
                query = query.filter(ProductoPricing.markup_calculado > 0)
            else:
                query = query.filter(
                    (ProductoPricing.markup_calculado <= 0) | (ProductoPricing.markup_calculado.is_(None))
                )

        if request.filtros.get("markup_rebate_positivo") is not None:
            if request.filtros["markup_rebate_positivo"]:
                query = query.filter(ProductoPricing.markup_rebate_real > 0)
            else:
                query = query.filter(
                    (ProductoPricing.markup_rebate_real <= 0) | (ProductoPricing.markup_rebate_real.is_(None))
                )

        if request.filtros.get("markup_oferta_positivo") is not None:
            if request.filtros["markup_oferta_positivo"]:
                query = query.filter(ProductoPricing.markup_oferta_real > 0)
            else:
                query = query.filter(
                    (ProductoPricing.markup_oferta_real <= 0) | (ProductoPricing.markup_oferta_real.is_(None))
                )

        if request.filtros.get("markup_web_transf_positivo") is not None:
            if request.filtros["markup_web_transf_positivo"]:
                query = query.filter(ProductoPricing.markup_web_real > 0)
            else:
                query = query.filter(
                    (ProductoPricing.markup_web_real <= 0) | (ProductoPricing.markup_web_real.is_(None))
                )

        # Filtro de Out of Cards
        if request.filtros.get("out_of_cards") is not None:
            if request.filtros["out_of_cards"]:
                query = query.filter(ProductoPricing.out_of_cards == True)
            else:
                query = query.filter((ProductoPricing.out_of_cards == False) | (ProductoPricing.out_of_cards.is_(None)))

        # Filtro de colores
        if request.filtros.get("colores"):
            colores_list = request.filtros["colores"].split(",")
            if "sin_color" in colores_list:
                colores_con_valor = [c for c in colores_list if c != "sin_color"]
                if colores_con_valor:
                    query = query.filter(
                        or_(
                            ProductoPricing.color_marcado.in_(colores_con_valor),
                            ProductoPricing.color_marcado.is_(None),
                        )
                    )
                else:
                    query = query.filter(ProductoPricing.color_marcado.is_(None))
            else:
                query = query.filter(ProductoPricing.color_marcado.in_(colores_list))

        # Filtro de PMs - filtra por pares (marca, categoria)
        if request.filtros.get("pms"):
            from app.models.marca_pm import MarcaPM

            pm_ids = [int(pm.strip()) for pm in request.filtros["pms"].split(",")]
            pares_pm = db.query(MarcaPM.marca, MarcaPM.categoria).filter(MarcaPM.usuario_id.in_(pm_ids)).all()
            if pares_pm:
                pares_upper = [(m.upper(), c.upper()) for m, c in pares_pm]
                query = query.filter(
                    tuple_(func.upper(ProductoERP.marca), func.upper(ProductoERP.categoria)).in_(pares_upper)
                )
            else:
                query = query.filter(ProductoERP.item_id == -1)

        # Filtro de MLA
        if request.filtros.get("con_mla") is not None:
            from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado
            from app.models.item_sin_mla_banlist import ItemSinMLABanlist

            if request.filtros["con_mla"]:
                # Con MLA: tienen al menos una publicación (sin importar estado)
                items_con_mla_subquery = (
                    db.query(MercadoLibreItemPublicado.item_id)
                    .filter(MercadoLibreItemPublicado.mlp_id.isnot(None))
                    .distinct()
                    .subquery()
                )
                query = query.filter(ProductoERP.item_id.in_(select(items_con_mla_subquery.c.item_id)))
            else:
                # Sin MLA: no tienen ninguna publicación (sin importar estado, excluye banlist)
                items_con_mla_subquery = (
                    db.query(MercadoLibreItemPublicado.item_id)
                    .filter(MercadoLibreItemPublicado.mlp_id.isnot(None))
                    .distinct()
                    .subquery()
                )

                items_en_banlist_subquery = db.query(ItemSinMLABanlist.item_id).subquery()

                query = query.filter(
                    ~ProductoERP.item_id.in_(select(items_con_mla_subquery.c.item_id)),
                    ~ProductoERP.item_id.in_(select(items_en_banlist_subquery.c.item_id)),
                )

        # Filtro de estado de publicaciones MLA
        if request.filtros.get("estado_mla"):
            from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado

            if request.filtros["estado_mla"] == "activa":
                # Tienen al menos una publicación activa
                items_activos_subquery = (
                    db.query(MercadoLibreItemPublicado.item_id)
                    .filter(
                        MercadoLibreItemPublicado.mlp_id.isnot(None),
                        or_(
                            MercadoLibreItemPublicado.optval_statusId == 2,
                            MercadoLibreItemPublicado.optval_statusId.is_(None),
                        ),
                    )
                    .distinct()
                    .subquery()
                )

                query = query.filter(ProductoERP.item_id.in_(select(items_activos_subquery.c.item_id)))

            elif request.filtros["estado_mla"] == "pausada":
                # Tienen publicaciones pero ninguna activa
                items_con_publis = (
                    db.query(MercadoLibreItemPublicado.item_id)
                    .filter(MercadoLibreItemPublicado.mlp_id.isnot(None))
                    .distinct()
                    .subquery()
                )

                items_activos = (
                    db.query(MercadoLibreItemPublicado.item_id)
                    .filter(
                        MercadoLibreItemPublicado.mlp_id.isnot(None),
                        or_(
                            MercadoLibreItemPublicado.optval_statusId == 2,
                            MercadoLibreItemPublicado.optval_statusId.is_(None),
                        ),
                    )
                    .distinct()
                    .subquery()
                )

                query = query.filter(
                    ProductoERP.item_id.in_(select(items_con_publis.c.item_id)),
                    ~ProductoERP.item_id.in_(select(items_activos.c.item_id)),
                )

        # Filtro de productos nuevos
        if request.filtros.get("nuevos_ultimos_7_dias"):
            from datetime import timedelta, timezone

            fecha_limite = datetime.now(timezone.utc) - timedelta(days=7)
            query = query.filter(ProductoERP.fecha_sync >= fecha_limite)

        # Filtro de Tienda Oficial
        if request.filtros.get("tienda_oficial"):
            from app.models.mercadolibre_item_publicado import MercadoLibreItemPublicado

            store_id = int(request.filtros.get("tienda_oficial"))
            item_ids_tienda = (
                db.query(MercadoLibreItemPublicado.item_id)
                .filter(MercadoLibreItemPublicado.mlp_official_store_id == store_id)
                .distinct()
            )
            query = query.filter(ProductoERP.item_id.in_(item_ids_tienda))

    productos = query.all()

    procesados = 0

    for producto_erp, producto_pricing in productos:
        # Si el producto tiene preservar_porcentaje_web=True, saltar
        if producto_pricing and producto_pricing.preservar_porcentaje_web:
            continue

        # Determinar markup a usar
        if producto_pricing and producto_pricing.precio_lista_ml:
            # Tiene precio: sumar porcentaje
            markup_base = (producto_pricing.markup_calculado or 0) / 100
            porcentaje_adicional = request.porcentaje_con_precio
        else:
            # No tiene precio: usar porcentaje base
            markup_base = 0
            porcentaje_adicional = request.porcentaje_sin_precio

        markup_objetivo = markup_base + (porcentaje_adicional / 100)

        # Calcular precio
        tipo_cambio = None
        if producto_erp.moneda_costo == "USD":
            tipo_cambio = obtener_tipo_cambio_actual(db, "USD")

        costo_ars = convertir_a_pesos(producto_erp.costo, producto_erp.moneda_costo, tipo_cambio)

        resultado = calcular_precio_web_transferencia(
            costo_ars=costo_ars, iva=producto_erp.iva, markup_objetivo=markup_objetivo
        )

        # Crear o actualizar pricing
        if not producto_pricing:
            producto_pricing = ProductoPricing(item_id=producto_erp.item_id, usuario_id=current_user.id)
            db.add(producto_pricing)

        producto_pricing.participa_web_transferencia = True
        producto_pricing.porcentaje_markup_web = porcentaje_adicional
        producto_pricing.precio_web_transferencia = resultado["precio"]
        producto_pricing.markup_web_real = resultado["markup_real"]
        producto_pricing.fecha_modificacion = datetime.now(UTC)

        procesados += 1

    db.commit()

    # Registrar auditoría masiva
    from app.services.auditoria_service import registrar_auditoria
    from app.models.auditoria import TipoAccion

    registrar_auditoria(
        db=db,
        usuario_id=current_user.id,
        tipo_accion=TipoAccion.MODIFICACION_MASIVA,
        es_masivo=True,
        productos_afectados=procesados,
        valores_nuevos={
            "accion": "calcular_web_masivo",
            "porcentaje_con_precio": request.porcentaje_con_precio,
            "porcentaje_sin_precio": request.porcentaje_sin_precio,
            "filtros": request.filtros,
        },
        comentario="Cálculo masivo de precios web transferencia",
    )

    return {
        "procesados": procesados,
        "porcentaje_con_precio": request.porcentaje_con_precio,
        "porcentaje_sin_precio": request.porcentaje_sin_precio,
    }


@router.post("/productos/calcular-pvp-masivo")
def calcular_pvp_masivo(
    request: CalculoPVPMasivoRequest, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Calcula precios PVP masivamente (clásica + cuotas con markup convergente)"""
    from app.services.pricing_calculator import calcular_precio_producto, obtener_tipo_cambio_actual

    # Obtener productos base
    query = db.query(ProductoERP, ProductoPricing).outerjoin(
        ProductoPricing, ProductoERP.item_id == ProductoPricing.item_id
    )

    # Aplicar filtros si existen (misma lógica que web masivo)
    if request.filtros:
        if request.filtros.get("search"):
            search_term = f"%{request.filtros['search']}%"
            query = query.filter((ProductoERP.descripcion.ilike(search_term)) | (ProductoERP.codigo.ilike(search_term)))

        if request.filtros.get("con_stock"):
            query = query.filter(ProductoERP.stock > 0)

        if request.filtros.get("con_precio"):
            query = query.filter(ProductoPricing.precio_lista_ml.isnot(None))

        if request.filtros.get("marcas"):
            marcas_list = request.filtros["marcas"].split(",")
            query = query.filter(ProductoERP.marca.in_(marcas_list))

        if request.filtros.get("subcategorias"):
            subcats_list = [int(s) for s in request.filtros["subcategorias"].split(",")]
            query = query.filter(ProductoERP.subcategoria_id.in_(subcats_list))

        # Filtros avanzados (reutilizar lógica de web masivo)
        if request.filtros.get("con_rebate") is not None:
            if request.filtros["con_rebate"]:
                query = query.filter(ProductoPricing.participa_rebate == True)
            else:
                query = query.filter(
                    (ProductoPricing.participa_rebate == False) | (ProductoPricing.participa_rebate.is_(None))
                )

        if request.filtros.get("con_oferta") is not None:
            if request.filtros["con_oferta"]:
                query = query.filter(ProductoPricing.participa_oferta == True)
            else:
                query = query.filter(
                    (ProductoPricing.participa_oferta == False) | (ProductoPricing.participa_oferta.is_(None))
                )

        if request.filtros.get("con_web_transf") is not None:
            if request.filtros["con_web_transf"]:
                query = query.filter(ProductoPricing.participa_web_transferencia == True)
            else:
                query = query.filter(
                    (ProductoPricing.participa_web_transferencia == False)
                    | (ProductoPricing.participa_web_transferencia.is_(None))
                )

        if request.filtros.get("out_of_cards") is not None:
            if request.filtros["out_of_cards"]:
                query = query.filter(ProductoPricing.out_of_cards == True)
            else:
                query = query.filter((ProductoPricing.out_of_cards == False) | (ProductoPricing.out_of_cards.is_(None)))

        if request.filtros.get("colores"):
            colores_list = request.filtros["colores"].split(",")
            if "sin_color" in colores_list:
                colores_con_valor = [c for c in colores_list if c != "sin_color"]
                if colores_con_valor:
                    query = query.filter(
                        or_(
                            ProductoPricing.color_marcado.in_(colores_con_valor),
                            ProductoPricing.color_marcado.is_(None),
                        )
                    )
                else:
                    query = query.filter(ProductoPricing.color_marcado.is_(None))
            else:
                query = query.filter(ProductoPricing.color_marcado.in_(colores_list))

        if request.filtros.get("pms"):
            from app.models.marca_pm import MarcaPM

            pm_ids = [int(pm.strip()) for pm in request.filtros["pms"].split(",")]
            pares_pm = db.query(MarcaPM.marca, MarcaPM.categoria).filter(MarcaPM.usuario_id.in_(pm_ids)).all()
            if pares_pm:
                pares_upper = [(m.upper(), c.upper()) for m, c in pares_pm]
                query = query.filter(
                    tuple_(func.upper(ProductoERP.marca), func.upper(ProductoERP.categoria)).in_(pares_upper)
                )
            else:
                query = query.filter(ProductoERP.item_id == -1)

        # Filtros de markup
        if request.filtros.get("markup_clasica_positivo") is not None:
            if request.filtros["markup_clasica_positivo"]:
                query = query.filter(ProductoPricing.markup_calculado > 0)
            else:
                query = query.filter(
                    (ProductoPricing.markup_calculado <= 0) | (ProductoPricing.markup_calculado.is_(None))
                )

    productos = query.all()

    procesados = 0
    tipo_cambio_cache = {}

    for producto_erp, producto_pricing in productos:
        try:
            # Obtener tipo de cambio si es necesario
            tipo_cambio = None
            if producto_erp.moneda_costo == "USD":
                if "USD" not in tipo_cambio_cache:
                    tipo_cambio_cache["USD"] = obtener_tipo_cambio_actual(db, "USD")
                tipo_cambio = tipo_cambio_cache["USD"]
                if not tipo_cambio:
                    continue  # Saltar este producto si no hay tipo de cambio

            # Crear pricing si no existe
            if not producto_pricing:
                producto_pricing = ProductoPricing(item_id=producto_erp.item_id, usuario_id=current_user.id)
                db.add(producto_pricing)

            # Calcular PVP CLÁSICA (pricelist_id=12)
            resultado_clasica = calcular_precio_producto(
                db=db,
                costo=producto_erp.costo,
                moneda_costo=producto_erp.moneda_costo,
                iva=producto_erp.iva,
                envio=producto_erp.envio or 0,
                subcategoria_id=producto_erp.subcategoria_id,
                pricelist_id=12,  # 54-Lista ML PVP
                markup_objetivo=request.markup_pvp_clasica,
                tipo_cambio=tipo_cambio,
                adicional_markup=0,  # Sin adicional para clásica
            )

            if "error" not in resultado_clasica:
                producto_pricing.precio_pvp = resultado_clasica["precio"]
                producto_pricing.markup_pvp = resultado_clasica["markup_real"]

            # Calcular PVP CUOTAS (usa markup de clásica + adicional separado)
            # Igual que en /precios/set-rapido

            # 3 cuotas (pricelist_id=18)
            resultado_3 = calcular_precio_producto(
                db=db,
                costo=producto_erp.costo,
                moneda_costo=producto_erp.moneda_costo,
                iva=producto_erp.iva,
                envio=producto_erp.envio or 0,
                subcategoria_id=producto_erp.subcategoria_id,
                pricelist_id=18,  # 55-Lista ML PVP 3C
                markup_objetivo=request.markup_pvp_clasica,  # Mismo que clásica
                tipo_cambio=tipo_cambio,
                adicional_markup=request.adicional_cuotas,  # El adicional va acá
            )

            if "error" not in resultado_3:
                producto_pricing.precio_pvp_3_cuotas = resultado_3["precio"]
                producto_pricing.markup_pvp_3_cuotas = resultado_3["markup_real"]

            # 6 cuotas (pricelist_id=19)
            resultado_6 = calcular_precio_producto(
                db=db,
                costo=producto_erp.costo,
                moneda_costo=producto_erp.moneda_costo,
                iva=producto_erp.iva,
                envio=producto_erp.envio or 0,
                subcategoria_id=producto_erp.subcategoria_id,
                pricelist_id=19,  # 56-Lista ML PVP 6C
                markup_objetivo=request.markup_pvp_clasica,
                tipo_cambio=tipo_cambio,
                adicional_markup=request.adicional_cuotas,
            )

            if "error" not in resultado_6:
                producto_pricing.precio_pvp_6_cuotas = resultado_6["precio"]
                producto_pricing.markup_pvp_6_cuotas = resultado_6["markup_real"]

            # 9 cuotas (pricelist_id=20)
            resultado_9 = calcular_precio_producto(
                db=db,
                costo=producto_erp.costo,
                moneda_costo=producto_erp.moneda_costo,
                iva=producto_erp.iva,
                envio=producto_erp.envio or 0,
                subcategoria_id=producto_erp.subcategoria_id,
                pricelist_id=20,  # 57-Lista ML PVP 9C
                markup_objetivo=request.markup_pvp_clasica,
                tipo_cambio=tipo_cambio,
                adicional_markup=request.adicional_cuotas,
            )

            if "error" not in resultado_9:
                producto_pricing.precio_pvp_9_cuotas = resultado_9["precio"]
                producto_pricing.markup_pvp_9_cuotas = resultado_9["markup_real"]

            # 12 cuotas (pricelist_id=21)
            resultado_12 = calcular_precio_producto(
                db=db,
                costo=producto_erp.costo,
                moneda_costo=producto_erp.moneda_costo,
                iva=producto_erp.iva,
                envio=producto_erp.envio or 0,
                subcategoria_id=producto_erp.subcategoria_id,
                pricelist_id=21,  # 58-Lista ML PVP 12C
                markup_objetivo=request.markup_pvp_clasica,
                tipo_cambio=tipo_cambio,
                adicional_markup=request.adicional_cuotas,
            )

            if "error" not in resultado_12:
                producto_pricing.precio_pvp_12_cuotas = resultado_12["precio"]
                producto_pricing.markup_pvp_12_cuotas = resultado_12["markup_real"]

            producto_pricing.fecha_modificacion = datetime.now(UTC)
            procesados += 1

        except Exception as e:
            logger.error("Error procesando producto %s: %s", producto_erp.item_id, e, exc_info=True)
            continue

    db.commit()

    # Registrar auditoría masiva
    from app.services.auditoria_service import registrar_auditoria
    from app.models.auditoria import TipoAccion

    registrar_auditoria(
        db=db,
        usuario_id=current_user.id,
        tipo_accion=TipoAccion.MODIFICACION_MASIVA,
        es_masivo=True,
        productos_afectados=procesados,
        valores_nuevos={
            "accion": "calcular_pvp_masivo",
            "markup_pvp_clasica": request.markup_pvp_clasica,
            "adicional_cuotas": request.adicional_cuotas,
            "filtros": request.filtros,
        },
        comentario="Cálculo masivo de precios PVP",
    )

    return {
        "procesados": procesados,
        "markup_pvp_clasica": request.markup_pvp_clasica,
        "adicional_cuotas": request.adicional_cuotas,
    }


@router.post("/productos/recalcular-cuotas-masivo")
def recalcular_cuotas_masivo(
    request: RecalcularCuotasMasivoRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Recalcula cuotas masivamente desde el precio base existente (web o pvp).

    NO modifica el precio clásica/base: solo recalcula y persiste cuotas (3/6/9/12)
    para cada producto que matchea los filtros y tiene precio base > 0.
    """
    from app.services.pricing_calculator import (
        calcular_precio_producto,
        obtener_tipo_cambio_actual,
        convertir_a_pesos,
        obtener_grupo_subcategoria,
        obtener_comision_base,
        calcular_comision_ml_total,
        calcular_limpio,
        calcular_markup,
    )
    from app.api.endpoints.pricing import obtener_markup_adicional_cuotas

    lista_tipo = request.lista_tipo
    if lista_tipo not in ("web", "pvp"):
        raise HTTPException(400, "lista_tipo debe ser 'web' o 'pvp'")

    # Obtener productos con pricing existente (necesitan precio base para recalcular)
    query = db.query(ProductoERP, ProductoPricing).join(ProductoPricing, ProductoERP.item_id == ProductoPricing.item_id)

    # Solo productos que tengan precio base > 0 según lista_tipo
    if lista_tipo == "pvp":
        query = query.filter(ProductoPricing.precio_pvp.isnot(None), ProductoPricing.precio_pvp > 0)
    else:
        query = query.filter(ProductoPricing.precio_lista_ml.isnot(None), ProductoPricing.precio_lista_ml > 0)

    # Aplicar filtros (misma lógica que calcular-pvp-masivo / calcular-web-masivo)
    if request.filtros:
        if request.filtros.get("search"):
            search_term = f"%{request.filtros['search']}%"
            query = query.filter((ProductoERP.descripcion.ilike(search_term)) | (ProductoERP.codigo.ilike(search_term)))

        if request.filtros.get("con_stock") is not None:
            if request.filtros["con_stock"]:
                query = query.filter(ProductoERP.stock > 0)
            else:
                query = query.filter(ProductoERP.stock <= 0)

        if request.filtros.get("con_precio") is not None:
            if request.filtros["con_precio"]:
                query = query.filter(ProductoPricing.precio_lista_ml.isnot(None))
            else:
                query = query.filter(ProductoPricing.precio_lista_ml.is_(None))

        if request.filtros.get("marcas"):
            marcas_list = request.filtros["marcas"].split(",")
            query = query.filter(ProductoERP.marca.in_(marcas_list))

        if request.filtros.get("subcategorias"):
            subcats_list = [int(s) for s in request.filtros["subcategorias"].split(",")]
            query = query.filter(ProductoERP.subcategoria_id.in_(subcats_list))

        if request.filtros.get("con_rebate") is not None:
            if request.filtros["con_rebate"]:
                query = query.filter(ProductoPricing.participa_rebate == True)
            else:
                query = query.filter(
                    (ProductoPricing.participa_rebate == False) | (ProductoPricing.participa_rebate.is_(None))
                )

        if request.filtros.get("con_oferta") is not None:
            if request.filtros["con_oferta"]:
                query = query.filter(ProductoPricing.participa_oferta == True)
            else:
                query = query.filter(
                    (ProductoPricing.participa_oferta == False) | (ProductoPricing.participa_oferta.is_(None))
                )

        if request.filtros.get("con_web_transf") is not None:
            if request.filtros["con_web_transf"]:
                query = query.filter(ProductoPricing.participa_web_transferencia == True)
            else:
                query = query.filter(
                    (ProductoPricing.participa_web_transferencia == False)
                    | (ProductoPricing.participa_web_transferencia.is_(None))
                )

        if request.filtros.get("out_of_cards") is not None:
            if request.filtros["out_of_cards"]:
                query = query.filter(ProductoPricing.out_of_cards == True)
            else:
                query = query.filter((ProductoPricing.out_of_cards == False) | (ProductoPricing.out_of_cards.is_(None)))

        if request.filtros.get("colores"):
            colores_list = request.filtros["colores"].split(",")
            if "sin_color" in colores_list:
                colores_con_valor = [c for c in colores_list if c != "sin_color"]
                if colores_con_valor:
                    query = query.filter(
                        or_(
                            ProductoPricing.color_marcado.in_(colores_con_valor),
                            ProductoPricing.color_marcado.is_(None),
                        )
                    )
                else:
                    query = query.filter(ProductoPricing.color_marcado.is_(None))
            else:
                query = query.filter(ProductoPricing.color_marcado.in_(colores_list))

        if request.filtros.get("pms"):
            from app.models.marca_pm import MarcaPM

            pm_ids = [int(pm.strip()) for pm in request.filtros["pms"].split(",")]
            pares_pm = db.query(MarcaPM.marca, MarcaPM.categoria).filter(MarcaPM.usuario_id.in_(pm_ids)).all()
            if pares_pm:
                pares_upper = [(m.upper(), c.upper()) for m, c in pares_pm]
                query = query.filter(
                    tuple_(func.upper(ProductoERP.marca), func.upper(ProductoERP.categoria)).in_(pares_upper)
                )
            else:
                query = query.filter(ProductoERP.item_id == -1)

        if request.filtros.get("markup_clasica_positivo") is not None:
            if request.filtros["markup_clasica_positivo"]:
                query = query.filter(ProductoPricing.markup_calculado > 0)
            else:
                query = query.filter(
                    (ProductoPricing.markup_calculado <= 0) | (ProductoPricing.markup_calculado.is_(None))
                )

    productos = query.all()

    # Markup adicional global (fallback si el producto no tiene custom)
    markup_adicional_global = obtener_markup_adicional_cuotas(db)

    # Cache de tipo de cambio
    tipo_cambio_cache = {}
    procesados = 0
    errores = 0

    # Configuración de pricelists según lista_tipo
    if lista_tipo == "pvp":
        cuotas_config = {
            "precio_pvp_3_cuotas": (18, "markup_pvp_3_cuotas"),
            "precio_pvp_6_cuotas": (19, "markup_pvp_6_cuotas"),
            "precio_pvp_9_cuotas": (20, "markup_pvp_9_cuotas"),
            "precio_pvp_12_cuotas": (21, "markup_pvp_12_cuotas"),
        }
        pricelist_clasica = 12
    else:
        cuotas_config = {
            "precio_3_cuotas": (17, "markup_3_cuotas"),
            "precio_6_cuotas": (14, "markup_6_cuotas"),
            "precio_9_cuotas": (13, "markup_9_cuotas"),
            "precio_12_cuotas": (23, "markup_12_cuotas"),
        }
        pricelist_clasica = 4

    for producto_erp, producto_pricing in productos:
        try:
            # Obtener precio base existente
            if lista_tipo == "pvp":
                precio_base = float(producto_pricing.precio_pvp)
            else:
                precio_base = float(producto_pricing.precio_lista_ml)

            if precio_base <= 0:
                continue

            # Tipo de cambio
            tipo_cambio = None
            if producto_erp.moneda_costo == "USD":
                if "USD" not in tipo_cambio_cache:
                    tipo_cambio_cache["USD"] = obtener_tipo_cambio_actual(db, "USD")
                tipo_cambio = tipo_cambio_cache["USD"]
                if not tipo_cambio:
                    continue

            costo_ars = convertir_a_pesos(producto_erp.costo, producto_erp.moneda_costo, tipo_cambio)
            grupo_id = obtener_grupo_subcategoria(db, producto_erp.subcategoria_id)

            # Calcular markup del precio base existente
            comision_base = obtener_comision_base(db, pricelist_clasica, grupo_id)
            if not comision_base:
                continue

            comisiones = calcular_comision_ml_total(precio_base, comision_base, producto_erp.iva, db=db)
            limpio = calcular_limpio(
                precio_base,
                producto_erp.iva,
                producto_erp.envio or 0,
                comisiones["comision_total"],
                db=db,
                grupo_id=grupo_id,
            )
            markup = calcular_markup(limpio, costo_ars)
            markup_porcentaje = round(markup * 100, 2)

            # Markup adicional: custom del producto > global
            if lista_tipo == "pvp":
                markup_adicional = (
                    float(producto_pricing.markup_adicional_cuotas_pvp_custom)
                    if producto_pricing.markup_adicional_cuotas_pvp_custom is not None
                    else markup_adicional_global
                )
            else:
                markup_adicional = (
                    float(producto_pricing.markup_adicional_cuotas_custom)
                    if producto_pricing.markup_adicional_cuotas_custom is not None
                    else markup_adicional_global
                )

            # Calcular cada cuota
            for nombre_precio, (pricelist_id, nombre_markup) in cuotas_config.items():
                try:
                    resultado = calcular_precio_producto(
                        db=db,
                        costo=producto_erp.costo,
                        moneda_costo=producto_erp.moneda_costo,
                        iva=producto_erp.iva,
                        envio=producto_erp.envio or 0,
                        subcategoria_id=producto_erp.subcategoria_id,
                        pricelist_id=pricelist_id,
                        markup_objetivo=markup_porcentaje,
                        tipo_cambio=tipo_cambio,
                        adicional_markup=markup_adicional,
                    )

                    if "error" not in resultado:
                        precio_cuota = round(resultado["precio"], 2)
                        setattr(producto_pricing, nombre_precio, precio_cuota if precio_cuota > 0 else None)

                        # Calcular markup de esta cuota
                        if precio_cuota > 0:
                            comision_base_cuota = obtener_comision_base(db, pricelist_id, grupo_id)
                            if comision_base_cuota:
                                comisiones_cuota = calcular_comision_ml_total(
                                    float(precio_cuota), comision_base_cuota, producto_erp.iva, db=db
                                )
                                limpio_cuota = calcular_limpio(
                                    float(precio_cuota),
                                    producto_erp.iva,
                                    producto_erp.envio or 0,
                                    comisiones_cuota["comision_total"],
                                    db=db,
                                    grupo_id=grupo_id,
                                )
                                markup_cuota = round(calcular_markup(limpio_cuota, costo_ars) * 100, 2)
                                setattr(producto_pricing, nombre_markup, markup_cuota)
                            else:
                                setattr(producto_pricing, nombre_markup, None)
                        else:
                            setattr(producto_pricing, nombre_markup, None)
                    else:
                        setattr(producto_pricing, nombre_precio, None)
                        setattr(producto_pricing, nombre_markup, None)
                except Exception:
                    setattr(producto_pricing, nombre_precio, None)
                    setattr(producto_pricing, nombre_markup, None)

            producto_pricing.usuario_id = current_user.id
            producto_pricing.fecha_modificacion = datetime.now(UTC)
            procesados += 1

        except Exception as e:
            logger.warning(f"Error recalculando cuotas producto {producto_erp.item_id}: {str(e)}")
            errores += 1
            continue

    db.commit()

    # Registrar auditoría masiva
    from app.services.auditoria_service import registrar_auditoria
    from app.models.auditoria import TipoAccion

    registrar_auditoria(
        db=db,
        usuario_id=current_user.id,
        tipo_accion=TipoAccion.MODIFICACION_MASIVA,
        es_masivo=True,
        productos_afectados=procesados,
        valores_nuevos={
            "accion": "recalcular_cuotas_masivo",
            "lista_tipo": lista_tipo,
            "filtros": request.filtros,
        },
        comentario=f"Recálculo masivo de cuotas {lista_tipo.upper()}",
    )

    return {
        "procesados": procesados,
        "errores": errores,
        "lista_tipo": lista_tipo,
    }


@router.post("/productos/limpiar-rebate")
def limpiar_rebate(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Desactiva rebate en todos los productos"""
    from app.services.auditoria_service import registrar_auditoria
    from app.models.auditoria import TipoAccion

    count = db.query(ProductoPricing).filter(ProductoPricing.participa_rebate == True).count()

    db.query(ProductoPricing).update({ProductoPricing.participa_rebate: False})
    db.commit()

    # Registrar auditoría
    registrar_auditoria(
        db=db,
        usuario_id=current_user.id,
        tipo_accion=TipoAccion.MODIFICACION_MASIVA,
        es_masivo=True,
        productos_afectados=count,
        valores_nuevos={"accion": "limpiar_rebate"},
        comentario="Limpieza masiva de rebate",
    )

    return {"mensaje": "Rebate desactivado en todos los productos", "productos_actualizados": count}


@router.post("/productos/limpiar-web-transferencia")
def limpiar_web_transferencia(db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    """Desactiva web transferencia en todos los productos"""
    from app.services.auditoria_service import registrar_auditoria
    from app.models.auditoria import TipoAccion

    count = db.query(ProductoPricing).filter(ProductoPricing.participa_web_transferencia == True).count()

    db.query(ProductoPricing).update(
        {
            ProductoPricing.participa_web_transferencia: False,
            ProductoPricing.precio_web_transferencia: None,
            ProductoPricing.markup_web_real: None,
        }
    )
    db.commit()

    # Registrar auditoría
    registrar_auditoria(
        db=db,
        usuario_id=current_user.id,
        tipo_accion=TipoAccion.MODIFICACION_MASIVA,
        es_masivo=True,
        productos_afectados=count,
        valores_nuevos={"accion": "limpiar_web_transferencia"},
        comentario="Limpieza masiva de web transferencia",
    )

    return {"mensaje": "Web transferencia desactivada en todos los productos", "productos_actualizados": count}


@router.patch("/productos/{item_id}/config-cuotas")
def actualizar_config_cuotas_producto(
    item_id: int,
    body: ConfigCuotasRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Actualiza la configuración individual de recálculo de cuotas y markup adicional de un producto"""
    from app.services.permisos_service import verificar_permiso

    if not verificar_permiso(db, current_user, "productos.editar_precio_cuotas"):
        raise HTTPException(status_code=403, detail="No tienes permiso para editar configuración de cuotas")

    recalcular_cuotas_auto = body.recalcular_cuotas_auto
    markup_adicional_cuotas_custom = body.markup_adicional_cuotas_custom
    markup_adicional_cuotas_pvp_custom = body.markup_adicional_cuotas_pvp_custom

    # Validar markups si se proporcionan
    if markup_adicional_cuotas_custom is not None:
        try:
            markup_valor = float(markup_adicional_cuotas_custom)
            if markup_valor < 0 or markup_valor > 100:
                raise ValueError("Markup web debe estar entre 0 y 100")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    if markup_adicional_cuotas_pvp_custom is not None:
        try:
            markup_valor = float(markup_adicional_cuotas_pvp_custom)
            if markup_valor < 0 or markup_valor > 100:
                raise ValueError("Markup PVP debe estar entre 0 y 100")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # Buscar producto pricing
    producto_pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).first()

    if not producto_pricing:
        # Crear registro si no existe
        producto_pricing = ProductoPricing(item_id=item_id, usuario_id=current_user.id)
        db.add(producto_pricing)

    # Actualizar configuración
    producto_pricing.recalcular_cuotas_auto = recalcular_cuotas_auto
    producto_pricing.markup_adicional_cuotas_custom = markup_adicional_cuotas_custom
    producto_pricing.markup_adicional_cuotas_pvp_custom = markup_adicional_cuotas_pvp_custom
    producto_pricing.usuario_id = current_user.id
    producto_pricing.fecha_modificacion = datetime.now(UTC)

    db.commit()
    db.refresh(producto_pricing)

    return {
        "mensaje": "Configuración actualizada",
        "recalcular_cuotas_auto": producto_pricing.recalcular_cuotas_auto,
        "markup_adicional_cuotas_custom": float(producto_pricing.markup_adicional_cuotas_custom)
        if producto_pricing.markup_adicional_cuotas_custom
        else None,
        "markup_adicional_cuotas_pvp_custom": float(producto_pricing.markup_adicional_cuotas_pvp_custom)
        if producto_pricing.markup_adicional_cuotas_pvp_custom
        else None,
    }


@router.patch("/productos/{item_id}/out-of-cards")
def actualizar_out_of_cards(
    item_id: int, data: dict, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)
):
    """Actualiza el estado de out_of_cards de un producto"""
    from app.services.permisos_service import verificar_permiso

    if not verificar_permiso(db, current_user, "productos.toggle_out_of_cards"):
        raise HTTPException(status_code=403, detail="No tienes permiso para marcar out of cards")
    from app.services.auditoria_service import registrar_auditoria
    from app.models.auditoria import TipoAccion

    pricing = db.query(ProductoPricing).filter(ProductoPricing.item_id == item_id).first()

    if not pricing:
        raise HTTPException(status_code=404, detail="Producto no encontrado")

    # Guardar valor anterior
    valor_anterior = pricing.out_of_cards
    valor_nuevo = data.get("out_of_cards", False)

    pricing.out_of_cards = valor_nuevo
    db.commit()

    # Registrar auditoría
    registrar_auditoria(
        db=db,
        usuario_id=current_user.id,
        tipo_accion=TipoAccion.MARCAR_OUT_OF_CARDS if valor_nuevo else TipoAccion.DESMARCAR_OUT_OF_CARDS,
        item_id=item_id,
        valores_anteriores={"out_of_cards": valor_anterior},
        valores_nuevos={"out_of_cards": valor_nuevo},
    )

    return {"status": "success", "out_of_cards": pricing.out_of_cards}
