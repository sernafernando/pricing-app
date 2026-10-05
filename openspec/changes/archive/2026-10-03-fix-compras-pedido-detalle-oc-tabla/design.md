# Design

1. Schema: add `item_code`, `oc_comp_id`, `oc_bra_id`, `oc_poh_id` on `OrdenCompraLineaResponse`. Keep response top-level first triple + `lines` (all OCs’ lines flat).
2. Service: `triples_for_pedido`; SQL OR of triples; SELECT `p.codigo AS item_code` + oc ids on each row.
3. Front: group `ocDetalle.lines` by `oc_poh_id`; one `OC #n` section each; columns Código / Descripción / Qty / Saldo; CSS center + ellipsis on description.
4. Fetch still gated on `oc_poh_id` (header always set when any OC linked).
