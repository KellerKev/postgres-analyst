# Spec: Cortex Local
**Tagline:** Snowflake Cortex Analyst — on your laptop, with Ollama and Postgres.  
**Purpose:** Blog post companion repo for kevinkeller.org. Must be jaw-dropping in a screenshot, runnable in 5 minutes, and understandable in 10.

---

## What It Does

Three-panel web app:
1. **Left — Schema Explorer:** Auto-introspect a connected Postgres DB. User can expand tables, toggle columns on/off, add semantic descriptions ("this is the customer's lifetime value in EUR"), mark columns as PII.
2. **Middle — Semantic Canvas:** A visual card-based view of the saved semantic model. Shows enriched tables and their "AI-visible" columns. User can drag to reorder, click to edit inline.
3. **Right — Chat:** Natural language → SQL → Results. User types a question, sees the generated SQL, approves or edits it, then sees results as a formatted table.

The **key insight** that makes this different from a tutorial: the semantic layer is the product. The LLM never sees raw schema — it only sees what the user has curated. That's exactly what Snowflake Cortex Analyst does with its YAML semantic model, but here it's visual and interactive.

---

## File Structure

```
cortex-local/
├── docker-compose.yml
├── init.sql                  # Metadata schema + demo data
├── backend/
│   ├── main.py               # FastAPI — single file, ~250 lines
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── vite.config.js
│   ├── package.json
│   └── src/
│       ├── main.jsx
│       ├── App.jsx           # Root layout, state, routing between panels
│       ├── SchemaExplorer.jsx
│       ├── SemanticCanvas.jsx
│       └── ChatPanel.jsx
└── README.md
```

No monorepo tooling. No TypeScript. Preact + Vite only.

---

## Stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | Preact + Vite | Lightweight React-compatible, fast HMR |
| Styling | Plain CSS with CSS variables | No Tailwind dep, blog readers can read it |
| Backend | FastAPI (Python) | Clean async, auto docs at /docs |
| Metadata DB | Postgres (same instance) | The whole point — Postgres stores the semantic layer |
| Target DB | Same Postgres instance (demo DB) | Simplest setup; README explains how to point at external |
| LLM | Ollama (`llama3.2` or `sqlcoder`) | Local, no API key needed |
| HTTP client | `httpx` (async) | Ollama API calls |

---

## Docker Compose

Three services:

### `postgres`
- Image: `postgres:16-alpine`
- Mount `init.sql` as `/docker-entrypoint-initdb.d/init.sql`
- Env: `POSTGRES_USER=cortex`, `POSTGRES_PASSWORD=cortex`, `POSTGRES_DB=cortexdb`
- Port: `5432:5432`
- Healthcheck on `pg_isready`

### `ollama`
- Image: `ollama/ollama:latest`
- Port: `11434:11434`
- Volume: `ollama_data:/root/.ollama` (persist downloaded models)
- After start, auto-pull `llama3.2` via entrypoint script:
  ```bash
  ollama serve & sleep 5 && ollama pull llama3.2 && wait
  ```

### `backend`
- Build from `./backend/Dockerfile` (simple Python 3.12 slim image)
- Env: `PG_DSN`, `OLLAMA_URL=http://ollama:11434`
- Port: `8000:8000`
- Depends on postgres + ollama healthchecks
- Command: `uvicorn main:app --host 0.0.0.0 --reload`

Frontend is **not containerized** — user runs `npm run dev` locally. This keeps the spec simple and HMR fast during demo.

---

## init.sql — Two Parts

### Part 1: Metadata Schema (cortex-local's own tables)

```sql
-- The saved semantic model — what the LLM sees
CREATE TABLE semantic_tables (
  id          SERIAL PRIMARY KEY,
  table_name  TEXT NOT NULL UNIQUE,
  description TEXT,                    -- "This table contains one row per customer"
  created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE semantic_columns (
  id            SERIAL PRIMARY KEY,
  table_id      INTEGER REFERENCES semantic_tables(id) ON DELETE CASCADE,
  column_name   TEXT NOT NULL,
  data_type     TEXT,
  description   TEXT,                  -- "Lifetime value in EUR, never null"
  is_pii        BOOLEAN DEFAULT false, -- hide from LLM context if true
  is_visible    BOOLEAN DEFAULT true,  -- user can toggle off irrelevant columns
  created_at    TIMESTAMPTZ DEFAULT now(),
  UNIQUE(table_id, column_name)
);

-- Query history
CREATE TABLE query_history (
  id          SERIAL PRIMARY KEY,
  question    TEXT NOT NULL,
  sql         TEXT NOT NULL,
  was_edited  BOOLEAN DEFAULT false,  -- did user modify the generated SQL?
  result_rows INTEGER,
  created_at  TIMESTAMPTZ DEFAULT now()
);
```

