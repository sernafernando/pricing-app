# Delta for backend/security-hardening

## ADDED Requirements

### Requirement: Dead ungated Tienda Nube endpoint removed or gated

`GET /tienda-nube/productos` (`tienda_nube.py:279`) MUST NOT remain reachable without
a permission check, and MUST NOT lack a `response_model`. It has zero current callers,
so it MUST be removed outright, or — if kept — gated identically to other TN admin
endpoints with an explicit `response_model` added.

#### Scenario: Endpoint is gone or gated

- GIVEN the current unauthenticated-reachable, response-model-less endpoint
- WHEN this change ships
- THEN either the route no longer exists, or it requires a permission check and returns a typed `response_model`

#### Scenario: No unauthenticated access remains

- GIVEN the endpoint still exists after this change
- WHEN an unauthenticated or unpermissioned client calls it
- THEN the response is `401` or `403`, never a `200` with unguarded data
