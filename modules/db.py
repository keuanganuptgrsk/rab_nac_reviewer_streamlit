import os
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("RAB_NAC_DATA_DIR", BASE_DIR / "data"))
DB_PATH = Path(os.environ.get("RAB_NAC_DB_PATH", DATA_DIR / "app.db"))
KEYWORD_PACK_VERSION = "nac_2026_v1"
KEYWORD_PACK_FILENAME = "nac_2026_keyword_pack.xlsx"
KEYWORD_PACK_PATH = DATA_DIR / KEYWORD_PACK_FILENAME
BUNDLED_KEYWORD_PACK_PATH = BASE_DIR / "data" / KEYWORD_PACK_FILENAME


def now():
    return datetime.utcnow().isoformat(timespec="seconds")


@contextmanager
def connect(db_path=DB_PATH):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS nac_keywords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT, keyword TEXT NOT NULL, description TEXT, reference TEXT,
                severity TEXT DEFAULT 'medium', status TEXT DEFAULT 'active',
                created_by TEXT, created_at TEXT, updated_at TEXT, notes TEXT,
                nac_group TEXT, correction_percentage REAL, transaction_type TEXT,
                gl_account TEXT, gl_account_description TEXT, source_reference TEXT, source_slide TEXT
            );
            CREATE TABLE IF NOT EXISTS nac_synonyms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nac_keyword_id INTEGER, synonym TEXT NOT NULL, weight REAL DEFAULT 0.9,
                status TEXT DEFAULT 'active', created_at TEXT,
                FOREIGN KEY(nac_keyword_id) REFERENCES nac_keywords(id)
            );
            CREATE TABLE IF NOT EXISTS allowable_keywords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT, keyword TEXT NOT NULL, description TEXT,
                status TEXT DEFAULT 'active', created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS exceptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nac_keyword_id INTEGER NULL, pattern TEXT NOT NULL, reason TEXT,
                action TEXT DEFAULT 'lower_confidence', weight_adjustment REAL DEFAULT 25,
                status TEXT DEFAULT 'active', created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                row_id TEXT, original_text TEXT, matched_keyword TEXT, feedback_type TEXT,
                user_suggested_redaction TEXT, reviewer_notes TEXT, created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY, value TEXT
            );
            CREATE TABLE IF NOT EXISTS review_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_file TEXT, row_count INTEGER, created_at TEXT
            );
            """
        )
    migrate_schema()
    seed_default_settings()
    ensure_nac_2026_keyword_pack()
    ensure_fast_review_defaults()
    create_templates()


def migrate_schema():
    keyword_columns = {
        "nac_group": "TEXT",
        "correction_percentage": "REAL",
        "transaction_type": "TEXT",
        "gl_account": "TEXT",
        "gl_account_description": "TEXT",
        "source_reference": "TEXT",
        "source_slide": "TEXT",
    }
    with connect() as conn:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(nac_keywords)").fetchall()}
        for column, column_type in keyword_columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE nac_keywords ADD COLUMN {column} {column_type}")


def seed_default_settings():
    defaults = {
        "embedding_model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "enable_semantic": "false",
        "enable_stemming": "false",
        "fuzzy_threshold": "78",
        "semantic_threshold": "60",
        "exact_weight": "0.25",
        "synonym_weight": "0.25",
        "fuzzy_weight": "0.20",
        "semantic_weight": "0.30",
        "severity_weight": "0.10",
        "feedback_weight": "0.10",
        "allowable_penalty_weight": "0.20",
        "ocr_mode": "auto",
    }
    with connect() as conn:
        for key, value in defaults.items():
            conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))


def seed_db_if_empty():
    """Backward-compatible wrapper; production seeding is handled by ensure_nac_2026_keyword_pack."""
    ensure_nac_2026_keyword_pack()


def _default_synonyms(keyword):
    mapping = {
        "konsumsi rapat": ["makan rapat", "konsumsi meeting"],
        "jamuan rapat": ["hidangan rapat", "jamuan meeting"],
        "snack meeting": ["snack rapat", "kudapan rapat"],
        "coffee break": ["rehat kopi", "kopi rapat"],
        "biaya representasi": ["representasi", "biaya jamuan"],
    }
    return mapping.get(keyword, [])


def ensure_demo_keywords():
    """Backward-compatible no-op after v1.1.0."""
    ensure_nac_2026_keyword_pack()


def ensure_nac_2026_keyword_pack():
    settings = get_settings()
    if settings.get("keyword_pack_version") == KEYWORD_PACK_VERSION:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pack_path = KEYWORD_PACK_PATH if KEYWORD_PACK_PATH.exists() else BUNDLED_KEYWORD_PACK_PATH
    if not pack_path.exists():
        return

    keyword_frame = pd.read_excel(pack_path, sheet_name="NAC Keywords").fillna("")
    synonyms_frame = pd.read_excel(pack_path, sheet_name="Synonyms").fillna("")
    allowable_frame = pd.read_excel(pack_path, sheet_name="Allowable").fillna("")
    exceptions_frame = pd.read_excel(pack_path, sheet_name="Exceptions").fillna("")

    with connect() as conn:
        demo_ids = [
            row["id"]
            for row in conn.execute(
                """SELECT id FROM nac_keywords
                WHERE created_by='system_seed'
                   OR reference LIKE 'DEMO%'
                   OR notes LIKE '%Demo seed%'
                   OR notes LIKE '%demo keyword%'"""
            ).fetchall()
        ]
        if demo_ids:
            placeholders = ",".join("?" for _ in demo_ids)
            conn.execute(f"DELETE FROM nac_synonyms WHERE nac_keyword_id IN ({placeholders})", demo_ids)
            conn.execute(f"DELETE FROM exceptions WHERE nac_keyword_id IN ({placeholders})", demo_ids)
            conn.execute(f"DELETE FROM nac_keywords WHERE id IN ({placeholders})", demo_ids)

        keyword_id_by_text = {}
        for _, row in keyword_frame.iterrows():
            keyword = str(row.get("keyword", "")).strip()
            if not keyword:
                continue
            values = {
                "category": str(row.get("category", "")).strip(),
                "description": str(row.get("description", "")).strip(),
                "reference": str(row.get("reference", "")).strip(),
                "severity": str(row.get("severity", "medium") or "medium").strip(),
                "status": str(row.get("status", "active") or "active").strip(),
                "notes": str(row.get("notes", "")).strip(),
                "nac_group": str(row.get("nac_group", "")).strip(),
                "correction_percentage": _float_or_none(row.get("correction_percentage")),
                "transaction_type": str(row.get("transaction_type", "")).strip(),
                "gl_account": str(row.get("gl_account", "")).strip(),
                "gl_account_description": str(row.get("gl_account_description", "")).strip(),
                "source_reference": str(row.get("source_reference", "")).strip(),
                "source_slide": str(row.get("source_slide", "")).strip(),
            }
            existing = conn.execute("SELECT * FROM nac_keywords WHERE lower(keyword)=lower(?) ORDER BY id LIMIT 1", (keyword,)).fetchone()
            if existing:
                keyword_id = existing["id"]
                if existing["created_by"] == "system_seed":
                    conn.execute(
                        """UPDATE nac_keywords
                        SET category=?, description=?, reference=?, severity=?, status=?, notes=?,
                            nac_group=?, correction_percentage=?, transaction_type=?, gl_account=?,
                            gl_account_description=?, source_reference=?, source_slide=?, updated_at=?
                        WHERE id=?""",
                        (
                            values["category"], values["description"], values["reference"], values["severity"],
                            values["status"], values["notes"], values["nac_group"], values["correction_percentage"],
                            values["transaction_type"], values["gl_account"], values["gl_account_description"],
                            values["source_reference"], values["source_slide"], now(), keyword_id,
                        ),
                    )
            else:
                cur = conn.execute(
                    """INSERT INTO nac_keywords
                    (category, keyword, description, reference, severity, status, created_by, created_at, updated_at, notes,
                     nac_group, correction_percentage, transaction_type, gl_account, gl_account_description, source_reference, source_slide)
                    VALUES (?, ?, ?, ?, ?, ?, 'system_seed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        values["category"], keyword, values["description"], values["reference"], values["severity"],
                        values["status"], now(), now(), values["notes"], values["nac_group"],
                        values["correction_percentage"], values["transaction_type"], values["gl_account"],
                        values["gl_account_description"], values["source_reference"], values["source_slide"],
                    ),
                )
                keyword_id = cur.lastrowid
            keyword_id_by_text[keyword.lower()] = keyword_id

        for _, row in synonyms_frame.iterrows():
            keyword = str(row.get("keyword", "")).strip().lower()
            synonym = str(row.get("synonym", "")).strip()
            keyword_id = keyword_id_by_text.get(keyword)
            if not keyword_id or not synonym:
                continue
            exists = conn.execute(
                "SELECT id FROM nac_synonyms WHERE nac_keyword_id=? AND lower(synonym)=lower(?) LIMIT 1",
                (keyword_id, synonym),
            ).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO nac_synonyms (nac_keyword_id, synonym, weight, status, created_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        keyword_id,
                        synonym,
                        _float_or_none(row.get("weight")) or 0.9,
                        str(row.get("status", "active") or "active"),
                        now(),
                    ),
                )

        conn.execute("DELETE FROM allowable_keywords WHERE description LIKE 'Demo allowable keyword%'")
        for _, row in allowable_frame.iterrows():
            keyword = str(row.get("keyword", "")).strip()
            if not keyword:
                continue
            exists = conn.execute("SELECT id FROM allowable_keywords WHERE lower(keyword)=lower(?) LIMIT 1", (keyword,)).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO allowable_keywords (category, keyword, description, status, created_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        str(row.get("category", "") or "Teknis"),
                        keyword,
                        str(row.get("description", "")).strip(),
                        str(row.get("status", "active") or "active"),
                        now(),
                    ),
                )

        for _, row in exceptions_frame.iterrows():
            pattern = str(row.get("pattern", "")).strip()
            if not pattern:
                continue
            keyword = str(row.get("keyword", "")).strip().lower()
            keyword_id = keyword_id_by_text.get(keyword)
            exists = conn.execute("SELECT id FROM exceptions WHERE lower(pattern)=lower(?) LIMIT 1", (pattern,)).fetchone()
            if not exists:
                conn.execute(
                    """INSERT INTO exceptions
                    (nac_keyword_id, pattern, reason, action, weight_adjustment, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        keyword_id,
                        pattern,
                        str(row.get("reason", "")).strip(),
                        str(row.get("action", "lower_confidence") or "lower_confidence"),
                        _float_or_none(row.get("weight_adjustment")) or 25,
                        str(row.get("status", "active") or "active"),
                        now(),
                    ),
                )
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('keyword_pack_version', ?)", (KEYWORD_PACK_VERSION,))


def _float_or_none(value):
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def ensure_fast_review_defaults():
    settings = get_settings()
    if settings.get("semantic_user_configured") == "true":
        return
    if settings.get("enable_semantic") != "false":
        save_setting("enable_semantic", "false")


def rows(query, params=()):
    with connect() as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def execute(query, params=()):
    with connect() as conn:
        cur = conn.execute(query, params)
        return cur.lastrowid


def get_settings():
    return {r["key"]: r["value"] for r in rows("SELECT key, value FROM settings")}


def save_setting(key, value):
    execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))


def get_keywords(active_only=True):
    clause = "WHERE status='active'" if active_only else ""
    return rows(f"SELECT * FROM nac_keywords {clause} ORDER BY category, keyword")


def get_keyword_by_text(keyword):
    found = rows("SELECT * FROM nac_keywords WHERE lower(keyword)=lower(?) ORDER BY id LIMIT 1", (keyword,))
    return found[0] if found else None


def get_synonyms(active_only=True):
    clause = "WHERE s.status='active' AND k.status='active'" if active_only else ""
    return rows(
        f"""SELECT s.*, k.keyword AS parent_keyword, k.category, k.severity,
        k.nac_group, k.correction_percentage, k.transaction_type, k.gl_account,
        k.gl_account_description, k.source_reference, k.source_slide
        FROM nac_synonyms s LEFT JOIN nac_keywords k ON k.id=s.nac_keyword_id {clause}
        ORDER BY s.synonym"""
    )


def get_allowable(active_only=True):
    clause = "WHERE status='active'" if active_only else ""
    return rows(f"SELECT * FROM allowable_keywords {clause} ORDER BY keyword")


def get_exceptions(active_only=True):
    clause = "WHERE status='active'" if active_only else ""
    return rows(f"SELECT * FROM exceptions {clause} ORDER BY pattern")


def add_keyword(
    category,
    keyword,
    description="",
    reference="",
    severity="medium",
    status="active",
    notes="",
    created_by="user",
    nac_group="",
    correction_percentage=None,
    transaction_type="",
    gl_account="",
    gl_account_description="",
    source_reference="",
    source_slide="",
):
    return execute(
        """INSERT INTO nac_keywords
        (category, keyword, description, reference, severity, status, created_by, created_at, updated_at, notes,
         nac_group, correction_percentage, transaction_type, gl_account, gl_account_description, source_reference, source_slide)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            category, keyword, description, reference, severity, status, created_by, now(), now(), notes,
            nac_group, correction_percentage, transaction_type, gl_account, gl_account_description, source_reference, source_slide,
        ),
    )


