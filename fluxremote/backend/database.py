# fluxremote/backend/database.py
import sqlite3
import os
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

DB_PATH = os.environ.get("DATABASE_URL", "fluxremote.db")

logger = logging.getLogger("fluxremote.database")

def get_connection():
    """Returns a connection to the SQLite database with row factory enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the database schema and creates necessary tables if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON;")
    
    # Users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    
    # Devices table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS devices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id TEXT UNIQUE NOT NULL,
        device_name TEXT NOT NULL,
        access_password_hash TEXT NOT NULL,
        owner_id INTEGER,
        is_online INTEGER DEFAULT 0,
        last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL
    );
    """)
    
    # Sessions table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT UNIQUE NOT NULL,
        device_id TEXT NOT NULL,
        viewer_id TEXT NOT NULL,
        host_id TEXT NOT NULL,
        session_token TEXT UNIQUE,
        pairing_code TEXT,
        status TEXT DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        ended_at TIMESTAMP,
        FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE CASCADE
    );
    """)

    # Ensure session token and pairing code columns exist for older databases
    cursor.execute("PRAGMA table_info(sessions);")
    existing_columns = [row[1] for row in cursor.fetchall()]
    if 'session_token' not in existing_columns:
        cursor.execute("ALTER TABLE sessions ADD COLUMN session_token TEXT;")
    if 'pairing_code' not in existing_columns:
        cursor.execute("ALTER TABLE sessions ADD COLUMN pairing_code TEXT;")
    
    # Connection History table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS connection_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        device_id TEXT NOT NULL,
        viewer_id TEXT NOT NULL,
        duration_seconds INTEGER DEFAULT 0,
        bytes_transferred INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    
    conn.commit()
    conn.close()
    logger.info("SQLite Database initialized successfully.")

# Database Access Operations

def create_user(username: str, email: str, password_hash: str) -> bool:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
            (username, email, password_hash)
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        return False

def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def register_device(device_id: str, device_name: str, password_hash: str, owner_username: Optional[str] = None) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    
    owner_id = None
    if owner_username:
        user = get_user_by_username(owner_username)
        if user:
            owner_id = user["id"]
            
    try:
        cursor.execute(
            """
            INSERT INTO devices (device_id, device_name, access_password_hash, owner_id, is_online, last_seen)
            VALUES (?, ?, ?, ?, 1, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                device_name = excluded.device_name,
                access_password_hash = excluded.access_password_hash,
                owner_id = COALESCE(excluded.owner_id, devices.owner_id),
                is_online = 1,
                last_seen = ?
            """,
            (device_id, device_name, password_hash, owner_id, datetime.now(), datetime.now())
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error registering device: {e}")
        return False

def update_device_status(device_id: str, is_online: bool):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE devices SET is_online = ?, last_seen = ? WHERE device_id = ?",
        (1 if is_online else 0, datetime.now(), device_id)
    )
    conn.commit()
    conn.close()

def get_device(device_id: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_online_devices() -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT device_id, device_name, is_online, last_seen FROM devices WHERE is_online = 1")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def create_session(session_id: str, device_id: str, viewer_id: str, host_id: str, session_token: str = None, pairing_code: str = None) -> bool:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO sessions (session_id, device_id, viewer_id, host_id, session_token, pairing_code) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, device_id, viewer_id, host_id, session_token, pairing_code)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error creating session record: {e}")
        return False


def get_session_by_token(session_token: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sessions WHERE session_token = ?", (session_token,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def close_session(session_id: str, duration: int = 0, bytes_tx: int = 0):
    conn = get_connection()
    cursor = conn.cursor()
    # Fetch session info first
    cursor.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
    session = cursor.fetchone()
    if session:
        cursor.execute(
            "UPDATE sessions SET status = 'ended', ended_at = ? WHERE session_id = ?",
            (datetime.now(), session_id)
        )
        cursor.execute(
            "INSERT INTO connection_history (session_id, device_id, viewer_id, duration_seconds, bytes_transferred) VALUES (?, ?, ?, ?, ?)",
            (session_id, session["device_id"], session["viewer_id"], duration, bytes_tx)
        )
    conn.commit()
    conn.close()