### Part 2: Demo Data (so the app works immediately)

Create a small realistic demo dataset — an e-commerce schema with 3 tables:

```sql
CREATE TABLE customers (
  id         SERIAL PRIMARY KEY,
  email      TEXT,                   -- PII
  full_name  TEXT,                   -- PII
  country    TEXT,
  ltv_eur    NUMERIC(10,2),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE orders (
  id          SERIAL PRIMARY KEY,
  customer_id INTEGER REFERENCES customers(id),
  total_eur   NUMERIC(10,2),
  status      TEXT,                  -- 'pending', 'shipped', 'returned'
  created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE products (
  id       SERIAL PRIMARY KEY,
  name     TEXT,
  category TEXT,
  price_eur NUMERIC(10,2)
);
```

Insert ~20 rows of realistic demo data across all three tables. Include a returned order, a high-LTV customer, multiple countries. This gives the LLM interesting queries to answer.

---

## Backend: main.py

### Endpoints

#### `GET /api/introspect`
Introspect the connected Postgres instance. Returns all user tables (excluding `pg_*`, `information_schema`, and the `semantic_*` / `query_history` metadata tables) with their columns and data types.

Query `information_schema.columns`. Return shape:
```json
{
  "tables": [
    {
      "table_name": "customers",
      "columns": [
        {"column_name": "id", "data_type": "integer"},
        {"column_name": "email", "data_type": "text"}
      ]
    }
  ]
}
```

#### `GET /api/semantic`
Return the full saved semantic model from `semantic_tables` + `semantic_columns` (JOIN). Return same shape as introspect but enriched with descriptions, PII flags, visibility.

#### `POST /api/semantic/save`
Upsert the full semantic model. Accept:
```json
{
  "tables": [
    {
      "table_name": "customers",
      "description": "One row per registered customer",
      "columns": [
        {
          "column_name": "email",
          "description": "Customer email address",
          "is_pii": true,
          "is_visible": false
        }
      ]
    }
  ]
}
```
Use `INSERT ... ON CONFLICT DO UPDATE` for both tables.

#### `POST /api/query`
The main endpoint. Accept:
```json
{"question": "Which country has the highest average order value?"}
```

Steps:
1. Load saved semantic model from DB (only `is_visible=true`, skip `is_pii=true` columns)
2. Build a compact schema prompt:
```
You are a SQL expert. Given this schema, write a single PostgreSQL SELECT query to answer the question.
Return ONLY the SQL query, no explanation, no markdown.

Schema:
Table: orders
  - customer_id (integer): Foreign key to customers
  - total_eur (numeric): Order total in EUR
  - status (text): One of pending, shipped, returned

Table: customers
  - country (text): ISO country code
  - ltv_eur (numeric): Customer lifetime value in EUR

Question: Which country has the highest average order value?
```
3. POST to Ollama `/api/generate` with model `llama3.2`, stream=false
4. Extract SQL from response (strip markdown fences if present)
5. Execute SQL against Postgres with a **5 second statement timeout** (`SET statement_timeout = '5s'`)
6. Return:
```json
{
  "sql": "SELECT c.country, AVG(o.total_eur)...",
  "columns": ["country", "avg_order_value"],
  "rows": [["NL", 142.50], ["DE", 98.20]],
  "row_count": 2
}
```
7. Save to `query_history`

**Error handling:** If Ollama returns unparseable SQL, return `{"error": "Could not parse SQL", "raw": "..."}` — never crash. If SQL execution fails, return `{"error": "SQL error", "sql": "...", "detail": "..."}` so the user can see and fix the query.

#### `GET /api/history`
Return last 20 rows from `query_history` ordered by `created_at DESC`.

---

## Frontend

### Aesthetic Direction
**Industrial data terminal.** Dark background (`#0d0d0f`), monospace accents for SQL and column names (`JetBrains Mono` or `IBM Plex Mono` from Google Fonts), clean sans-serif for UI chrome (`DM Sans`). Accent color: electric amber (`#f5a623`) — confident, readable, not the typical blue. Thin 1px borders. Tight spacing. Feels like a tool built by engineers for engineers, not a SaaS landing page.

No shadows. No rounded corners on data elements. SQL is displayed in a distinct code block with syntax highlighting (simple regex-based, no library needed).

### Layout
Three equal-width columns, full viewport height, no scroll on the outer container. Each panel scrolls internally.

