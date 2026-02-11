from sqlalchemy import Column, Integer, String, Boolean, DateTime, Numeric, Text
from sqlalchemy.sql import func
from app.core.database import Base


class MercadoLibreItemPublicado(Base):
    """
    Modelo para tbMercadoLibre_ItemsPublicados del ERP
    Contiene todas las publicaciones de items en MercadoLibre
    """

    __tablename__ = "tb_mercadolibre_items_publicados"

    # Primary Key
    mlp_id = Column(Integer, primary_key=True, index=True)

    # IDs de referencia
    comp_id = Column(Integer)
    bra_id = Column(Integer)
    stor_id = Column(Integer)
    prli_id = Column(Integer, index=True)
    item_id = Column(Integer, index=True)
    user_id = Column(Integer)
    mls_id = Column(Integer)
    mlipc_id = Column(Integer)
    st_id = Column(Integer)
    disc_id = Column(Integer)
    dl_id = Column(Integer)
    mlmp_id = Column(Integer)
    stor_id4StockAvailability = Column("stor_id4stockavailability", Integer)
    storg_id = Column(Integer)
    prli_id4MercadoShop = Column("prli_id4mercadoshop", Integer)
    prli_id_PriceByQty_1 = Column("prli_id_pricebyqty_1", Integer)
    prli_id_PriceByQty_2 = Column("prli_id_pricebyqty_2", Integer)
    prli_id_PriceByQty_3 = Column("prli_id_pricebyqty_3", Integer)
    prli_id_PriceByQty_4 = Column("prli_id_pricebyqty_4", Integer)
    prli_id_PriceByQty_5 = Column("prli_id_pricebyqty_5", Integer)

    # Datos básicos de publicación
    mlp_publicationID = Column("mlp_publicationid", String(50), index=True)
    mlp_itemTitle = Column("mlp_itemtitle", String(500))
    mlp_itemSubTitle = Column("mlp_itemsubtitle", String(500))
    mlp_subTitle = Column("mlp_subtitle", String(500))
    mlp_itemDesc = Column("mlp_itemdesc", Text)
    mlp_itemHTML = Column("mlp_itemhtml", Text)
    mlp_itemHTML2 = Column("mlp_itemhtml2", Text)
    mlp_itemHTML3 = Column("mlp_itemhtml3", Text)
    mlp_family_name = Column("mlp_family_name", String(255))
    mlp_userProductID = Column("mlp_userproductid", String(100))

    # Precios y moneda
    mlp_price = Column(Numeric(18, 6))
    curr_id = Column(Integer)
    mlp_lastPublicatedPrice = Column("mlp_lastpublicatedprice", Numeric(18, 6))
    mlp_lastPublicatedCurrID = Column("mlp_lastpublicatedcurrid", Integer)
    mlp_lastPublicatedExchange = Column("mlp_lastpublicatedexchange", Numeric(18, 10))
    mlp_price4FreeShipping = Column("mlp_price4freeshipping", Numeric(18, 6))
    mlp_price4AdditionalCost = Column("mlp_price4additionalcost", Numeric(18, 6))
    mlp_lastPriceInformedByML = Column("mlp_lastpriceinformedbyml", Numeric(18, 6))
    mlp_Price2WinLastPrice = Column("mlp_price2winlastprice", Numeric(18, 6))

    # Cantidades
    mlp_initQty = Column("mlp_initqty", Integer)
    mlp_minQty4Pause = Column("mlp_minqty4pause", Integer)
    mlp_sold_quantity = Column(Integer)
    mlp_lastPublicatedAvailableQTY = Column("mlp_lastpublicatedavailableqty", Integer)
    mlp_min_purchase_unit_1 = Column(Integer)
    mlp_min_purchase_unit_2 = Column(Integer)
    mlp_min_purchase_unit_3 = Column(Integer)
    mlp_min_purchase_unit_4 = Column(Integer)
    mlp_min_purchase_unit_5 = Column(Integer)

    # Estados y flags
    optval_statusId = Column("optval_statusid", Integer)
    mlp_Active = Column("mlp_active", Boolean, default=True)
    mlp_4Revision = Column("mlp_4revision", Boolean, default=False)
    mlp_revisionMessage = Column("mlp_revisionmessage", Text)
    mlp_lastStatusID = Column("mlp_laststatusid", Integer)
    mlp_variationError = Column("mlp_variationerror", Text)
    health = Column(Numeric(5, 2))

    # Tipo de publicación
    mlp_listing_type_id = Column(String(50))
    mlp_buying_mode = Column(String(50))
    mlp_isFixedPrice = Column("mlp_isfixedprice", Boolean, default=False)

    # Comisiones
    mlp_listing_fee_amount = Column(Numeric(18, 6))
    mlp_sale_fee_amount = Column(Numeric(18, 6))

    # URLs y media
    mlp_permalink = Column(String(500))
    mlp_thumbnail = Column(String(500))
    mlp_video_id = Column(String(100))

    # Fechas
    mlp_inicDate = Column("mlp_inicdate", DateTime)
    mlp_endDate = Column("mlp_enddate", DateTime)
    mlp_lastUpdate = Column("mlp_lastupdate", DateTime)
    mlp_start_time = Column(DateTime)
    mlp_stop_time = Column(DateTime)
    mlp_creationDate = Column("mlp_creationdate", DateTime)
    dateof_lastUpdate = Column("dateof_lastupdate", DateTime)
    dateof_lastUpdateFromMeLi = Column("dateof_lastupdatefromml", DateTime)
    mlp_lastUpdateFromERP = Column("mlp_lastupdatefromerp", DateTime)
    mlp_Price2WinLastActivation = Column("mlp_price2winlastactivation", DateTime)
    mlp_catalog_forewarning_date = Column(DateTime)
    mlp_statistics_lastUpdate = Column("mlp_statistics_lastupdate", DateTime)
    userid_lastUpdate = Column("userid_lastupdate", Integer)

    # Envíos y logística
    mlp_accepts_mercadopago = Column(Boolean, default=False)
    mlp_local_pick_up = Column(Boolean, default=False)
    mlp_free_shipping = Column(Boolean, default=False)
    mlp_free_method = Column(String(50))
    mlp_free_shippingMShops = Column("mlp_free_shippingmshops", Boolean, default=False)
    mlp_free_shippingMShops_Coeficient = Column("mlp_free_shippingmshops_coeficient", Numeric(10, 4))
    mlp_manufacturing_time = Column(Integer)

    # Categoría
    mlp_publicationCategoryID = Column("mlp_publicationcategoryid", String(50))

    # Garantía
    mlp_warranty = Column(Text)
    mlp_warranty_type = Column(String(100))
    mlp_warranty_time = Column(String(50))
    mlp_warranty_time_value = Column(Integer)

    # Catálogo
    mlp_catalog_product_id = Column(String(50))
    mlp_catalog_listing = Column(Boolean, default=False)
    mlp_catalog_isAvailable = Column("mlp_catalog_isavailable", Boolean, default=False)
    mlp_catalog_forewarning = Column(Boolean, default=False)
    mlp_catalog_boost = Column(Numeric(5, 2))
    mlp_blockCatalogPriceUpdateFromNormalPublication = Column(
        "mlp_blockcatalogpriceupdatefromnormalpublication", Boolean, default=False
    )

    # Fulfillment
    mlp_is4FulFillment = Column("mlp_is4fulfillment", Boolean, default=False)
    mlp_is4FullAndFlex = Column("mlp_is4fullandflex", Boolean, default=False)
    mlp_forceSO4Commercial = Column("mlp_forceso4commercial", Boolean, default=False)

    # Ofertas y campañas
    mlp_isInDeal = Column("mlp_isindeal", Boolean, default=False)
    mlp_isInCampaign = Column("mlp_isincampaign", Boolean, default=False)
    mlp_hasOffer = Column("mlp_hasoffer", Boolean, default=False)
    mlp_hasCandidate = Column("mlp_hascandidate", Boolean, default=False)
    mlp_priceDirectDiscountPercenage = Column("mlp_pricedirectdiscountpercenage", Numeric(5, 2))

    # Price to Win
    mlp_isAvailable4Price2Win = Column("mlp_isavailable4price2win", Boolean, default=False)
    mlp_hasPrice2WinActive = Column("mlp_hasprice2winactive", Boolean, default=False)

    # Ahora programas (financiación)
    mlp_ahora3 = Column(Boolean, default=False)
    mlp_ahora6 = Column(Boolean, default=False)
    mlp_ahora12 = Column(Boolean, default=False)
    mlp_ahora18 = Column(Boolean, default=False)
    mlp_ahora24 = Column(Boolean, default=False)
    mlp_ahora30 = Column(Boolean, default=False)
    mlp_ahora3mshops = Column(Boolean, default=False)
    mlp_ahora6mshops = Column(Boolean, default=False)
    mlp_ahora12mshops = Column(Boolean, default=False)
    mlp_ahora24mshops = Column(Boolean, default=False)
    mlp_ahora12_paidByBuyer = Column("mlp_ahora12_paidbybuyer", Boolean, default=False)
    mlp_ahora3plan = Column(Boolean, default=False)
    mlp_ahora3planmshops = Column(Boolean, default=False)

    # Cuotas simples
    mlp_cuotasimple3 = Column(Boolean, default=False)
    mlp_cuotasimple6 = Column(Boolean, default=False)
    mlp_cuotasimple12 = Column(Boolean, default=False)
    mlp_cuotasimple_paidbybuyer = Column(Boolean, default=False)
    mlp_cuotasimple3mshops = Column(Boolean, default=False)
    mlp_cuotasimple6mshops = Column(Boolean, default=False)
    mlp_cuotasimple12mshops = Column(Boolean, default=False)

    # Campañas especiales
    mlp_9xCampaign = Column("mlp_9xcampaign", Boolean, default=False)
    mlp_9xCampaignmshops = Column("mlp_9xcampaignmshops", Boolean, default=False)
    mlp_12xCampaign = Column("mlp_12xcampaign", Boolean, default=False)
    mlp_12xCampaignmshops = Column("mlp_12xcampaignmshops", Boolean, default=False)

    # PCJ Co-funded
    mlp_pcjcofunded = Column(Boolean, default=False)
    mlp_pcjcofundedmshops = Column(Boolean, default=False)

    # Estadísticas
    mlp_statistics_MinPrice4Category = Column("mlp_statistics_minprice4category", Numeric(18, 6))
    mlp_statistics_MaxPrice4Category = Column("mlp_statistics_maxprice4category", Numeric(18, 6))
    mlp_statistics_AvgPrice4Category = Column("mlp_statistics_avgprice4category", Numeric(18, 6))
    mlp_statistics_MaxPrice4EAN = Column("mlp_statistics_maxprice4ean", Numeric(18, 6))
    mlp_statistics_MinPrice4EAN = Column("mlp_statistics_minprice4ean", Numeric(18, 6))
    mlp_statistics_AvgPrice4EAN = Column("mlp_statistics_avgprice4ean", Numeric(18, 6))
    mlp_statistics_AvgSales4Week = Column("mlp_statistics_avgsales4week", Numeric(18, 6))
    mlp_statistics_hasData = Column("mlp_statistics_hasdata", Boolean, default=False)

    # Otros flags
    mlp_allowPublicationsWithNoStock = Column("mlp_allowpublicationswithnostock", Boolean, default=False)
    mlp_force2CheckStock = Column("mlp_force2checkstock", Boolean, default=False)
    mlp_lastPublicatedPriceOrExchangeChanged = Column(
        "mlp_lastpublicatedpriceorexchangechanged", Boolean, default=False
    )
    mlp_isME1Available = Column("mlp_isme1available", Boolean, default=False)
    mlp_fixPublicationDeliveryCharge = Column("mlp_fixpublicationdeliverycharge", Boolean, default=False)
    mlp_blockPriceUpdate = Column("mlp_blockpriceupdate", Boolean, default=False)
    mlp_blockPriceUpdate4mercadoShops = Column("mlp_blockpriceupdate4mercadoshops", Boolean, default=False)
    mlp_mustUpdate_prli_id4MercadoShop = Column("mlp_mustupdate_prli_id4mercadoshop", Boolean, default=False)
    mlp_forcePriceUpdate = Column("mlp_forcepriceupdate", Boolean, default=False)
    mlp_hasIncompleteCompatibilities = Column("mlp_hasincompletecompatibilities", Boolean, default=False)
    mlp_notExistsInMeli_by404 = Column("mlp_notexistsinmeli_by404", Boolean, default=False)
    mlp_poorImage = Column("mlp_poorimage", Boolean, default=False)
    mlp_labelPrintModuleNoPrintSecondLabel = Column("mlp_labelprintmodulenoprintsecondlabel", Boolean, default=False)
    mlp_loyalty_discount_eligible = Column(Boolean, default=False)

    # Configuraciones adicionales
    mlp_official_store_id = Column(Integer)
    mlp_sizeChartID = Column("mlp_sizechartid", Integer)
    mlp_attributesVerificationNeeded = Column("mlp_attributesverificationneeded", Boolean, default=False)
    mlp_channelID = Column("mlp_channelid", Integer)
    mlp_prli_id4MercadoShopPlusDeliveryCharge = Column("mlp_prli_id4mercadoshopplusdeliverycharge", Integer)

    # Automatización
    mlp_Aut_Int_Ext_Enabled = Column("mlp_aut_int_ext_enabled", Boolean, default=False)
    mlp_Aut_Int_Ext_Percentage = Column("mlp_aut_int_ext_percentage", Numeric(10, 4))
    mlp_Aut_Int_Ext_Type = Column("mlp_aut_int_ext_type", Integer)

    # Price by Quantity
    mlp_Enabled4PriceByQty = Column("mlp_enabled4pricebyqty", Boolean, default=False)

    # Validaciones JSON
    mlp_lastJSonValidation = Column("mlp_lastjsonvalidation", Text)

    # Auditoría local
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<MercadoLibreItemPublicado(mlp_id={self.mlp_id}, mlp_publicationID={self.mlp_publicationID}, item_id={self.item_id}, mlp_itemTitle={self.mlp_itemTitle[:50] if self.mlp_itemTitle else None})>"
