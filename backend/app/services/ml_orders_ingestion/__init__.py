"""ML API-sourced order/shipment ingestion (ml-ventas-fuente-de-verdad).

Pure mapping (`mapper.py`) and, from slice 3 onward, the ingestion/sweep
services that write to `ml_orders_ops`/`ml_order_items_ops`/`ml_shipments_ops`
through the single idempotent upsert path. See design doc (obs #1823).
"""
