# Gestión Full: auditoría de operaciones

Las acciones de Gestión Full (override, Listo, paquete/envío, qty export, inbound, quitar del envío, export, U/caja) quedan registradas en la auditoría global del sistema, con usuario y detalle JSON. Al quitar inventarios del envío se guarda un snapshot aunque la línea ya no esté en el paquete.

Si al quitar líneas (o al asignar inbound) todas las que quedan con cantidad a enviar ya tienen inbound, el paquete se cierra solo — es el mismo criterio de siempre al completar el envío.
