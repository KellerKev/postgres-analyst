import os
import re
import json
from contextlib import asynccontextmanager

import asyncpg
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

PG_DSN = os.getenv("PG_DSN", "postgresql://cortex@localhost:5434/cortexdb")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")

pool: asyncpg.Pool | None = None

METADATA_TABLES = {"semantic_models", "semantic_tables", "semantic_columns", "query_history"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = await asyncpg.create_pool(PG_DSN, min_size=2, max_size=10)
    yield
    await pool.close()


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Pydantic Models ----------

class SemanticColumn(BaseModel):
    column_name: str
    description: str | None = None
    data_type: str | None = None
    is_pii: bool = False
    is_visible: bool = True


class SemanticTable(BaseModel):
    table_name: str
    description: str | None = None
    columns: list[SemanticColumn] = []


class SemanticSaveRequest(BaseModel):
    model_id: int
    tables: list[SemanticTable]


class QueryRequest(BaseModel):
    question: str
    model_id: int | None = None
    sql: str | None = None
    was_edited: bool = False
    accept_without_pii: bool = False


class ModelCreate(BaseModel):
    name: str
    description: str | None = None


class ModelUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


# ---------- Model CRUD ----------

@app.get("/api/models")
async def list_models():
    rows = await pool.fetch("""
        SELECT id, name, description, created_at
        FROM semantic_models
        ORDER BY created_at
    """)
    return {"models": [dict(r) for r in rows]}


@app.post("/api/models")
async def create_model(req: ModelCreate):
    row = await pool.fetchrow("""
        INSERT INTO semantic_models (name, description)
        VALUES ($1, $2)
        RETURNING id, name, description
    """, req.name, req.description)
    return dict(row)


@app.put("/api/models/{model_id}")
async def update_model(model_id: int, req: ModelUpdate):
    await pool.execute("""
        UPDATE semantic_models
        SET name = COALESCE($2, name), description = COALESCE($3, description)
        WHERE id = $1
    """, model_id, req.name, req.description)
    return {"status": "updated"}


@app.delete("/api/models/{model_id}")
async def delete_model(model_id: int):
    await pool.execute("DELETE FROM semantic_models WHERE id = $1", model_id)
    return {"status": "deleted"}


# ---------- Endpoints ----------

@app.get("/api/introspect")
async def introspect():
    rows = await pool.fetch("""
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
    """)
    tables: dict[str, list] = {}
    for r in rows:
        if r["table_name"] in METADATA_TABLES:
            continue
        tables.setdefault(r["table_name"], []).append({
            "column_name": r["column_name"],
            "data_type": r["data_type"],
        })
    return {
        "tables": [
            {"table_name": t, "columns": cols}
            for t, cols in tables.items()
        ]
    }


@app.post("/api/introspect/describe")
async def auto_describe():
    """Use LLM to auto-generate descriptions, detect PII, and suggest visibility."""
    intro = await introspect()
    tables = intro["tables"]
    if not tables:
        return {"tables": []}

    # Also fetch sample data for better descriptions
    samples = {}
    for tbl in tables:
        try:
            rows = await pool.fetch(
                f'SELECT * FROM "{tbl["table_name"]}" LIMIT 3'
            )
            samples[tbl["table_name"]] = [
                {k: str(v) for k, v in dict(r).items()} for r in rows
            ]
        except Exception:
            samples[tbl["table_name"]] = []

    # Also fetch foreign keys
    fk_rows = await pool.fetch("""
        SELECT
            tc.table_name, kcu.column_name,
            ccu.table_name AS foreign_table, ccu.column_name AS foreign_column
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
        JOIN information_schema.constraint_column_usage ccu
            ON tc.constraint_name = ccu.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'
    """)
    fk_map: dict[str, dict[str, str]] = {}
    for fk in fk_rows:
        fk_map.setdefault(fk["table_name"], {})[fk["column_name"]] = (
            f"FK -> {fk['foreign_table']}.{fk['foreign_column']}"
        )

    schema_text = ""
    for tbl in tables:
        tn = tbl["table_name"]
        schema_text += f"Table: {tn}\n"
        for col in tbl["columns"]:
            fk_info = fk_map.get(tn, {}).get(col["column_name"], "")
            fk_suffix = f" ({fk_info})" if fk_info else ""
            schema_text += f"  - {col['column_name']} ({col['data_type']}){fk_suffix}\n"
        if samples.get(tn):
            schema_text += f"  Sample rows: {json.dumps(samples[tn][:2], default=str)}\n"
        schema_text += "\n"

    prompt = (
        "You are a data analyst. Given this database schema with sample data, "
        "generate a JSON description for each table and column.\n\n"
        "For each table, provide:\n"
        '- "description": one-sentence description of what the table contains\n'
        "For each column, provide:\n"
        '- "description": short description of the column\'s meaning\n'
        '- "is_pii": true if the column contains personally identifiable information '
        "(emails, names, phone numbers, addresses, SSNs, etc.)\n"
        '- "is_visible": true for most columns, false for internal/technical columns '
        "(like auto-increment IDs, created_at timestamps, internal FKs that aren't "
        "useful for analytics)\n\n"
        "Return ONLY valid JSON, no explanation. Format:\n"
        "```json\n"
        '{"tables": [{"table_name": "...", "description": "...", "columns": '
        '[{"column_name": "...", "description": "...", "is_pii": false, "is_visible": true}]}]}\n'
        "```\n\n"
        f"Schema:\n{schema_text}"
    )

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "")
    except Exception as e:
        return {"error": f"Ollama error: {e}"}

    # Parse JSON from response
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    # Some models add thinking tags
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL).strip()

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to find JSON in the response
        match = re.search(r'\{.*"tables".*\}', cleaned, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group())
            except json.JSONDecodeError:
                return {"error": "Could not parse LLM response", "raw": raw}
        else:
            return {"error": "Could not parse LLM response", "raw": raw}

    # Merge LLM descriptions back onto the introspected schema (preserve data_type)
    described = []
    for tbl in tables:
        llm_tbl = next(
            (t for t in result.get("tables", [])
             if isinstance(t, dict) and t.get("table_name") == tbl["table_name"]),
            {},
        )
        cols = []
        for col in tbl["columns"]:
            llm_col = next(
                (c for c in llm_tbl.get("columns", [])
                 if isinstance(c, dict) and c.get("column_name") == col["column_name"]),
                {},
            )
            cols.append({
                "column_name": col["column_name"],
                "data_type": col["data_type"],
                "description": llm_col.get("description", ""),
                "is_pii": llm_col.get("is_pii", False),
                "is_visible": llm_col.get("is_visible", True),
            })
        described.append({
            "table_name": tbl["table_name"],
            "description": llm_tbl.get("description", ""),
            "columns": cols,
        })

    return {"tables": described}