def update_keyword_status(keyword_id, status):
    execute("UPDATE nac_keywords SET status=?, updated_at=? WHERE id=?", (status, now(), keyword_id))


def update_keyword(keyword_id, category, keyword, description, reference, severity, status, notes):
    execute(
        """UPDATE nac_keywords
        SET category=?, keyword=?, description=?, reference=?, severity=?, status=?, notes=?, updated_at=?
        WHERE id=?""",
        (category, keyword, description, reference, severity, status, notes, now(), keyword_id),
    )


def add_synonym(keyword_id, synonym, weight=0.9, status="active"):
    return execute(
        "INSERT INTO nac_synonyms (nac_keyword_id, synonym, weight, status, created_at) VALUES (?, ?, ?, ?, ?)",
        (keyword_id, synonym, weight, status, now()),
    )


def synonym_exists(keyword_id, synonym):
    found = rows(
        "SELECT id FROM nac_synonyms WHERE nac_keyword_id=? AND lower(synonym)=lower(?) LIMIT 1",
        (keyword_id, synonym),
    )
    return bool(found)


def update_synonym_status(synonym_id, status):
    execute("UPDATE nac_synonyms SET status=? WHERE id=?", (status, synonym_id))


def add_allowable(category, keyword, description="", status="active"):
    return execute(
        "INSERT INTO allowable_keywords (category, keyword, description, status, created_at) VALUES (?, ?, ?, ?, ?)",
        (category, keyword, description, status, now()),
    )


