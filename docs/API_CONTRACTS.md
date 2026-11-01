# API contracts

Generated from the FastAPI schema by `python scripts/gen_docs.py`. Interactive docs are at `/docs` on the API.

Errors use `{"detail": ...}`. Status codes: 401 not signed in, 403 wrong role, 404 unknown record, 409 conflict, 422 invalid input, 503 a required database is down. Cached reads add an `X-Cache` header of HIT, MISS or BYPASS.

## Auth

| Method | Path | Parameters | Notes |
|---|---|---|---|
| POST | `/auth/login` |  |  |
| POST | `/auth/logout` |  |  |
| GET | `/auth/me` |  |  |

## Relational

| Method | Path | Parameters | Notes |
|---|---|---|---|
| GET | `/meta/filters` |  |  |
| GET | `/meta/provenance` |  |  |
| GET | `/trade` | `year_from`, `year_to`, `quarter`, `exporter`, `importer`, `hardware_type`, `category`, `route`, `controlled`, `include_synthetic`, `sort`, `direction`, `limit`, `offset` |  |
| GET | `/trade/summary` | `group_by`, `year_from`, `year_to`, `quarter`, `exporter`, `importer`, `hardware_type`, `category`, `route`, `controlled`, `include_synthetic` |  |
| GET | `/restrictions` | `year_from`, `year_to`, `imposer`, `target`, `restriction_type`, `technology`, `min_severity`, `q`, `include_synthetic`, `sort`, `direction`, `limit`, `offset` |  |
| GET | `/restrictions/summary` | `group_by`, `year_from`, `year_to`, `imposer`, `target`, `restriction_type`, `technology`, `min_severity`, `q`, `include_synthetic` |  |
| GET | `/infrastructure/compare` | `year`, `include_synthetic` |  |
| GET | `/infrastructure/trend` | `metric`, `codes`, `include_synthetic` |  |
| GET | `/actors/{code}/profile` | `code`, `include_synthetic` |  |
| GET | `/companies` | `hq`, `domain`, `sanction_risk`, `exposure`, `year`, `include_synthetic`, `q`, `limit`, `offset` |  |
| GET | `/companies/{company_key}` | `company_key` |  |
| GET | `/reports/top-links` | `year`, `hardware_type`, `include_synthetic`, `limit` | Directed links ranked by value, with each link's share of the year and of its exporter's total. |
| GET | `/reports/restriction-targets` | `year_from`, `year_to`, `min_measures`, `include_synthetic` |  |
| GET | `/reports/grid-pressure` | `year`, `include_synthetic` | Countries whose AI grid stress is above that year's average, with AI investment for comparison. |
| GET | `/reports/hardware-controls` | `year_from`, `year_to`, `include_synthetic` | Hardware types with at least one controlled observation (uses the partial index). |
| GET | `/reports/mutual-restrictions` | `include_synthetic`, `limit` | Pairs of actors that have each imposed measures on the other (a self-join). |
| GET | `/reports/company-risk` | `year`, `include_synthetic` | Flagged companies with the restrictions their headquarters country received that year. |

## Graph

| Method | Path | Parameters | Notes |
|---|---|---|---|
| GET | `/graph/neighborhood/{code}` | `code`, `year`, `include_synthetic` |  |
| GET | `/graph/paths` | `source`, `target`, `year`, `max_hops`, `include_synthetic`, `limit` | Directed trade paths over the yearly summary edges, ranked by the weakest hop's value. |
| GET | `/graph/reroutes` | `source`, `target`, `year`, `include_synthetic` | If source-to-target trade is restricted, which single intermediaries exist, and are their hops restricted too? |
| GET | `/graph/network` | `year`, `include_synthetic` | Whole-network aggregation in Cypher: weighted degree, partner count and broker position per actor. |
| GET | `/graph/edges` | `source`, `target`, `year`, `include_synthetic`, `limit` | Row-level edges between two actors, with every edge property visible. |

## Curation

| Method | Path | Parameters | Notes |
|---|---|---|---|
| GET | `/annotations` | `entity_type`, `entity_key`, `mine`, `limit`, `offset` |  |
| POST | `/annotations` |  |  |
| PATCH | `/annotations/{annotation_id}` | `annotation_id` |  |
| DELETE | `/annotations/{annotation_id}` | `annotation_id` |  |
| GET | `/aliases` | `status`, `limit`, `offset` |  |
| POST | `/aliases` |  |  |
| GET | `/aliases/unlinked-labels` |  | Supplier labels with no approved company, largest trade value first (anti-join with an aggregate). |
| POST | `/aliases/review` |  | All-or-nothing: one invalid id or a self-review rolls back the whole batch. |
| DELETE | `/aliases/{alias_id}` | `alias_id` |  |
| GET | `/reports/company-supplier-trade` | `year` |  |
| POST | `/events/navigation` |  | Stores no user identity. A replayed client_event_id is ignored. |

## Admin

| Method | Path | Parameters | Notes |
|---|---|---|---|
| GET | `/admin/import-batches` |  |  |
| GET | `/admin/data-quality` | `batch_id`, `limit`, `offset` |  |
| GET | `/admin/audit-log` | `table_name`, `limit`, `offset` |  |
| GET | `/admin/users` |  |  |
| POST | `/admin/users` |  |  |
| PATCH | `/admin/users/{user_id}` | `user_id` |  |
| GET | `/admin/reconciliation` |  | Row counts across PostgreSQL and Neo4j, compared with the audited expectations. |
| POST | `/admin/graph/sync` |  | Rebuild the projection from PostgreSQL. Idempotent; the graph has no independent writes. |
| GET | `/admin/metrics` |  |  |

## Health

| Method | Path | Parameters | Notes |
|---|---|---|---|
| GET | `/health/live` |  |  |
| GET | `/health/ready` |  | Ready means both required databases answer. Redis is optional and only reported. |