@app.get("/api/semantic")
async def get_semantic(model_id: int | None = None):
    if model_id is not None:
        rows = await pool.fetch("""
            SELECT t.id, t.table_name, t.description AS table_desc,
                   c.column_name, c.data_type, c.description AS col_desc,
                   c.is_pii, c.is_visible
            FROM semantic_tables t
            LEFT JOIN semantic_columns c ON c.table_id = t.id
            WHERE t.model_id = $1
            ORDER BY t.table_name, c.column_name
        """, model_id)
    else:
        rows = await pool.fetch("""
            SELECT t.id, t.table_name, t.description AS table_desc,
                   c.column_name, c.data_type, c.description AS col_desc,
                   c.is_pii, c.is_visible
            FROM semantic_tables t
            LEFT JOIN semantic_columns c ON c.table_id = t.id
            ORDER BY t.table_name, c.column_name
        """)
    tables: dict[str, dict] = {}
    for r in rows:
        tn = r["table_name"]
        if tn not in tables:
            tables[tn] = {
                "table_name": tn,
                "description": r["table_desc"],
                "columns": [],
            }
        if r["column_name"]:
            tables[tn]["columns"].append({
                "column_name": r["column_name"],
                "data_type": r["data_type"],
                "description": r["col_desc"],
                "is_pii": r["is_pii"],
                "is_visible": r["is_visible"],
            })
    return {"tables": list(tables.values())}


@app.post("/api/semantic/save")
async def save_semantic(req: SemanticSaveRequest):
    async with pool.acquire() as conn:
        for tbl in req.tables:
            row = await conn.fetchrow("""
                INSERT INTO semantic_tables (model_id, table_name, description)
                VALUES ($1, $2, $3)
                ON CONFLICT (model_id, table_name) DO UPDATE SET description = $3
                RETURNING id
            """, req.model_id, tbl.table_name, tbl.description)
            table_id = row["id"]
            for col in tbl.columns:
                await conn.execute("""
                    INSERT INTO semantic_columns
                        (table_id, column_name, data_type, description, is_pii, is_visible)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (table_id, column_name) DO UPDATE SET
                        data_type = $3, description = $4, is_pii = $5, is_visible = $6
                """, table_id, col.column_name, col.data_type,
                     col.description, col.is_pii, col.is_visible)
    return {"status": "saved"}


