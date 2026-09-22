# Ventas ML mockups (Stitch)

`listado.*` and `detalle.*` were generated with Stitch on 2026-09-21 as the visual reference for the `ventas-ml-rediseno` change.

They are a **visual reference only**: layout, information hierarchy, icons, typography and density. Numbers, money rules and data sources come from the specs in `openspec/`, never from these files. Known differences:

- The detail mockup shows Neto as the amount ML deposited and subtracts SIRTAC. The current rule (`openspec/specs/ml-ventas-desglose-ui`, `ml-ventas-neto`) adds SIRTAC back to Neto, shows it as informational, and adds the sub-line "MP $X · SIRTAC $Y".
- Data invented by Stitch is out of scope: card brand and last 4 digits, buyer CUIT, "Factura A emitida", "vs mes anterior" trends, "Objetivo" targets, the account selector and the top navigation.
