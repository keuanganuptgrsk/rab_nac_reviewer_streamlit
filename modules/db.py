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
                created_by TEXT, created_at TEXT, updated_at TEXT, notes TEXT
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
    seed_db_if_empty()
    ensure_demo_keywords()
    ensure_fast_review_defaults()
    create_templates()


def seed_db_if_empty():
    with connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM nac_keywords").fetchone()[0]
        if count:
            return
        seeds = [
            ("Rapat/Jamuan", "konsumsi rapat", "Konsumsi kegiatan rapat", "DEMO - validasi PMK/internal diperlukan", "medium"),
            ("Rapat/Jamuan", "jamuan rapat", "Jamuan kegiatan rapat", "DEMO - validasi PMK/internal diperlukan", "medium"),
            ("Rapat/Jamuan", "snack meeting", "Snack/coffee break meeting", "DEMO", "medium"),
            ("Rapat/Jamuan", "coffee break", "Coffee break", "DEMO", "medium"),
            ("Pegawai", "fasilitas pegawai", "Fasilitas pegawai", "DEMO", "high"),
            ("Pegawai", "tunjangan pegawai", "Tunjangan pegawai", "DEMO", "high"),
            ("Pegawai", "uang cuti", "Uang cuti", "DEMO", "high"),
            ("Pegawai", "rumah dinas pegawai", "Rumah dinas pegawai", "DEMO", "high"),
            ("Pegawai", "rekreasi pegawai", "Rekreasi pegawai", "DEMO", "high"),
            ("Representasi", "entertainment", "Entertainment", "DEMO", "high"),
            ("Denda/Sanksi", "denda", "Denda", "DEMO", "high"),
            ("Denda/Sanksi", "sanksi", "Sanksi", "DEMO", "high"),
            ("Pribadi/Hadiah", "biaya pribadi", "Biaya pribadi", "DEMO", "very_high"),
            ("Pribadi/Hadiah", "hadiah", "Hadiah", "DEMO", "medium"),
            ("Pribadi/Hadiah", "souvenir", "Souvenir", "DEMO", "medium"),
            ("Pegawai", "seragam non teknis", "Seragam non teknis", "DEMO", "medium"),
            ("Representasi", "biaya representasi", "Biaya representasi", "DEMO", "high"),
        ]
        for category, keyword, desc, ref, severity in seeds:
            cur = conn.execute(
                """INSERT INTO nac_keywords
                (category, keyword, description, reference, severity, status, created_by, created_at, updated_at, notes)
                VALUES (?, ?, ?, ?, ?, 'active', 'system_seed', ?, ?, 'Demo seed; wajib divalidasi')""",
                (category, keyword, desc, ref, severity, now(), now()),
            )
            for syn in _default_synonyms(keyword):
                conn.execute(
                    "INSERT INTO nac_synonyms (nac_keyword_id, synonym, weight, status, created_at) VALUES (?, ?, 0.9, 'active', ?)",
                    (cur.lastrowid, syn, now()),
                )
        allowable = [
            "material konstruksi", "jasa instalasi", "jasa pengujian", "inspeksi teknis",
            "transportasi teknis proyek", "peralatan kerja", "pengujian gardu",
            "pemeliharaan jaringan", "penggantian material", "commissioning",
            "mobilisasi alat", "konsumsi bahan bakar", "bahan bakar genset",
        ]
        for kw in allowable:
            conn.execute(
                "INSERT INTO allowable_keywords (category, keyword, description, status, created_at) VALUES ('Teknis', ?, 'Demo allowable keyword', 'active', ?)",
                (kw, now()),
            )
        conn.execute(
            "INSERT INTO exceptions (pattern, reason, action, weight_adjustment, status, created_at) VALUES (?, ?, 'lower_confidence', 35, 'active', ?)",
            ("konsumsi bahan bakar", "Konsumsi dalam konteks bahan bakar, bukan konsumsi rapat/jamuan", now()),
        )
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
        for k, v in defaults.items():
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, v))


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
    demo_keywords = [
        ("Rapat/Jamuan", "konsumsi", "Konsumsi/jamuan umum; demo keyword perlu validasi", "DEMO", "high", ["prasmanan", "makan minum", "minuman", "snack box"]),
        ("Rapat/Jamuan", "catering", "Catering/jamuan; demo keyword perlu validasi", "DEMO", "high", ["katering", "charge catering"]),
        ("Rapat/Jamuan", "prasmanan", "Konsumsi prasmanan; demo keyword perlu validasi", "DEMO", "high", ["menu prasmanan"]),
        ("Rapat/Jamuan", "snack", "Snack/kudapan; demo keyword perlu validasi", "DEMO", "high", ["snack anak", "snack anak2", "snack box", "kudapan"]),
        ("Rapat/Jamuan", "minuman", "Minuman/konsumsi; demo keyword perlu validasi", "DEMO", "medium", ["es jeruk", "nektar"]),
        ("Pribadi/Hadiah", "doorprize", "Doorprize/hadiah; demo keyword perlu validasi", "DEMO", "high", ["hadiah quiz", "hadiah quizziz"]),
        ("Pribadi/Hadiah", "oleh-oleh", "Oleh-oleh/cinderamata; demo keyword perlu validasi", "DEMO", "medium", ["buah tangan", "bawaan"]),
        ("Pribadi/Hadiah", "cinderamata", "Cinderamata/souvenir; demo keyword perlu validasi", "DEMO", "medium", ["kenang-kenangan"]),
        ("Representasi", "fee narasumber", "Fee/honor narasumber; demo keyword perlu validasi", "DEMO", "medium", ["honor narasumber", "tambahan fee penceramah"]),
        ("Pegawai", "baju vip", "Pakaian non-teknis/VIP; demo keyword perlu validasi", "DEMO", "medium", ["seragam vip"]),
        ("Personel/Operasional", "uang saku", "Uang saku/bantuan personal; demo keyword perlu validasi", "DEMO", "medium", ["bantuan uang saku"]),
        ("Personel/Operasional", "honorarium", "Honorarium personel; demo keyword perlu validasi", "DEMO", "medium", ["honor", "fee narasumber"]),
        ("Personel/Operasional", "pulsa petugas", "Pulsa/komunikasi personal; demo keyword perlu validasi", "DEMO", "medium", ["pulsa lapangan", "pulsa operator"]),
        ("Transportasi/Personel", "bantuan transport eksternal", "Transport/bantuan eksternal; demo keyword perlu validasi", "DEMO", "medium", ["transport eksternal", "bantuan transport"]),
    ]
    with connect() as conn:
        for category, keyword, desc, ref, severity, synonyms in demo_keywords:
            existing = conn.execute("SELECT id FROM nac_keywords WHERE lower(keyword)=lower(?)", (keyword,)).fetchone()
            if existing:
                keyword_id = existing["id"]
            else:
                cur = conn.execute(
                    """INSERT INTO nac_keywords
                    (category, keyword, description, reference, severity, status, created_by, created_at, updated_at, notes)
                    VALUES (?, ?, ?, ?, ?, 'active', 'system_seed', ?, ?, 'Demo seed; wajib divalidasi')""",
                    (category, keyword, desc, ref, severity, now(), now()),
                )
                keyword_id = cur.lastrowid
            for synonym in synonyms:
                exists = conn.execute(
                    "SELECT id FROM nac_synonyms WHERE nac_keyword_id=? AND lower(synonym)=lower(?)",
                    (keyword_id, synonym),
                ).fetchone()
                if not exists:
                    conn.execute(
                        "INSERT INTO nac_synonyms (nac_keyword_id, synonym, weight, status, created_at) VALUES (?, ?, 0.9, 'active', ?)",
                        (keyword_id, synonym, now()),
                    )


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
    clause = "WHERE s.status='active'" if active_only else ""
    return rows(
        f"""SELECT s.*, k.keyword AS parent_keyword, k.category, k.severity
        FROM nac_synonyms s LEFT JOIN nac_keywords k ON k.id=s.nac_keyword_id {clause}
        ORDER BY s.synonym"""
    )


def get_allowable(active_only=True):
    clause = "WHERE status='active'" if active_only else ""
    return rows(f"SELECT * FROM allowable_keywords {clause} ORDER BY keyword")


def get_exceptions(active_only=True):
    clause = "WHERE status='active'" if active_only else ""
    return rows(f"SELECT * FROM exceptions {clause} ORDER BY pattern")


def add_keyword(category, keyword, description="", reference="", severity="medium", status="active", notes="", created_by="user"):
    return execute(
        """INSERT INTO nac_keywords (category, keyword, description, reference, severity, status, created_by, created_at, updated_at, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (category, keyword, description, reference, severity, status, created_by, now(), now(), notes),
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
    cols = ["category", "keyword", "synonyms", "description", "reference", "severity", "status", "notes"]
    if not template.exists():
        pd.DataFrame(columns=cols).to_excel(template, index=False)
    if not seed_xlsx.exists():
        pd.DataFrame(get_keywords(False))[cols[:2] + ["description", "reference", "severity", "status", "notes"]].to_excel(seed_xlsx, index=False)
