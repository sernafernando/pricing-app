{
  "schemaName": "gentle-ai.sdd-research/v1",
  "revision": 2,
  "change": "fix-markup-masivo-filtro",
  "outcome": "done",
  "accessed_at": "2026-09-04T15:31:32Z",
  "questions": [
    {
      "id": "Q1",
      "text": "By code evidence alone: what exact UI strings and values define the Acciones masivas modal product count, and how do they relate to `Mostrando {productos.length} de {totalProductos}` and `pageSize` including option `9999` (\"Todos\")?"
    },
    {
      "id": "Q2",
      "text": "What does PR #1242 (body + review comments) state about operating on visible page vs full filter set?"
    },
    {
      "id": "Q3",
      "text": "Can documentation/PR evidence alone determine what on-screen string showed \"18\" in the reporter’s session, or must that remain uncertainty for orchestrator product discovery?"
    }
  ],
  "admission": {
    "schemaName": "gentle-ai.sdd-research-capability/v1",
    "status": "admitted",
    "requested_classes": [
      "documentation",
      "open-web"
    ],
    "observed_grants": {
      "documentation": [
        "/home/user/.herdr/worktrees/pricing-app/fix-markup-filtro/openspec/changes/fix-markup-masivo-filtro/exploration.md",
        "/home/user/.herdr/worktrees/pricing-app/fix-markup-filtro/frontend/src/components/AplicarMarkupMasivoModal.jsx",
        "/home/user/.herdr/worktrees/pricing-app/fix-markup-filtro/frontend/src/pages/Productos.jsx",
        "/home/user/.herdr/worktrees/pricing-app/fix-markup-filtro/frontend/src/hooks/useProductosData.js",
        "/home/user/.herdr/worktrees/pricing-app/fix-markup-filtro/frontend/src/hooks/useProductosFilters.js"
      ],
      "open-web": [
        "https://github.com/sernafernando/pricing-app/pull/1242"
      ]
    },
    "denied_classes": [],
    "notes": "Persistence tools are not evidence grants. No undeclared class was used for claims."
  },
  "sources": [
    {
      "id": "S1",
      "class": "documentation",
      "title": "AplicarMarkupMasivoModal.jsx — modal count and copy",
      "publisher": "pricing-app worktree fix-markup-filtro",
      "url": "file:///home/user/.herdr/worktrees/pricing-app/fix-markup-filtro/frontend/src/components/AplicarMarkupMasivoModal.jsx",
      "accessed_at": "2026-09-04T15:31:32Z",
      "excerpt": "const total = productos?.length ?? 0; ... Acciones masivas — {total} producto(s) visible(s); Opera solo sobre los productos visibles en la grilla (página actual y filtros).; Aplicar a {total} producto(s); No hay productos en la vista actual; Hay {total} visibles: se enviará en N tandas..."
    },
    {
      "id": "S2",
      "class": "documentation",
      "title": "Productos.jsx — results line, pageSize Todos, modal props",
      "publisher": "pricing-app worktree fix-markup-filtro",
      "url": "file:///home/user/.herdr/worktrees/pricing-app/fix-markup-filtro/frontend/src/pages/Productos.jsx",
      "accessed_at": "2026-09-04T15:31:32Z",
      "excerpt": "Mostrando {productos.length} de {totalProductos.toLocaleString('es-AR')} productos; <option value={9999}>Todos</option>; const productosOrdenados = productos; productos={productosOrdenados}; Acciones masivas button title: Acciones masivas sobre los productos visibles (markup ML y config de cuotas); pagination: (1 - ${pageSize} de ${totalProductos})"
    },
    {
      "id": "S3",
      "class": "documentation",
      "title": "useProductosData.js — listar page_size fills productos",
      "publisher": "pricing-app worktree fix-markup-filtro",
      "url": "file:///home/user/.herdr/worktrees/pricing-app/fix-markup-filtro/frontend/src/hooks/useProductosData.js",
      "accessed_at": "2026-09-04T15:31:32Z",
      "excerpt": "const params = { ...construirFiltrosParams(), page, page_size: pageSize }; ... setTotalProductos(productosRes.data.total || productosRes.data.productos.length); setProductos(productosRes.data.productos);"
    },
    {
      "id": "S4",
      "class": "documentation",
      "title": "useProductosFilters.js — default pageSize 50 and pagesize URL sync",
      "publisher": "pricing-app worktree fix-markup-filtro",
      "url": "file:///home/user/.herdr/worktrees/pricing-app/fix-markup-filtro/frontend/src/hooks/useProductosFilters.js",
      "accessed_at": "2026-09-04T15:31:32Z",
      "excerpt": "const [pageSize, setPageSize] = useState(50); if (pageSize !== 50) params.set('pagesize', pageSize.toString()); if (pagesizeParam) setPageSize(parseInt(pagesizeParam, 10)); construirFiltrosParams builds filter params without pagination."
    },
    {
      "id": "S5",
      "class": "documentation",
      "title": "exploration.md — prior explore notes on 18 vs ~4000",
      "publisher": "openspec change fix-markup-masivo-filtro",
      "url": "file:///home/user/.herdr/worktrees/pricing-app/fix-markup-filtro/openspec/changes/fix-markup-masivo-filtro/exploration.md",
      "accessed_at": "2026-09-04T15:31:32Z",
      "excerpt": "Symptom: grid showed 18 products, Acciones masivas showed ~4000+. Invariant: modal total === productos.length === first number in Mostrando X de Y. On 18 vs ~4000: 18 is either filtered totalProductos, marca-panel/stat cue, or misread — not a second fetch inside the modal."
    },
    {
      "id": "S6",
      "class": "open-web",
      "title": "PR #1242 — feat: acciones masivas de markup ML Clasica en Productos",
      "publisher": "GitHub sernafernando/pricing-app",
      "url": "https://github.com/sernafernando/pricing-app/pull/1242",
      "accessed_at": "2026-09-04T15:31:32Z",
      "excerpt": "PR body Risks: Opera sobre visibles en la grilla. Scope: El modal parte en tandas de 100 si hay mas visibles (caso Todos / pageSize 9999). Review (sernafernando approve note): El modal opera sobre productosOrdenados, o sea la página visible... cuando el usuario viene de pageSize chico es fácil creer que se aplicó a todo el filtro. Un contador del estilo \"100 de 3200 del filtro actual\" en el header del modal lo cerraría."
    }
  ],
  "validated_claims": [
    {
      "id": "C1",
      "question_ids": [
        "Q1"
      ],
      "claim": "The Acciones masivas modal product count is exactly `total = productos?.length ?? 0` from the `productos` prop. That value is interpolated into: header `Acciones masivas — {total} producto(s) visible(s)`; primary CTA `Aplicar a {total} producto(s)`; optional info `Hay {total} visibles: se enviará en {ceil(total/100)} tandas...`; empty toast `No hay productos en la vista actual`; and success toast for config-only uses the same `total`.",
      "source_ids": [
        "S1"
      ]
    },
    {
      "id": "C2",
      "question_ids": [
        "Q1"
      ],
      "claim": "Productos.jsx passes `productos={productosOrdenados}` and `productosOrdenados = productos` (identity). Therefore modal `total` equals the grid array length used by `Mostrando {productos.length} de {totalProductos...}` — i.e. the first number in that line, not `totalProductos` (the second number).",
      "source_ids": [
        "S1",
        "S2"
      ]
    },
    {
      "id": "C3",
      "question_ids": [
        "Q1"
      ],
      "claim": "`cargarProductos` sets both `productos` and `totalProductos` from one `productosAPI.listar` call with `{ ...construirFiltrosParams(), page, page_size: pageSize }`. Default `pageSize` is 50; the UI select offers 50/100/200/500 and `9999` labeled `Todos`. With `pageSize === 9999`, the loaded page buffer can hold thousands of rows, so modal `total` can be catalog-scale while still being \"current page buffer length\".",
      "source_ids": [
        "S2",
        "S3",
        "S4"
      ]
    },
    {
      "id": "C4",
      "question_ids": [
        "Q1"
      ],
      "claim": "Related UI strings that are NOT the modal count: results line `Mostrando {productos.length} de {totalProductos.toLocaleString('es-AR')} productos`; page-size label `Mostrar:` with option text `Todos` for value 9999; toolbar button label `Acciones masivas` and title `Acciones masivas sobre los productos visibles (markup ML y config de cuotas)`; pagination info `Página {page} (1 - ${pageSize} de ${totalProductos})` which uses configured `pageSize`, not `min(loaded,total)`. Modal info copy states it operates on visible grid products (current page and filters).",
      "source_ids": [
        "S1",
        "S2"
      ]
    },
    {
      "id": "C5",
      "question_ids": [
        "Q2"
      ],
      "claim": "PR #1242 body states the feature operates on products visible in the grid (`Opera sobre visibles en la grilla`) and explicitly ties multi-batch sending to the Todos / pageSize 9999 case (`tandas de 100 si hay mas visibles (caso Todos / pageSize 9999)`). It does not claim server-side resolution of the full filtered set.",
      "source_ids": [
        "S6"
      ]
    },
    {
      "id": "C6",
      "question_ids": [
        "Q2"
      ],
      "claim": "PR #1242 review commentary (sernafernando, post-fix approve note) states the modal operates on `productosOrdenados` — the visible page — and warns that with a small `pageSize` users may believe the action applied to the entire current filter. The suggested UX counterexample is a header like `100 de 3200 del filtro actual`, which treats page-visible count and filter-total as distinct.",
      "source_ids": [
        "S6"
      ]
    },
    {
      "id": "C7",
      "question_ids": [
        "Q3"
      ],
      "claim": "Documentation and PR evidence alone cannot determine which on-screen string displayed the number 18 in the reporter session. Code+PR prove modal count equals loaded `productos.length` (same as Mostrando X). Exploration records the symptom as grid 18 vs modal ~4000+, and hypothesizes 18 as expected filtered total / panel cue / misread, but no granted source quotes a screenshot or exact string containing 18. PR #1242 never mentions 18. Therefore the identity of the 18-bearing UI string remains uncertainty for orchestrator/user product discovery.",
      "source_ids": [
        "S1",
        "S2",
        "S5",
        "S6"
      ]
    }
  ],
  "contradictions": [
    {
      "id": "X1",
      "summary": "Reporter symptom (explore): grid showed 18 while modal showed ~4000+. Code invariant (S1+S2): modal total === productos.length === Mostrando X. Those cannot both be true for the same simultaneous render of the same `productos` array.",
      "source_ids": [
        "S1",
        "S2",
        "S5"
      ],
      "resolution": "Not resolved by granted evidence. Possible explanations (non-authoritative): reporter compared modal total to totalProductos/Y or another cue labeled 18; session had pageSize=Todos with wide list result (~4000) while expecting filtered 18; timing/state mismatch across observations. Requires product discovery confirmation."
    }
  ],
  "uncertainty": [
    {
      "id": "U1",
      "question_ids": [
        "Q3"
      ],
      "summary": "Which exact on-screen string showed \"18\" remains unknown under documentation/open-web grants alone.",
      "requires": "orchestrator_product_discovery_or_reporter_confirmation"
    },
    {
      "id": "U2",
      "question_ids": [
        "Q1",
        "Q3"
      ],
      "summary": "Reporter session pageSize value (50 vs 9999 Todos) and whether filters were present on the listar that filled `productos` are not attested by PR body/comments or code screenshots.",
      "requires": "orchestrator_product_discovery_or_reporter_confirmation"
    }
  ],
  "freshness": {
    "code_worktree": "fix-markup-filtro contemporaneous with change exploration 2026-09-04",
    "pr_1242": "merged 2026-09-04T14:20:56Z; body+timeline fetched 2026-09-04T15:31:32Z",
    "exploration": "written 2026-09-04; used as documentation grant, not as independent runtime proof beyond its cited code claims"
  },
  "product_choices": {
    "authoritative": false,
    "status": "pending",
    "notes": "Research does not select Approaches 1–4 from exploration. Scope bug class (page buffer item_ids vs filter-scoped siblings) is evidenced; preferred fix remains an orchestrator/product decision after confirming the 18-bearing string if needed."
  },
  "answers": {
    "Q1": "answered",
    "Q2": "answered",
    "Q3": "answered_as_uncertainty"
  },
  "executive_summary": "Modal count is productos.length (header/CTA/info), equal to Mostrando X and driven by listar page_size (incl. 9999 Todos). PR #1242 body and review state visible-page scope, not full filter set. The on-screen origin of reporter \"18\" cannot be fixed from docs/PR alone."
}