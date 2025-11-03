-- Otorgar permisos sobre la tabla marcas_pm al usuario de la aplicación
GRANT ALL PRIVILEGES ON TABLE marcas_pm TO pricing_user;

-- Otorgar permisos sobre la secuencia (para INSERT con SERIAL)
GRANT USAGE, SELECT ON SEQUENCE marcas_pm_id_seq TO pricing_user;