```
┌─────────────────┬──────────────────┬─────────────────┐
│  SCHEMA         │  SEMANTIC MODEL  │  CHAT           │
│  EXPLORER       │                  │                 │
│                 │                  │                 │
│  [introspect]   │  [save model]    │  [question box] │
│                 │                  │                 │
│  ▼ customers    │  ┌─ customers ─┐ │  Q: Which...    │
│    id           │  │ One row per │ │                 │
│    email  [PII] │  │ customer    │ │  SELECT c...    │
│    full_name    │  │             │ │                 │
│    country  ✓   │  │  country ✓  │ │  ┌──────────┐  │
│    ltv_eur  ✓   │  │  ltv_eur ✓  │ │  │ NL  142  │  │
│                 │  └─────────────┘ │  │ DE   98  │  │
│  ▼ orders       │                  │  └──────────┘  │
│    ...          │  ┌─ orders ───┐  │                 │
└─────────────────┴──────────────────┴─────────────────┘
```

### App.jsx State
Top-level state managed in `App.jsx` with `useState`:
```javascript
const [introspected, setIntrospected] = useState([])   // raw schema from DB
const [semantic, setSemantic] = useState([])            // enriched model
const [dirty, setDirty] = useState(false)               // unsaved changes indicator
const [history, setHistory] = useState([])              // query history
```

Pass state and setters down as props — no context, no Redux. This is a demo, not a product.

### SchemaExplorer.jsx
- "Introspect Database" button at the top → calls `GET /api/introspect`
- Also calls `GET /api/semantic` on load to merge saved descriptions into the introspected schema
- Renders a collapsible list of tables
- Each column row shows: column name, data type, a PII toggle (🔴 when on), a visibility toggle (eye icon)
- Editing a description inline (click → contenteditable input) marks `dirty=true`
- Bottom: "Save Semantic Model" button (amber, disabled when not dirty) → calls `POST /api/semantic/save`

### SemanticCanvas.jsx
- Reads from `semantic` state (saved model only)
- Renders each table as a card with its description at the top
- Below the description: only `is_visible=true`, `is_pii=false` columns — exactly what the LLM sees
- PII columns shown as `████████` (redacted) with a lock icon
- Hidden columns shown faintly with strikethrough
- Refresh button to reload from API
- Empty state: "No semantic model saved yet. Use the Schema Explorer to add descriptions and save."

### ChatPanel.jsx
- Textarea for question input (Enter to submit, Shift+Enter for newline)
- On submit: POST to `/api/query`, show loading spinner
- Display generated SQL in a styled code block with a copy button
- SQL is **editable** — user can modify and re-run. If modified, `was_edited=true` in the history record.
- Results table: auto-sized columns, max 50 rows displayed, row count shown
- Error display: if SQL failed, show the error + the bad SQL so user can debug
- Below results: scrollable query history (collapsed by default, expandable)

---

## README.md

### Sections

**1. What is this?**
3 sentences. "Snowflake Cortex Analyst costs $X per query. This is the same idea — a visual semantic layer that lets you ask questions in plain English and get SQL results — running locally on Ollama and Postgres. No cloud. No API key. No per-query billing."

**2. Architecture diagram**
```
[Your Postgres DB]
       ↓ introspect
[Schema Explorer UI] → enrich with descriptions → [Semantic Layer in Postgres]
                                                            ↓ context
                                              [Ollama llama3.2] → SQL
                                                            ↓
                                              [Execute against Postgres]
                                                            ↓
                                              [Results Table in UI]
```

**3. Quick start**
```bash
git clone ...
cd cortex-local
docker compose up -d          # starts postgres + ollama (pulls llama3.2 ~2GB)

cd frontend
npm install && npm run dev    # http://localhost:5173

# In another terminal:
cd backend
pip install -r requirements.txt
uvicorn main:app --reload     # http://localhost:8000
```

**4. Point at your own database**
```bash
export PG_DSN="postgresql://user:pass@host:5432/mydb"
uvicorn main:app --reload
```

**5. The money shot**
Screenshot placeholder with caption: *"The LLM only sees what you curate. PII columns are invisible to the model."*

**6. Model swap**
One-liner: how to switch from `llama3.2` to `sqlcoder:7b` for better SQL quality.

---

## Constraints

- `agents.py` equivalent here is `main.py` — single file, raw SQL via `asyncpg`, no ORM
- No auth — this is a local demo, not a multi-tenant product
- No WebSockets — polling is fine for the demo, keep it simple
- Ollama must be in docker-compose but frontend dev server runs locally (not in docker)
- All Postgres queries in `main.py` use parameterized queries — readers will copy this code
- SQL syntax highlighting in ChatPanel: regex-based keyword highlighting only — no CodeMirror, no Prism

---

## Success Criteria

1. `docker compose up -d && npm run dev` works from a fresh clone in under 5 minutes
2. Introspecting the demo DB shows 3 tables immediately
3. Marking `email` and `full_name` as PII and saving — then asking "list all customers" — does NOT return emails or names in the result
4. Query history persists across page refresh
5. The UI looks like a tool someone would actually use, not a tutorial project
