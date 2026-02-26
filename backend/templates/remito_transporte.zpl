^XA
^CI28
^LH0,30
^FX ═══════════════════════════════════════════════════════
^FX   REMITO DE TRANSPORTE — Etiqueta térmica 4x6"
^FX   Se imprime al final del lote de etiquetas cuando
^FX   el envío tiene transporte interprovincial asignado.
^FX ═══════════════════════════════════════════════════════

^FX — Título —
^FO0,10^GB800,60,60^FS
^FO0,20^A0N,40,40^FB800,1,0,C^FR^FDREMITO TRANSPORTE^FS

^FX — Fecha y Shipping ID —
^FO30,90^A0N,22,22^FDFecha: {{FECHA_ENVIO}}^FS
^FO430,90^A0N,22,22^FDEnvío: {{SHIPPING_ID}}^FS

^FO0,125^GB800,2,2^FS

^FX ═══════════════════════════════════════════════════════
^FX   TRANSPORTE (a dónde va la logística)
^FX ═══════════════════════════════════════════════════════

^FO30,145^A0N,30,30^FH^FDTransporte:^FS
^FO30,145^A0N,30,30^FH^FDTransporte:^FS
^FO220,145^A0N,30,30^FB560,1,0,L^FH^FD{{TRANSPORTE_NOMBRE}}^FS

^FO30,190^A0N,24,24^FH^FDDirecci_C3_B3n:^FS
^FO30,190^A0N,24,24^FH^FDDirecci_C3_B3n:^FS
^FO180,190^A0N,24,24^FB600,2,0,L^FH^FD{{TRANSPORTE_DIRECCION}}^FS

^FO30,250^A0N,24,24^FDCP: {{TRANSPORTE_CP}}^FS
^FO250,250^A0N,24,24^FDLocalidad: {{TRANSPORTE_LOCALIDAD}}^FS

^FO30,290^A0N,24,24^FH^FDTel: {{TRANSPORTE_TELEFONO}}^FS
^FO430,290^A0N,24,24^FH^FDHorario: {{TRANSPORTE_HORARIO}}^FS

^FO0,330^GB800,2,2^FS

^FX ═══════════════════════════════════════════════════════
^FX   DESTINATARIO FINAL (a dónde va el transporte)
^FX ═══════════════════════════════════════════════════════

^FO30,350^A0N,30,30^FH^FDDestinatario final:^FS
^FO30,350^A0N,30,30^FH^FDDestinatario final:^FS
^FO300,350^A0N,30,30^FB480,2,0,L^FH^FD{{NOMBRE_DESTINATARIO}}^FS

^FO30,435^A0N,24,24^FH^FDDirecci_C3_B3n:^FS
^FO30,435^A0N,24,24^FH^FDDirecci_C3_B3n:^FS
^FO180,435^A0N,24,24^FB600,2,0,L^FH^FD{{DIRECCION_CLIENTE}}^FS

^FO30,495^A0N,24,24^FDCP: {{CP_CLIENTE}}^FS
^FO250,495^A0N,24,24^FDCiudad: {{CIUDAD_CLIENTE}}^FS

^FO30,535^A0N,24,24^FH^FDTel: {{TELEFONO_DESTINATARIO}}^FS

^FO0,575^GB800,2,2^FS

^FX ═══════════════════════════════════════════════════════
^FX   DETALLE DE ENVÍO
^FX ═══════════════════════════════════════════════════════

^FO30,595^A0N,24,24^FDPedido: {{ID_PEDIDO}}^FS
^FO300,595^A0N,24,24^FDItems: {{CANTIDAD_ITEMS}}^FS

^FO30,635^A0N,24,24^FB750,2,0,L^FDSKU: {{SKUS_CONCATENADOS}}^FS

^FO30,695^A0N,24,24^FB750,3,0,L^FH^FDObs: {{OBSERVACIONES}}^FS

^FO0,775^GB800,2,2^FS

^FX — Bultos (grande, centrado) —
^FO0,795^A0N,70,70^FB800,1,0,C^FD{{TOTAL_BULTOS}} BULTO{{BULTOS_PLURAL}}^FS

^FX — Logística que lo lleva —
^FO0,885^A0N,24,24^FB800,1,0,C^FH^FDLog_C3_ADstica: {{LOGISTICA_NOMBRE}}^FS

^FX — Pie —
^FO0,935^GB800,2,2^FS
^FO0,955^A0N,20,20^FB800,1,0,C^FDGauss Online - Felipe Vallese 1559 - CP 1406 - Tel: (11) 5263-0601^FS

^XZ
^XA^MCY^XZ
