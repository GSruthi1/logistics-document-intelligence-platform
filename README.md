# Logistics Document Intelligence Platform (LDIP)

Extracts structured data from freight documents (Bills of Lading, Proofs of
Delivery, Freight Invoices) using a multimodal LLM, scores per-field
confidence, validates against configurable business rules, and routes only
the documents that actually need a human to a review queue — with a full
audit trail of every extraction, validation, and correction.

Built as a production-shaped portfolio project: FastAPI, PostgreSQL with
Alembic migrations, Docker + docker-compose, a pytest suite (unit +
integration) running in CI, and a benchmark comparing LLM extraction against
a pytesseract OCR baseline on 100 synthetic documents.

**Live:** [ldip-production.up.railway.app](https://ldip-production.up.railway.app) &middot; interactive API docs at [`/docs`](https://ldip-production.up.railway.app/docs) &middot; try it: `GET /queue`, or `POST /extract` with a PDF/image + `doc_type`

## Results, up front

Measured on the same 100 synthetic documents (not two different samples —
see [Benchmark results](#benchmark-results) for methodology):

| | Field accuracy | Errors |
|---|---|---|
| **pytesseract OCR baseline** | 67.1% | 0 |
| **Claude Sonnet 5 (multimodal LLM)** | **100.0%** | 0 |

The gap isn't "LLMs are smarter" in the abstract — it's specific and
measured: OCR accuracy drops from **82.5% → 43.1%** on documents that phrase
the same fields with different label wording (e.g. "Shipper" vs "Ship
From"), because keyword-matching breaks when the keyword changes. The LLM
holds **100% → 100%** across the same split, because it extracts by meaning,
not label text. Under the pipeline's real confidence/validation routing
logic, that accuracy translates to **60% of documents skipping human review
entirely** — a reviewer only ever sees the fraction the system is actually
unsure about.

## The problem this solves

Freight companies process thousands of BOLs, PODs, and invoices a day.
They're semi-structured — the same handful of fields (shipper, consignee,
PRO number, weight, charges) — but every carrier formats them differently.
Traditional OCR reads *characters*, not *fields*: it can't tell "consignee"
from "shipper" when the layout shifts, so extracting structured data from OCR
output means building brittle keyword/regex heuristics that break on the
next carrier's paperwork. Manual data entry doesn't scale. A multimodal LLM
reads for *meaning*, not layout position, so it survives exactly the kind of
formatting variation that breaks OCR-based extraction — see
[Benchmark results](#benchmark-results) below for a measured comparison, not
an assumed one.

## Pipeline

```
1. INGEST      POST /extract -> file hashed + stored, Document row created
       │
2. EXTRACT     Multimodal LLM (Claude/GPT-4o) reads the image/PDF, returns
       │       each field as {value, self_reported_confidence} via native
       │       structured output (tool use / function calling) — never
       │       free-text JSON parsing.
       │
3. SCORE       ConfidenceScorer recomputes confidence on top of the model's
       │       own number: penalizes format mismatches (bad date/currency
       │       shape), zeroes out missing required fields. This is what
       │       routing actually uses, not the raw model confidence.
       │
4. VALIDATE    RulesEngine runs business rules loaded from a YAML config
       │       (app/validation/rules_config.yaml) — required fields, date
       │       ordering, sanity bounds, allowed values. Config change, not
       │       a code change, to add/tune a rule.
       │
5. ROUTE       All fields >= confidence threshold AND all rules pass ->
       │       auto-approved. Otherwise -> HITL queue, with a
       │       machine-generated reason ("2 fields below threshold: ...").
       │            ┌──────────────┴──────────────┐
       │      AUTO-APPROVED                   HITL QUEUE
       │                                            │
6. REVIEW      (done)                    GET /queue -> reviewer sees flagged
       │                                 fields -> PATCH /queue/{id}/correct
       │
7. AUDIT       Every extraction, score, validation, routing decision, and
               human correction is an immutable row in audit_log — who
               changed what, from what, to what, when.
```

## Architecture

```
                         ┌─────────────────────────────────────────┐
                         │              FastAPI app                 │
                         │  POST /extract   GET/PATCH /queue/*       │
                         └───────────────┬───────────────────────────┘
                                          │
                         ┌────────────────▼────────────────┐
                         │        DocumentService            │  <- orchestrator only;
                         │   (app/services/document_service)  │     no business logic lives here
                         └───┬────────┬────────┬────────┬───┘
                             │        │        │        │
                  ┌──────────▼─┐ ┌────▼─────┐ ┌▼────────────┐ ┌▼──────────────┐
                  │ Extractor  │ │Confidence│ │ RulesEngine  │ │ HitlService    │
                  │(interface) │ │Scorer    │ │(YAML-driven) │ │ (queue + audit)│
                  ├────────────┤ └──────────┘ └──────────────┘ └────────────────┘
                  │LLMExtractor│
                  │OCRExtractor│  <- benchmark-only baseline, not used in live routing
                  └────────────┘
                                          │
                         ┌────────────────▼────────────────┐
                         │         PostgreSQL                │
                         │ documents, extracted_fields,      │
                         │ validation_results, hitl_queue_    │
                         │ items, corrections, audit_log      │
                         └───────────────────────────────────┘
```

Every arrow above is an abstract interface, not a concrete import —
`DocumentService` depends on `Extractor`, `FileStorage`, `RulesEngine` as
types, never on `LLMExtractor` or `LocalFileStorage` directly. Swapping
Claude for GPT-4o, or local disk for Azure Blob, is a one-line change in
`app/api/deps.py`; nothing else in the pipeline knows or cares.

## Repo structure

```
app/
  core/         settings (pydantic-settings), logging
  db/           SQLAlchemy engine/session, declarative Base
  models/       ORM models — one file per table
  schemas/      Pydantic request/response models
  extraction/   Extractor interface + LLMExtractor + OCRExtractor + field schemas + prompts
  scoring/      ConfidenceScorer
  validation/   RulesEngine + rules_config.yaml (the configurable business rules)
  queue/        HitlService (enqueue / list / correct)
  services/     DocumentService (orchestrator), AuditService
  storage/      FileStorage interface + Local/AzureBlob implementations
  api/          FastAPI routes + dependency wiring
alembic/        DB migrations
tests/
  unit/         no DB, no HTTP — pure logic (scorer, rules engine, OCR heuristics)
  integration/  real Postgres + FastAPI TestClient + a fake LLM extractor
benchmark/      synthetic document generator + LLM-vs-OCR accuracy benchmark
docker/         Dockerfile + entrypoint (runs migrations, then starts uvicorn)
```

## Running it locally

```bash
git clone <this repo> && cd LDIP
cp .env.example .env        # then fill in ANTHROPIC_API_KEY or OPENAI_API_KEY
docker compose up --build
```

That builds the image, starts Postgres with a healthcheck gate, runs Alembic
migrations automatically on boot, and serves the API at `http://localhost:8000`
(interactive docs at `/docs`).

For local development without Docker:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
docker run -d -p 5432:5432 -e POSTGRES_USER=ldip -e POSTGRES_PASSWORD=ldip -e POSTGRES_DB=ldip postgres:16-alpine
alembic upgrade head
uvicorn app.main:app --reload
```

## API

| Endpoint | Description |
|---|---|
| `POST /extract` | multipart upload (`file`, `doc_type`) — runs the full pipeline, returns extracted fields + validation results + routing decision |
| `GET /queue` | list HITL queue items (filter by `status`, paginate with `limit`/`offset`) |
| `GET /queue/{id}` | one queue item's full detail (fields, validation errors) |
| `PATCH /queue/{id}/correct` | submit one or more field corrections; resolves the queue item |
| `GET /health` | liveness + DB connectivity check |

```bash
curl -X POST http://localhost:8000/extract \
  -F "file=@sample_bol.pdf" \
  -F "doc_type=bill_of_lading"
```

`doc_type` must be one of `bill_of_lading`, `proof_of_delivery`,
`freight_invoice` (see `app/extraction/field_schema.py` to add a new type).

## Testing

```bash
pytest --cov=app --cov-report=term-missing
```

32 tests, ~88% coverage. Unit tests cover `ConfidenceScorer`, `RulesEngine`
(including a real, unmocked pytesseract run), and the YAML rule loader with
no DB or HTTP involved. Integration tests exercise the full pipeline through
a real `TestClient` + real Postgres, with a fake `Extractor` standing in for
the paid LLM API — including the duplicate-upload dedup path, the
low-confidence and validation-error HITL routing paths, and the full
correct-and-resolve queue flow with audit-trail verification.

CI (`.github/workflows/ci.yml`) runs `ruff`, an `alembic upgrade head`
sanity check, the full test suite against a real Postgres service
container, and a Docker build — on every push/PR to `main`.

## Benchmark results

100 synthetic documents were generated with Faker (realistic field values)
and Jinja2 (two different "carrier profile" templates per document type —
different label wording and layout, e.g. "Shipper" vs "Ship From", table vs
stacked layout — simulating how two real carriers' paperwork actually
differs). See `benchmark/carrier_profiles.py` for the exact label mapping
and `benchmark/generate_synthetic_docs.py` for generation.

| Method | Overall accuracy | "standard" profile | "altcarrier" profile | Sample | Errors |
|---|---|---|---|---|---|
| pytesseract OCR baseline | **67.1%** | 82.5% | 43.1% | 100 docs | 0 |
| Claude Sonnet 5 (multimodal) | **100.0%** | 100.0% | 100.0% | 100 docs | 0 |

Both methods were run against the identical 100-document set (869 fields
graded for the LLM run) so the comparison is apples-to-apples, not two
different samples. Both runs are reproducible:
`python -m benchmark.generate_synthetic_docs --seed 42` then
`python -m benchmark.run_benchmark --methods ocr` (free, local) or
`--methods llm` (calls a paid API — the LLM run here was split into two
batches via `--offset`, so a partial run's cost never has to be re-paid when
extending it to the full set). Full results in
[`benchmark/results/benchmark_results.json`](benchmark/results/benchmark_results.json).

**Why the profile breakdown matters more than the headline number:** the OCR
baseline doesn't fail because tesseract reads characters badly — it fails
because turning "characters on a page" into "this is the consignee_name
field" requires guessing at label text (`app/extraction/ocr_extractor.py`'s
`FIELD_LABEL_ALIASES`), and that guess breaks the moment a document phrases
a label differently than expected (43.1% vs 82.5% is that failure, measured
directly). The LLM doesn't do keyword matching — it's asked to identify
"the receiving party" semantically, so relabeling doesn't fool it.

**Honest caveat, worth saying out loud in an interview:** 100% on the LLM
side reflects that these are clean, computer-rendered synthetic PDFs, not
scanned, photographed, or handwritten real-world documents — a production
deployment would see some error rate from image quality alone. The
*mechanism* the benchmark demonstrates (semantic extraction survives layout
variation that breaks keyword-based OCR extraction) is the real, generalizable
finding; the exact accuracy numbers are specific to this synthetic set.

The HITL routing side of the benchmark (using the exact `ConfidenceScorer` +
`RulesEngine` the live API uses, not a separate calculation) showed **60% of
documents would skip human review entirely** across the full 100-document
LLM run — i.e., a reviewer only ever sees the ~40% of documents the pipeline
is actually unsure about, not all of them.

## Deployment

### Azure App Service (container deployment)

```bash
az group create --name ldip-rg --location eastus
az postgres flexible-server create --resource-group ldip-rg --name ldip-pg \
  --admin-user ldip --admin-password '<strong-password>' --sku-name Standard_B1ms
az acr create --resource-group ldip-rg --name ldipacr --sku Basic
az acr build --registry ldipacr --image ldip-app:latest -f docker/Dockerfile .
az appservice plan create --name ldip-plan --resource-group ldip-rg --is-linux --sku B1
az webapp create --resource-group ldip-rg --plan ldip-plan --name ldip-app \
  --deployment-container-image-name ldipacr.azurecr.io/ldip-app:latest
az webapp config appsettings set --resource-group ldip-rg --name ldip-app --settings \
  DATABASE_URL="postgresql+psycopg2://ldip:<password>@ldip-pg.postgres.database.azure.com:5432/ldip" \
  ANTHROPIC_API_KEY="<key>" LLM_PROVIDER=anthropic STORAGE_BACKEND=azure_blob \
  AZURE_STORAGE_CONNECTION_STRING="<connection-string>"
```

The entrypoint script runs Alembic migrations on container start, so a fresh
App Service deploy against a fresh Postgres Flexible Server just works —
no manual migration step.

### Railway.app (this is what's actually running at the live URL above)

`railway.json` at the repo root points Railway at `docker/Dockerfile`
explicitly (Railway's default auto-detection looks for a root-level
`Dockerfile`, which this repo intentionally doesn't have — `docker/` keeps
container-specific files out of the project root). Steps: create a project,
add a Postgres database (Railway provisions one and exposes `DATABASE_URL`
+ `PGHOST`/`PGPASSWORD`/etc. automatically), add an empty service for the
app, set `DATABASE_URL` on the app service to the Postgres service's URL
with the scheme remapped to `postgresql+psycopg2://` (SQLAlchemy's driver
prefix, not Railway's default `postgresql://`), set
`ANTHROPIC_API_KEY`/`OPENAI_API_KEY` + `LLM_PROVIDER`, generate a domain
(`railway domain --port 8000`), deploy (`railway up`). The same
`entrypoint.sh` used locally and in `docker-compose.yml` runs Alembic
migrations on container start there too — one migration path for every
environment.

**Two real deploy-time bugs, worth knowing about if you hit them elsewhere:**

1. **Healthcheck failed with no application error anywhere in the logs.**
   The container logs showed migrations succeeding and uvicorn listening
   fine — but Railway's healthcheck prober couldn't reach it, over and over,
   until a domain (`railway domain --port <port>`) was created for the
   service. Without an explicit target port, Railway had nothing to route
   the healthcheck to, even though the app itself was healthy the entire
   time. Lesson: "the app looks fine in the logs" and "the platform can
   reach the app" are different claims — verify both.
2. **`TypeError: Client.__init__() got an unexpected keyword argument
   'proxies'`** on the very first live `/extract` call, despite dozens of
   successful local benchmark calls against the same code. Root cause:
   `requirements.txt` pinned `anthropic==0.34.2` but never pinned `httpx`
   (a transitive dependency) — locally, `requirements-dev.txt`'s own
   `httpx==0.27.2` pin happened to win dependency resolution, masking the
   problem; Railway's image only installs `requirements.txt`, where pip
   resolved the newest `httpx` (0.28.1), which dropped a kwarg
   `anthropic==0.34.2` still unconditionally passes internally. Fixed by
   pinning `httpx==0.27.2` directly in `requirements.txt`. Lesson: an
   unpinned transitive dependency can resolve differently in dev vs. prod
   even when every *direct* dependency is pinned — "pip install worked
   locally" doesn't mean the production install will resolve the same
   graph.

## Key design decisions (for the "why did you build it this way" conversation)

- **CHECK constraints, not native Postgres ENUMs**, for `status`/`doc_type`
  columns — adding a new status value later is a one-line migration, not an
  `ALTER TYPE ... ADD VALUE` that can't run in a transaction.
- **EAV-shaped `extracted_fields` table** (one row per field, not one wide
  column per field) — BOLs, PODs, and invoices have different field sets,
  and new document types are a registry entry in `field_schema.py`, not a
  schema migration.
- **Business rules in YAML, not Python `if` statements** — a client's ops
  team changing "max weight 80,000 lbs" to 60,000 should be a config edit,
  not a pull request.
- **Structured output (tool use / function calling), never free-text JSON
  parsing** from the LLM — schema conformance is enforced by the provider,
  not by hoping the model didn't wrap its answer in a markdown fence.
- **Confidence is recomputed, not trusted** — LLM self-reported confidence
  is a signal, not a probability; `ConfidenceScorer` penalizes format
  mismatches and zeroes out missing required fields independently of what
  the model claims.
- **Append-only `corrections` + `audit_log`**, never in-place updates to a
  "what happened" record — six months later, "why did the system do X" has
  to be answerable.
- **Content-hash deduplication** on upload — a duplicate PDF doesn't trigger
  a second paid LLM call.
