"""One-time helper kept for traceability: derive docs/diagrams/*.mmd from the project guide's Mermaid blocks,
adding what was built beyond the guide (application tables, the derived summary edge, the as-built flows)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
blocks = re.findall(r"```mermaid\n(.*?)```", (ROOT / "RITEN_GRAPH_Project_Guide.md").read_text(encoding="utf-8"), re.S)

er = blocks[0].rstrip() + '''

  subgraph APP_DOMAIN["Application accounts, curation and audit"]
    USER["APP_USER"]
    U_ID(["user_id PK"])
    U_NAME(["username"])
    U_HASH(["password_hash"])
    U_ROLE(["role"])
    USER --- U_ID
    USER --- U_NAME
    USER --- U_HASH
    USER --- U_ROLE
    NOTE["ANNOTATION"]
    N_ID(["annotation_id PK"])
    N_ENTITY(["entity_type, entity_key"])
    N_TEXT(["note"])
    NOTE --- N_ID
    NOTE --- N_ENTITY
    NOTE --- N_TEXT
    ALIAS["SUPPLIER_COMPANY_ALIAS"]
    AL_ID(["alias_id PK"])
    AL_EV(["evidence, confidence"])
    AL_ST(["status"])
    ALIAS --- AL_ID
    ALIAS --- AL_EV
    ALIAS --- AL_ST
    AUDIT["AUDIT_LOG"]
    AU_ID(["audit_id PK"])
    AU_OP(["table_name, operation, row_pk"])
    AU_ROW(["old_row, new_row"])
    AUDIT --- AU_ID
    AUDIT --- AU_OP
    AUDIT --- AU_ROW
    WRITES{"writes"}
    PROPOSES{"proposes"}
    REVIEWS{"reviews"}
    LABEL_OF{"candidate label"}
    COMPANY_OF{"candidate company"}
    USER ---|"1"| WRITES
    WRITES ---|"N"| NOTE
    USER ---|"1"| PROPOSES
    PROPOSES ---|"N"| ALIAS
    USER ---|"0..1"| REVIEWS
    REVIEWS ---|"N"| ALIAS
    SUP ---|"1"| LABEL_OF
    LABEL_OF ---|"N"| ALIAS
    COMPANY ---|"1"| COMPANY_OF
    COMPANY_OF ---|"N"| ALIAS
  end
'''
relational = blocks[1].rstrip() + '''
  USER["app_user\\nPK user_id\\nUNIQUE username"]
  NOTE["annotation\\nPK annotation_id\\nFK created_by"]
  ALIAS["supplier_company_alias\\nPK alias_id\\nFK supplier_label_id\\nFK company_key\\nFK proposed_by\\nFK reviewed_by\\nUNIQUE approved label"]
  AUDIT["audit_log\\nPK audit_id\\nwritten by triggers"]
  USER --> NOTE
  USER --> ALIAS
  SUP --> ALIAS
  COMPANY --> ALIAS
  NOTE -. "trigger" .-> AUDIT
  ALIAS -. "trigger" .-> AUDIT
'''
relational = relational.replace(chr(92) + "n", "<br/>")  # Mermaid line breaks, not literal backslash-n
graph = blocks[2].rstrip() + '''
  ACTOR -->|"TRADE_SUMMARY {year, value, volume, observations, controlled_observations, is_synthetic} derived per pair and year"| ACTOR2
'''
etl = '''flowchart TD
  FILES["Six source CSVs in data/"] --> CONTRACT["Contract check: filename, header, row and synthetic counts"]
  CONTRACT --> RAW["Raw staging tables, all text, with batch, file and row number"]
  REF["reference/actor_mapping.csv, reviewed actor codes"] --> RULES
  RAW --> RULES["Validation rules"]
  RULES -->|"any blocking error"| REJECT["Roll back the batch; record it as failed with row identifiers"]
  RULES -->|"caveats only"| REL["Normalized PostgreSQL tables, upserted in one transaction"]
  RULES --> CAVEATS["Disclosed caveats: etl_issue and DATA_QUALITY_REPORT.md"]
  REL --> RECON["Reconcile canonical counts and synthetic flags"]
  RECON --> GRAPH["Idempotent Neo4j projection with count check"]
  REL --> REPORTS["SQL views, functions and reports"]
  GRAPH --> TRAVERSALS["Graph paths and network aggregation"]
'''
architecture = '''flowchart LR
  BROWSER["Browser"] --> NEXT["Next.js: pages and /api proxy"]
  NEXT -->|"HTTP, session cookie"| API["FastAPI: one service with SQL, graph, curation and admin routers"]
  API -->|"app role: read facts, write curation data"| PG[("PostgreSQL: system of record")]
  API -->|"read-only traversals"| NEO[("Neo4j: graph projection")]
  API <-->|"cache-aside, optional"| CACHE[("Redis")]
  WORKER(["Prefetch worker, optional"]) -->|"reads events and candidate data"| PG
  WORKER -->|"reads candidate graph views"| NEO
  WORKER -->|"fills bounded entries"| CACHE
  ETL(["ETL, owner role"]) -->|"loads"| PG
  ETL -->|"projects"| NEO
'''
out = ROOT / "docs" / "diagrams"
out.mkdir(parents=True, exist_ok=True)
for name, text in (("ER_DIAGRAM", er), ("RELATIONAL_SCHEMA", relational), ("GRAPH_MODEL", graph), ("ETL_FLOW", etl), ("ARCHITECTURE", architecture)):
    (out / f"{name}.mmd").write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")
print("wrote", sorted(p.name for p in out.glob("*.mmd")))
