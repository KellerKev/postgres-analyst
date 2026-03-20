# Postgres Analyst

**Ask your Postgres database questions in plain English. Get SQL back. No cloud, no API keys, no per-query billing.**

This is a local, open-source alternative to tools like [Snowflake Cortex Analyst](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst). It connects to any Postgres database, lets you build a visual **semantic layer** on top of your schema, and uses a local LLM (via [Ollama](https://ollama.com)) to translate natural language questions into SQL queries.

```
[Your Postgres DB]
       | introspect
[Schema Explorer] --> auto-describe + enrich --> [Semantic Model in Postgres]
                                                          | context
                                                [Ollama LLM] --> SQL
                                                          |
                                                [Execute against Postgres]
                                                          |
                                                [Results in UI]
```

## What you'll learn

This project demonstrates a pattern that's becoming central to how companies build AI-powered data tools:

- **Semantic layers** — Why raw schema isn't enough for LLMs, and how a curated layer of descriptions, PII flags, and visibility controls makes the difference between a useful query and `column customers.name does not exist`.
- **LLM-as-SQL-compiler** — The LLM doesn't need to be perfect on the first try. With the right schema context, foreign key hints, and auto-retry on errors, even a small local model (8B params) can reliably generate correct SQL.
- **Multiple semantic models** — One database, many views. A "Sales Dashboard" model exposes different tables and columns than a "Support Tool" model. Each model is a curated lens for a different use case or team.
- **PII-aware AI** — Columns marked as PII are visible to the LLM for JOINs but excluded from SELECT output by default. The model knows `full_name` exists without leaking it in every query.

## Features

- **Three-panel UI** — Schema Explorer | Semantic Canvas | Chat
- **Auto-describe** — One click to have the LLM generate descriptions, detect PII, and suggest visibility for every table and column
- **Multiple semantic models** — Create named models ("Sales App", "Support Dashboard") with different column selections and descriptions
- **Editable SQL** — Review the generated SQL, modify it, and re-run
- **Auto-retry** — If generated SQL fails, the error is fed back to the LLM to self-correct
- **Query history** — Every query is logged with its question, SQL, and result count
- **PII protection** — Mark columns as PII; the LLM sees them for context but avoids selecting them
- **Works with any Postgres database** — Ships with a demo e-commerce dataset, but point it at your own DB with one env var

## Quick start

### Prerequisites

- [pixi](https://pixi.sh) (manages Python, Node, and Postgres — no system installs needed)
- [Ollama](https://ollama.com) running with a model pulled (e.g., `ollama pull qwen3:8b`)

### Setup

```bash
git clone <this-repo>
cd postgres-analyst

# One-time setup: initializes Postgres, creates DB, seeds demo data
pixi run setup-db
pixi run install-frontend
```

### Run

Open two terminals:

```bash
# Terminal 1: Backend (FastAPI on port 8000)
pixi run backend

# Terminal 2: Frontend (Vite on port 5173)
pixi run frontend
```

Open **http://localhost:5173**.

### Use it

1. Click **Introspect** to discover your database tables
2. Click **Auto-describe** to have the LLM generate descriptions and detect PII
3. Review the suggestions, tweak as needed
4. Click **Save Semantic Model**
5. Switch to the Chat panel and ask questions in plain English

### Point at your own database

```bash
export PG_DSN="postgresql://user:pass@host:5432/mydb"
pixi run backend
```

Introspect will discover your tables. Auto-describe will generate descriptions from your actual schema and sample data.

### Switch LLM model

```bash
export OLLAMA_MODEL="llama3.2"   # or sqlcoder:7b, mistral, etc.
pixi run backend
```

Any Ollama-compatible model works. Larger models produce better SQL but are slower.

## Stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | Preact + Vite | Lightweight, fast HMR, React-compatible |
| Backend | FastAPI (Python) | Async, clean, auto-docs at `/docs` |
| Database | Postgres (via pixi) | Stores both the semantic layer and your data |
| LLM | Ollama (local) | No API key, no cloud, runs on your hardware |

## Project structure

```
postgres-analyst/
  backend/
    main.py            # FastAPI — all endpoints in one file
  frontend/
    src/
      App.jsx            # Root layout, model selector, state management
      SchemaExplorer.jsx # Introspect DB, edit descriptions, toggle PII
      SemanticCanvas.jsx # Visual view of the curated semantic model
      ChatPanel.jsx      # Natural language -> SQL -> results
      style.css          # Dark terminal aesthetic, no CSS framework
  init.sql               # Metadata schema + demo e-commerce data
  pyproject.toml         # pixi config, Python deps, task definitions
```

## API

| Endpoint | Method | Description |
|---|---|---|
| `/api/models` | GET | List semantic models |
| `/api/models` | POST | Create a semantic model |
| `/api/models/{id}` | PUT | Update model name/description |
| `/api/models/{id}` | DELETE | Delete model (cascades) |
| `/api/introspect` | GET | Discover tables and columns from Postgres |
| `/api/introspect/describe` | POST | LLM auto-generates descriptions + PII flags |
| `/api/semantic?model_id=X` | GET | Get the semantic model |
| `/api/semantic/save` | POST | Save/update the semantic model |
| `/api/query` | POST | Ask a question, get SQL + results |
| `/api/history` | GET | Last 20 queries |

Full OpenAPI docs available at `http://localhost:8000/docs` when the backend is running.

## Use cases

- **Internal data tools** — Build natural-language query interfaces for non-technical teams without exposing raw database access
- **Data catalogs** — Auto-describe your schema and maintain a living semantic layer alongside your database
- **Multi-tenant analytics** — Create different semantic models for different teams, each with appropriate access controls
- **Prototyping** — Test whether a semantic layer + LLM approach works for your data before investing in commercial tools
- **Learning** — Understand how Snowflake Cortex Analyst, dbt semantic layer, and similar products work under the hood

## License

MIT