def _build_schema_prompt(sem_tables: list[dict], fk_rows: list) -> str:
    """Build the schema section of the prompt, including hidden/PII hints."""
    schema_lines = []
    table_names = set()
    for tbl in sem_tables:
        table_names.add(tbl["table_name"])
        schema_lines.append(f"Table: {tbl['table_name']}")
        if tbl.get("description"):
            schema_lines.append(f"  -- {tbl['description']}")
        for col in tbl.get("columns", []):
            parts = [f"  - {col['column_name']} ({col.get('data_type', 'unknown')})"]
            if col.get("description"):
                parts.append(f": {col['description']}")
            if col.get("is_pii"):
                parts.append(" [PII]")
            elif not col.get("is_visible", True):
                parts.append(" [hidden — avoid unless necessary]")
            schema_lines.append("".join(parts))
        schema_lines.append("")

    fk_lines = []
    for fk in fk_rows:
        if fk["table_name"] in table_names:
            fk_lines.append(
                f"  {fk['table_name']}.{fk['column_name']} -> "
                f"{fk['foreign_table']}.{fk['foreign_column']}"
            )
    if fk_lines:
        schema_lines.append("Relationships:")
        schema_lines.extend(fk_lines)
        schema_lines.append("")

    return "\n".join(schema_lines)


def _extract_sql(raw: str) -> str | None:
    """Extract SQL from LLM response, stripping markdown/thinking tags."""
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    cleaned = re.sub(r"^```(?:sql)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    # Find the SELECT statement if there's extra text
    match = re.search(r"(SELECT\b.+)", cleaned, re.DOTALL | re.IGNORECASE)
    if match:
        sql = match.group(1).rstrip(";").strip()
        return sql
    return None


async def _get_pii_columns(model_id: int | None) -> set[str]:
    """Return a set of column names marked as PII in the semantic model."""
    if model_id is None:
        rows = await pool.fetch(
            "SELECT column_name FROM semantic_columns WHERE is_pii = TRUE"
        )
    else:
        rows = await pool.fetch("""
            SELECT c.column_name
            FROM semantic_columns c
            JOIN semantic_tables t ON c.table_id = t.id
            WHERE c.is_pii = TRUE AND t.model_id = $1
        """, model_id)
    return {r["column_name"] for r in rows}



async def _call_ollama(prompt: str) -> str:
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
        )
        resp.raise_for_status()
        return resp.json().get("response", "")