def update_allowable_status(allowable_id, status):
    execute("UPDATE allowable_keywords SET status=? WHERE id=?", (status, allowable_id))


def add_exception(keyword_id, pattern, reason="", action="lower_confidence", weight_adjustment=25, status="active"):
    return execute(
        "INSERT INTO exceptions (nac_keyword_id, pattern, reason, action, weight_adjustment, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (keyword_id or None, pattern, reason, action, weight_adjustment, status, now()),
    )


def update_exception_status(exception_id, status):
    execute("UPDATE exceptions SET status=? WHERE id=?", (status, exception_id))


def save_feedback(row_id, original_text, matched_keyword, feedback_type, user_suggested_redaction="", reviewer_notes=""):
    return execute(
        """INSERT INTO feedback (row_id, original_text, matched_keyword, feedback_type, user_suggested_redaction, reviewer_notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (row_id, original_text, matched_keyword, feedback_type, user_suggested_redaction, reviewer_notes, now()),
    )


def get_feedback():
    return rows("SELECT * FROM feedback ORDER BY created_at DESC")


def backup_db(destination=None):
    destination = Path(destination or (DATA_DIR / f"app_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.db"))
    shutil.copy2(DB_PATH, destination)
    return str(destination)


def restore_db(src_path):
    shutil.copy2(src_path, DB_PATH)
    init_db()
    return str(DB_PATH)


def reset_demo_database():
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()


def create_templates():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    template = DATA_DIR / "keyword_import_template.xlsx"
    seed_xlsx = DATA_DIR / "seed_keywords.xlsx"
    cols = [
        "category", "keyword", "synonyms", "description", "reference", "severity", "status", "notes",
        "nac_group", "correction_percentage", "transaction_type", "gl_account",
        "gl_account_description", "source_reference", "source_slide",
    ]
    if not template.exists():
        pd.DataFrame(columns=cols).to_excel(template, index=False)
    if not seed_xlsx.exists():
        pd.DataFrame(get_keywords(False)).to_excel(seed_xlsx, index=False)
