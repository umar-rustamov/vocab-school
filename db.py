# -*- coding: utf-8 -*-
import sqlite3
import os
from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(os.path.dirname(__file__), "vocab_school.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('student','teacher','admin')),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS units (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number INTEGER NOT NULL UNIQUE,
    title TEXT,
    created_by INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(created_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    unit_id INTEGER NOT NULL,
    word TEXT NOT NULL,
    translation TEXT NOT NULL,
    synonyms TEXT DEFAULT '[]',
    collocations TEXT DEFAULT '[]',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(unit_id) REFERENCES units(id)
);

CREATE TABLE IF NOT EXISTS progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL,
    word_id INTEGER NOT NULL,
    box INTEGER DEFAULT 0,
    due INTEGER DEFAULT 0,
    seen INTEGER DEFAULT 0,
    correct INTEGER DEFAULT 0,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(student_id, word_id),
    FOREIGN KEY(student_id) REFERENCES users(id),
    FOREIGN KEY(word_id) REFERENCES words(id)
);

CREATE TABLE IF NOT EXISTS revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    editor_id INTEGER,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    action TEXT NOT NULL,
    detail TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(editor_id) REFERENCES users(id)
);
"""

DEFAULT_ADMIN_EMAIL = "admin@school.local"
DEFAULT_ADMIN_PASSWORD = "admin123"  # поменяйте после первого входа!


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()

    existing = conn.execute(
        "SELECT id FROM users WHERE email = ?", (DEFAULT_ADMIN_EMAIL,)
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
            (
                "Главный админ",
                DEFAULT_ADMIN_EMAIL,
                generate_password_hash(DEFAULT_ADMIN_PASSWORD),
                "admin",
            ),
        )
        conn.commit()
        print(
            f"[vocab-school] Создан админ по умолчанию: "
            f"{DEFAULT_ADMIN_EMAIL} / {DEFAULT_ADMIN_PASSWORD} — смените пароль после входа!"
        )
    conn.close()


def log_revision(conn, editor_id, entity_type, entity_id, action, detail=""):
    conn.execute(
        "INSERT INTO revisions (editor_id, entity_type, entity_id, action, detail) "
        "VALUES (?, ?, ?, ?, ?)",
        (editor_id, entity_type, entity_id, action, detail),
    )