@app.post("/api/query")
async def query(req: QueryRequest):
    sql = req.sql
    schema_prompt = None

    if not sql:
        # Build context from semantic model (show ALL columns, with PII/hidden hints)
        sem = await get_semantic(model_id=req.model_id)
        sem_tables = sem["tables"]

        if not sem_tables:
            # Fallback: use raw introspection
            intro = await introspect()
            sem_tables = intro["tables"]

        # Fetch foreign keys
        fk_rows = await pool.fetch("""
            SELECT tc.table_name, kcu.column_name,
                   ccu.table_name AS foreign_table, ccu.column_name AS foreign_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'
        """)

        schema_prompt = _build_schema_prompt(sem_tables, fk_rows)

        prompt = (
            "You are a PostgreSQL expert. Write a single SELECT query to answer "
            "the user's question based on this schema.\n\n"
            "Rules:\n"
            "- Use only the column names shown in the schema — they are the real column names.\n"
            "- Columns marked [PII] exist and can be used in queries normally.\n"
            "- Use the relationships listed to JOIN tables.\n"
            "- Return only the SQL query.\n\n"
            f"{schema_prompt}\n"
            f"Question: {req.question}"
        )

        try:
            raw = await _call_ollama(prompt)
        except Exception as e:
            return {"error": f"Ollama error: {e}", "raw": ""}

        sql = _extract_sql(raw)
        if not sql:
            return {"error": "Could not parse SQL from response", "raw": raw}

    # Pre-flight PII check: probe column names with LIMIT 0
    pii_columns = await _get_pii_columns(req.model_id)
    if pii_columns:
        try:
            async with pool.acquire() as conn:
                await conn.execute("SET statement_timeout = '5s'")
                stmt = await conn.prepare(f"SELECT * FROM ({sql}) _pii_probe LIMIT 0")
                probe_columns = [a.name for a in stmt.get_attributes()]
        except Exception:
            probe_columns = []

        blocked = pii_columns & set(probe_columns) if probe_columns else set()
        if blocked:
            # Find tables referenced in the SQL
            sem = await get_semantic(model_id=req.model_id)
            all_sem_tables = sem["tables"]
            sql_upper = sql.upper()
            referenced_tables = [
                t for t in all_sem_tables if t["table_name"].upper() in sql_upper
            ]
            if not referenced_tables:
                referenced_tables = all_sem_tables

            # Collect non-PII columns from referenced tables
            safe_by_table = {}
            for tbl in referenced_tables:
                safe_cols = [
                    c["column_name"] for c in tbl.get("columns", [])
                    if not c.get("is_pii", False)
                ]
                if safe_cols:
                    safe_by_table[tbl["table_name"]] = safe_cols

            if not req.accept_without_pii:
                return {
                    "pii_blocked": True,
                    "sql": sql,
                    "blocked_columns": sorted(blocked),
                    "safe_columns": safe_by_table,
                }

            # User accepted: build a new query using only non-PII columns
            if not safe_by_table:
                return {"error": "No non-PII columns available for these tables."}
            # Build SELECT from the referenced tables' safe columns
            if len(referenced_tables) == 1:
                tbl_name = referenced_tables[0]["table_name"]
                cols = safe_by_table[tbl_name]
                col_list = ", ".join(cols)
                sql = f'SELECT {col_list} FROM "{tbl_name}"'
            else:
                # Multi-table: select safe columns that exist in the original result,
                # or fall back to all safe columns from the first table
                all_safe = set()
                for cols in safe_by_table.values():
                    all_safe.update(cols)
                safe_in_result = [c for c in probe_columns if c in all_safe]
                if safe_in_result:
                    col_list = ", ".join(safe_in_result)
                    sql = f"SELECT {col_list} FROM ({sql}) _safe"
                else:
                    # Original query only had PII cols; pick first table's safe columns
                    tbl_name = referenced_tables[0]["table_name"]
                    cols = safe_by_table.get(tbl_name, list(next(iter(safe_by_table.values()))))
                    col_list = ", ".join(cols)
                    sql = f'SELECT {col_list} FROM "{tbl_name}"'

    # Execute with auto-retry on error
    max_attempts = 1 if req.sql else 2  # only retry LLM-generated SQL
    last_error = None
    for attempt in range(max_attempts):
        try:
            async with pool.acquire() as conn:
                await conn.execute("SET statement_timeout = '5s'")
                rows = await conn.fetch(sql)
            last_error = None
            break
        except Exception as e:
            last_error = str(e)
            if attempt == 0 and max_attempts > 1 and schema_prompt:
                # Retry: feed the error back to the LLM
                retry_prompt = (
                    "The following SQL query failed with an error. Fix it using "
                    "only the column names from the schema.\n\n"
                    f"{schema_prompt}\n"
                    f"Original question: {req.question}\n\n"
                    f"Failed SQL:\n{sql}\n\n"
                    f"Error: {last_error}\n\n"
                    "Write the corrected SQL query only."
                )
                try:
                    raw = await _call_ollama(retry_prompt)
                    fixed = _extract_sql(raw)
                    if fixed:
                        sql = fixed
                except Exception:
                    pass

    if last_error:
        return {"error": "SQL error", "sql": sql, "detail": last_error}

    all_columns = [str(k) for k in rows[0].keys()] if rows else []

    # Safety net: always strip PII columns from results regardless of query path
    if not pii_columns:
        pii_columns = await _get_pii_columns(req.model_id)
    redacted = pii_columns & set(all_columns)
    if redacted:
        safe_indices = [i for i, c in enumerate(all_columns) if c not in pii_columns]
        columns = [all_columns[i] for i in safe_indices]
        result_rows = [
            [(v if not isinstance(v, bytes) else v.hex()) for j, v in enumerate(r.values()) if j in safe_indices]
            for r in rows
        ]
    else:
        columns = all_columns
        result_rows = [[v if not isinstance(v, bytes) else v.hex() for v in r.values()] for r in rows]

    # Save to history
    try:
        await pool.execute("""
            INSERT INTO query_history (question, sql, was_edited, result_rows)
            VALUES ($1, $2, $3, $4)
        """, req.question, sql, req.was_edited, len(result_rows))
    except Exception:
        pass

    return {
        "sql": sql,
        "columns": columns,
        "rows": result_rows,
        "row_count": len(result_rows),
    }


@app.get("/api/history")
async def history():
    rows = await pool.fetch("""
        SELECT id, question, sql, was_edited, result_rows, created_at
        FROM query_history
        ORDER BY created_at DESC
        LIMIT 20
    """)
    return {"history": [dict(r) for r in rows]}
