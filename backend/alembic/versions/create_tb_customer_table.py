"""create tb_customer table

Revision ID: create_tb_customer
Revises: change_pm_string
Create Date: 2025-12-03

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'create_tb_customer'
down_revision = 'change_pm_string'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tb_customer',
        # Primary Keys
        sa.Column('comp_id', sa.Integer(), nullable=False),
        sa.Column('cust_id', sa.Integer(), nullable=False),

        # Datos básicos
        sa.Column('bra_id', sa.Integer(), nullable=True),
        sa.Column('cust_name', sa.String(500), nullable=True),
        sa.Column('cust_name1', sa.String(500), nullable=True),
        sa.Column('fc_id', sa.Integer(), nullable=True),
        sa.Column('cust_taxnumber', sa.String(50), nullable=True),
        sa.Column('tnt_id', sa.Integer(), nullable=True),

        # Ingresos Brutos
        sa.Column('stcib_id', sa.Integer(), nullable=True),
        sa.Column('cust_taxibnumber', sa.String(50), nullable=True),

        # Contacto
        sa.Column('cust_web', sa.String(255), nullable=True),
        sa.Column('cust_contact', sa.String(255), nullable=True),
        sa.Column('cust_phone1', sa.String(100), nullable=True),
        sa.Column('cust_phone2', sa.String(100), nullable=True),
        sa.Column('cust_cellphone', sa.String(100), nullable=True),
        sa.Column('cust_cellphone2', sa.String(100), nullable=True),
        sa.Column('cust_email', sa.String(255), nullable=True),
        sa.Column('cust_fax', sa.String(100), nullable=True),
        sa.Column('cust_whatsapp', sa.String(100), nullable=True),

        # Dirección
        sa.Column('cust_address', sa.String(500), nullable=True),
        sa.Column('cust_city', sa.String(255), nullable=True),
        sa.Column('cust_zip', sa.String(20), nullable=True),
        sa.Column('country_id', sa.Integer(), nullable=True),
        sa.Column('state_id', sa.Integer(), nullable=True),
        sa.Column('city_id', sa.Integer(), nullable=True),
        sa.Column('street_id', sa.Integer(), nullable=True),
        sa.Column('cust_addressnumber', sa.String(50), nullable=True),
        sa.Column('cust_addressadditional', sa.String(255), nullable=True),
        sa.Column('cust_addressfloor', sa.String(50), nullable=True),

        # Dirección de entrega y pagos
        sa.Column('cust_address4delivery', sa.String(500), nullable=True),
        sa.Column('cust_address4payments', sa.String(500), nullable=True),

        # Estado
        sa.Column('cust_inactive', sa.Boolean(), nullable=True),
        sa.Column('cust_isediting', sa.Boolean(), nullable=True),
        sa.Column('cust_iseditingcd', sa.DateTime(), nullable=True),
        sa.Column('cust_iseditinguserid', sa.Integer(), nullable=True),

        # Comercial
        sa.Column('sm_id', sa.Integer(), nullable=True),
        sa.Column('sm_id_2', sa.Integer(), nullable=True),
        sa.Column('cust_partnerof', sa.Integer(), nullable=True),

        # Crédito
        sa.Column('cust_credit_max', sa.Numeric(18, 2), nullable=True),
        sa.Column('cust_credit_own', sa.Numeric(18, 2), nullable=True),
        sa.Column('cust_credit_curr_id', sa.Integer(), nullable=True),
        sa.Column('curr_id', sa.Integer(), nullable=True),

        # Configuraciones comerciales
        sa.Column('ck_id', sa.Integer(), nullable=True),
        sa.Column('st_id', sa.Integer(), nullable=True),
        sa.Column('disc_id', sa.Integer(), nullable=True),
        sa.Column('dl_id', sa.Integer(), nullable=True),
        sa.Column('prli_id', sa.Integer(), nullable=True),
        sa.Column('prli_id_alternative', sa.Integer(), nullable=True),
        sa.Column('stor_id', sa.Integer(), nullable=True),
        sa.Column('coslis_id', sa.Integer(), nullable=True),
        sa.Column('coslis_idb', sa.Integer(), nullable=True),

        # Contabilidad y usuarios
        sa.Column('acc_count_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('user_id4insert', sa.Integer(), nullable=True),
        sa.Column('user_id4lastupdate', sa.Integer(), nullable=True),

        # Web/eCommerce
        sa.Column('cust_webpassword', sa.String(255), nullable=True),
        sa.Column('cust_webnickname', sa.String(255), nullable=True),
        sa.Column('cust_webpending2verify', sa.Boolean(), nullable=True),
        sa.Column('cust_login', sa.String(255), nullable=True),
        sa.Column('cust_login_cd', sa.DateTime(), nullable=True),
        sa.Column('cust_login_ip', sa.String(100), nullable=True),
        sa.Column('cust_login_name', sa.String(255), nullable=True),
        sa.Column('cust_showstock', sa.Boolean(), nullable=True),
        sa.Column('cust_showpricelist', sa.Boolean(), nullable=True),
        sa.Column('cust_showzerostockitems', sa.Boolean(), nullable=True),

        # Orden de venta
        sa.Column('cust_saleordermaxvalue', sa.Numeric(18, 2), nullable=True),
        sa.Column('cust_saleorderdisableconcurrentproc', sa.Boolean(), nullable=True),
        sa.Column('cust_saleorderbranchtransfer', sa.Boolean(), nullable=True),
        sa.Column('bra_id4emmition', sa.Integer(), nullable=True),

        # Notas
        sa.Column('cust_annotation', sa.Text(), nullable=True),
        sa.Column('cust_note1', sa.Text(), nullable=True),
        sa.Column('cust_note2', sa.Text(), nullable=True),
        sa.Column('cust_note3', sa.Text(), nullable=True),
        sa.Column('cust_note4', sa.Text(), nullable=True),
        sa.Column('cust_notes', sa.Text(), nullable=True),
        sa.Column('cust_crmcomment', sa.Text(), nullable=True),

        # Judicial
        sa.Column('cust_judman', sa.Boolean(), nullable=True),
        sa.Column('cust_judmanblockcollection', sa.Boolean(), nullable=True),

        # Contactos adicionales
        sa.Column('cust_contact4payments', sa.String(255), nullable=True),
        sa.Column('cust_email4payments', sa.String(255), nullable=True),
        sa.Column('cust_contact4management', sa.String(255), nullable=True),
        sa.Column('cust_email4management', sa.String(255), nullable=True),
        sa.Column('cust_contact4administration', sa.String(255), nullable=True),
        sa.Column('cust_email4administration', sa.String(255), nullable=True),
        sa.Column('cust_contact4logistics', sa.String(255), nullable=True),
        sa.Column('cust_email4logistics', sa.String(255), nullable=True),
        sa.Column('cust_contact4alternative', sa.String(255), nullable=True),
        sa.Column('cust_email4alternative', sa.String(255), nullable=True),
        sa.Column('cust_contact4alternativeii', sa.String(255), nullable=True),
        sa.Column('cust_email4alternativeii', sa.String(255), nullable=True),
        sa.Column('cust_contact4rma', sa.String(255), nullable=True),
        sa.Column('cust_email4rma', sa.String(255), nullable=True),
        sa.Column('cust_address4rma', sa.String(500), nullable=True),
        sa.Column('cust_phone4rma', sa.String(100), nullable=True),
        sa.Column('cust_isavailable4internalrma', sa.Boolean(), nullable=True),

        # Actividad y exclusiones
        sa.Column('act_id', sa.Integer(), nullable=True),
        sa.Column('cust_excludeinciti', sa.Boolean(), nullable=True),
        sa.Column('cust_excludeofcustomermailing', sa.Boolean(), nullable=True),
        sa.Column('cust_mailing4custoverduedebt_excluded', sa.Boolean(), nullable=True),
        sa.Column('cust_disablenps', sa.Boolean(), nullable=True),

        # Rating
        sa.Column('rating_id', sa.Integer(), nullable=True),
        sa.Column('rating_id_previous', sa.Integer(), nullable=True),
        sa.Column('rating_id_cd', sa.DateTime(), nullable=True),
        sa.Column('cust_ratingprocesscheck', sa.Boolean(), nullable=True),

        # Datos personales
        sa.Column('cust_firstname', sa.String(255), nullable=True),
        sa.Column('cust_lastname', sa.String(255), nullable=True),
        sa.Column('cust_birthday', sa.DateTime(), nullable=True),
        sa.Column('cust_maleorfemale', sa.String(10), nullable=True),
        sa.Column('cust_age', sa.Integer(), nullable=True),
        sa.Column('marst_id', sa.Integer(), nullable=True),

        # Trabajo
        sa.Column('cust_jobtitle', sa.String(255), nullable=True),
        sa.Column('cust_jobaddress', sa.String(500), nullable=True),
        sa.Column('cust_jobcity', sa.String(255), nullable=True),
        sa.Column('cust_jobcity_id', sa.Integer(), nullable=True),
        sa.Column('cust_jobphone', sa.String(100), nullable=True),
        sa.Column('cust_jobname', sa.String(255), nullable=True),
        sa.Column('cust_jobpaydate', sa.DateTime(), nullable=True),
        sa.Column('cust_jobadmissiondate', sa.DateTime(), nullable=True),
        sa.Column('cust_jobyearinit', sa.Integer(), nullable=True),
        sa.Column('cust_jobpayintervalis15', sa.Boolean(), nullable=True),
        sa.Column('cust_remuneration', sa.Numeric(18, 2), nullable=True),

        # Propiedad
        sa.Column('cust_isowner', sa.Boolean(), nullable=True),
        sa.Column('cust_ownerof', sa.String(255), nullable=True),

        # Corporación y grupos
        sa.Column('corp_id', sa.Integer(), nullable=True),
        sa.Column('stg_id', sa.Integer(), nullable=True),
        sa.Column('stca_id', sa.Integer(), nullable=True),
        sa.Column('brag_id', sa.Integer(), nullable=True),
        sa.Column('ss_id', sa.Integer(), nullable=True),

        # Imagen y préstamos
        sa.Column('cust_imagechecksum', sa.String(255), nullable=True),
        sa.Column('cust_disabled4personalloan', sa.Boolean(), nullable=True),
        sa.Column('cram_id', sa.Integer(), nullable=True),
        sa.Column('cust_ramification', sa.String(255), nullable=True),
        sa.Column('rmap_id', sa.Integer(), nullable=True),

        # MercadoLibre
        sa.Column('cust_mercadolibrenickname', sa.String(255), nullable=True),
        sa.Column('cust_mercadolibreid', sa.String(100), nullable=True),
        sa.Column('mluser_id', sa.Integer(), nullable=True),

        # Verificación
        sa.Column('cust_checked', sa.Boolean(), nullable=True),
        sa.Column('cust_4initialvalues', sa.Boolean(), nullable=True),
        sa.Column('cust_updatedfromabm', sa.Boolean(), nullable=True),

        # Factura electrónica
        sa.Column('fecountry_id', sa.Integer(), nullable=True),
        sa.Column('fex_cuitid', sa.String(50), nullable=True),
        sa.Column('cust_electronicinvoice_mipyme_mode', sa.Integer(), nullable=True),
        sa.Column('def_id', sa.Integer(), nullable=True),
        sa.Column('cmde_noaction', sa.Boolean(), nullable=True),

        # GBP específicos
        sa.Column('cust_gbpurl', sa.String(500), nullable=True),
        sa.Column('cust_gbpmodules', sa.String(255), nullable=True),
        sa.Column('cust_gbpdbname', sa.String(255), nullable=True),
        sa.Column('cust_gbpuserqty', sa.Integer(), nullable=True),
        sa.Column('cust_gbpbranchqty', sa.Integer(), nullable=True),
        sa.Column('cust_gbpcompanyqty', sa.Integer(), nullable=True),
        sa.Column('cust_gbplasturlupdate', sa.DateTime(), nullable=True),
        sa.Column('cust_gbpcg', sa.String(255), nullable=True),
        sa.Column('cust_gbpsn', sa.String(255), nullable=True),
        sa.Column('cust_gbplpd', sa.DateTime(), nullable=True),
        sa.Column('cust_gbpurl2', sa.String(500), nullable=True),
        sa.Column('cust_gbpurl3', sa.String(500), nullable=True),
        sa.Column('cust_gbpurl4website', sa.String(500), nullable=True),
        sa.Column('cust_gbpdebtorinfo', sa.Text(), nullable=True),
        sa.Column('cust_gbpmessage', sa.Text(), nullable=True),
        sa.Column('cust_gbpimplementador', sa.String(255), nullable=True),
        sa.Column('cust_gbpcrm_user_id', sa.Integer(), nullable=True),
        sa.Column('cust_gbpmeli_serverurl', sa.String(500), nullable=True),
        sa.Column('cust_gbpcomunityid', sa.String(100), nullable=True),
        sa.Column('cust_gbpcommunityurl', sa.String(500), nullable=True),
        sa.Column('cust_gbpinproduction', sa.Boolean(), nullable=True),
        sa.Column('cust_hascm05configurations', sa.Boolean(), nullable=True),

        # Migración y relaciones
        sa.Column('cust_migrationid', sa.String(100), nullable=True),
        sa.Column('ws_internalid', sa.String(100), nullable=True),
        sa.Column('cust_id_related', sa.Integer(), nullable=True),
        sa.Column('cust_4onlysign', sa.Boolean(), nullable=True),
        sa.Column('cust_credit_max_last', sa.Numeric(18, 2), nullable=True),
        sa.Column('cust_credit_max_overcomedate', sa.DateTime(), nullable=True),

        # Pagos y otros
        sa.Column('cust_lastpaymentdatefromothererp', sa.DateTime(), nullable=True),
        sa.Column('sts_sujid', sa.Integer(), nullable=True),
        sa.Column('cust_excludefromsaleordercollect', sa.Boolean(), nullable=True),
        sa.Column('col_tcr_1', sa.String(255), nullable=True),
        sa.Column('col_gta_1', sa.String(255), nullable=True),

        # Fechas de auditoría
        sa.Column('cust_cd', sa.DateTime(), nullable=True),
        sa.Column('cust_lastupdate', sa.DateTime(), nullable=True),

        # Auditoría local
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),

        sa.PrimaryKeyConstraint('comp_id', 'cust_id')
    )

    # Índices
    op.create_index('ix_tb_customer_cust_id', 'tb_customer', ['cust_id'], unique=False)
    op.create_index('ix_tb_customer_cust_taxnumber', 'tb_customer', ['cust_taxnumber'], unique=False)


def downgrade():
    op.drop_index('ix_tb_customer_cust_taxnumber', table_name='tb_customer')
    op.drop_index('ix_tb_customer_cust_id', table_name='tb_customer')
    op.drop_table('tb_customer')
