"""
Enhanced memory management for the AI Assistant.
Provides categorized, encrypted long-term memory storage.
"""
import json
import sqlite3
import uuid
import datetime
import os
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any
import sys

# Try to import sqlcipher for encrypted database
try:
    import pysqlite3 as sqlite3
    SQLCIPHER_AVAILABLE = True
except ImportError:
    import sqlite3
    SQLCIPHER_AVAILABLE = False

def get_base_dir() -> Path:
    """Get the base directory for the application."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR = get_base_dir()
MEMORY_DIR = BASE_DIR / "memory"
MEMORY_PATH = MEMORY_DIR / "assistant_memory.db"
_lock = threading.Lock()

# Memory categories (aligned with MEHDI_W_CLAP structure)
MEMORY_CATEGORIES = {
    "identity": "Core personal data (name, pronunciation, demographics, etc.)",
    "preferences": "Stated user likes/dislikes, defaults",
    "habits": "Recurrent routines or behaviors",
    "corrections": "User feedback on agent behavior",
    "entities": "People, places, things relevant to the user",
    "projects": "Projects and goals the user is working on",
    "relationships": "People in the user's life",
    "wishes": "Wishes, plans, wants of the user",
    "notes": "General notes and miscellaneous information",
    "context": "Situational awareness (location, time, activity)",
}

def _get_db_connection():
    """Get a database connection, with optional encryption."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    if SQLCIPHER_AVAILABLE:
        # Use encrypted database if sqlcipher is available
        conn = sqlite3.connect(str(MEMORY_PATH))
        # Get encryption passphrase from environment or config
        # For now, we'll use a simple approach - in production this should be more secure
        passphrase = os.environ.get("ASSISTANT_DB_PASSPHRASE", "default_passphrase_change_me")
        conn.execute(f"PRAGMA key = '{passphrase}'")
        return conn
    else:
        # Fallback to regular SQLite
        return sqlite3.connect(str(MEMORY_PATH))

def init_db():
    """Initialize the database with required tables."""
    with _lock:
        conn = _get_db_connection()
        try:
            c = conn.cursor()

            # Create the main memory entries table
            c.execute('''
                CREATE TABLE IF NOT EXISTS memory_entries (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    context_id TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    strength REAL NOT NULL DEFAULT 1.0,
                    source TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.8
                )
            ''')

            # Create indexes for faster querying
            c.execute('CREATE INDEX IF NOT EXISTS idx_memory_category_key ON memory_entries(category, key)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_memory_context ON memory_entries(context_id)')
            c.execute('CREATE INDEX IF NOT EXISTS idx_memory_updated ON memory_entries(updated_at)')

            conn.commit()
        finally:
            conn.close()

def _empty_memory_structure() -> dict:
    """Return an empty memory structure with all categories."""
    return {category: {} for category in MEMORY_CATEGORIES.keys()}

def load_memory() -> dict:
    """
    Load all memories from database and organize by category.
    Returns a dictionary with categories as keys and memories as nested dictionaries.
    """
    with _lock:
        conn = _get_db_connection()
        try:
            c = conn.cursor()
            c.execute('''
                SELECT id, category, key, value, context_id, created_at, updated_at,
                       strength, source, confidence
                FROM memory_entries
                ORDER BY updated_at DESC
            ''')
            rows = c.fetchall()

            # Organize by category
            memory = _empty_memory_structure()

            for row in rows:
                (entry_id, category, key, value, context_id, created_at,
                 updated_at, strength, source, confidence) = row

                if category in memory:
                    memory[category][key] = {
                        "id": entry_id,
                        "value": value,
                        "context_id": context_id,
                        "created_at": created_at,
                        "updated_at": updated_at,
                        "strength": strength,
                        "source": source,
                        "confidence": confidence
                    }

            return memory
        finally:
            conn.close()

def save_memory(memory: dict) -> None:
    """
    Save the entire memory structure to database.
    This replaces all existing memories with the provided structure.
    """
    with _lock:
        conn = _get_db_connection()
        try:
            c = conn.cursor()

            # Clear existing entries
            c.execute('DELETE FROM memory_entries')

            # Insert all memories from the structure
            for category, entries in memory.items():
                if category not in MEMORY_CATEGORIES:
                    continue

                for key, entry_data in entries.items():
                    if not isinstance(entry_data, dict) or "value" not in entry_data:
                        # Skip invalid entries
                        continue

                    c.execute('''
                        INSERT INTO memory_entries
                        (id, category, key, value, context_id, created_at, updated_at, strength, source, confidence)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        entry_data.get("id", str(uuid.uuid4())),
                        category,
                        key,
                        str(entry_data["value"]),
                        entry_data.get("context_id"),
                        entry_data.get("created_at", int(datetime.datetime.now().timestamp() * 1000)),
                        entry_data.get("updated_at", int(datetime.datetime.now().timestamp() * 1000)),
                        entry_data.get("strength", 1.0),
                        entry_data.get("source", "user_statement"),
                        entry_data.get("confidence", 0.8)
                    ))

            conn.commit()
        finally:
            conn.close()

def get_memory(category: str, key: str, context_id: Optional[str] = None) -> List[Dict]:
    """
    Retrieve specific memory entries.

    Args:
        category: Memory category
        key: Memory key
        context_id: Optional context ID to filter by

    Returns:
        List of matching memory entries as dictionaries
    """
    with _lock:
        conn = _get_db_connection()
        try:
            c = conn.cursor()

            if context_id is None:
                c.execute('''
                    SELECT id, category, key, value, context_id, created_at, updated_at,
                           strength, source, confidence
                    FROM memory_entries
                    WHERE category=? AND key=?
                ''', (category, key))
            else:
                c.execute('''
                    SELECT id, category, key, value, context_id, created_at, updated_at,
                           strength, source, confidence
                    FROM memory_entries
                    WHERE category=? AND key=? AND context_id=?
                ''', (category, key, context_id))

            rows = c.fetchall()
            results = []

            for row in rows:
                (entry_id, cat, k, value, ctx_id, created_at, updated_at,
                 strength, source, confidence) = row

                results.append({
                    "id": entry_id,
                    "category": cat,
                    "key": k,
                    "value": value,
                    "context_id": ctx_id,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "strength": strength,
                    "source": source,
                    "confidence": confidence
                })

            return results
        finally:
            conn.close()

def add_memory(category: str, key: str, value: str, context_id: Optional[str] = None,
               strength: float = 1.0, source: str = "user_statement", confidence: float = 0.8) -> str:
    """
    Add a new memory entry.

    Args:
        category: Memory category
        key: Memory key
        value: Memory value
        context_id: Optional context ID
        strength: Memory strength (0.0-2.0)
        source: Source of the memory
        confidence: Confidence in the memory accuracy (0.0-1.0)

    Returns:
        The ID of the created memory entry
    """
    if category not in MEMORY_CATEGORIES:
        raise ValueError(f"Invalid memory category: {category}")

    entry_id = str(uuid.uuid4())
    now = int(datetime.datetime.now().timestamp() * 1000)

    with _lock:
        conn = _get_db_connection()
        try:
            c = conn.cursor()
            c.execute('''
                INSERT INTO memory_entries
                (id, category, key, value, context_id, created_at, updated_at, strength, source, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (entry_id, category, key, value, context_id, now, now, strength, source, confidence))
            conn.commit()
        finally:
            conn.close()

    return entry_id

def update_memory(entry_id: str, **fields) -> bool:
    """
    Update an existing memory entry.

    Args:
        entry_id: ID of the memory entry to update
        **fields: Fields to update (key, value, context_id, strength, source, confidence)

    Returns:
        True if update was successful, False otherwise
    """
    allowed_fields = {'key', 'value', 'context_id', 'strength', 'source', 'confidence'}
    updates = {k: v for k, v in fields.items() if k in allowed_fields}

    if not updates:
        return False

    # Add updated timestamp
    updates['updated_at'] = int(datetime.datetime.now().timestamp() * 1000)

    with _lock:
        conn = _get_db_connection()
        try:
            c = conn.cursor()

            # Build SET clause
            set_clauses = [f"{field}=?" for field in updates.keys()]
            set_clause = ", ".join(set_clauses)

            # Prepare values
            values = list(updates.values()) + [entry_id]

            c.execute(f'''
                UPDATE memory_entries
                SET {set_clause}
                WHERE id=?
            ''', values)

            conn.commit()
            return c.rowcount > 0
        finally:
            conn.close()

def delete_memory(entry_id: str) -> bool:
    """
    Delete a memory entry by ID.

    Args:
        entry_id: ID of the memory entry to delete

    Returns:
        True if deletion was successful, False otherwise
    """
    with _lock:
        conn = _get_db_connection()
        try:
            c = conn.cursor()
            c.execute('DELETE FROM memory_entries WHERE id=?', (entry_id,))
            conn.commit()
            return c.rowcount > 0
        finally:
            conn.close()

def list_memory(limit: int = 20, category: Optional[str] = None) -> List[Dict]:
    """
    List recent memory entries.

    Args:
        limit: Maximum number of entries to return
        category: Optional category to filter by

    Returns:
        List of memory entries as dictionaries, ordered by update time (newest first)
    """
    with _lock:
        conn = _get_db_connection()
        try:
            c = conn.cursor()

            if category is None:
                c.execute('''
                    SELECT id, category, key, value, context_id, created_at, updated_at,
                           strength, source, confidence
                    FROM memory_entries
                    ORDER BY updated_at DESC
                    LIMIT ?
                ''', (limit,))
            else:
                c.execute('''
                    SELECT id, category, key, value, context_id, created_at, updated_at,
                           strength, source, confidence
                    FROM memory_entries
                    WHERE category=?
                    ORDER BY updated_at DESC
                    LIMIT ?
                ''', (category, limit))

            rows = c.fetchall()
            results = []

            for row in rows:
                (entry_id, cat, key, value, ctx_id, created_at, updated_at,
                 strength, source, confidence) = row

                results.append({
                    "id": entry_id,
                    "category": cat,
                    "key": key,
                    "value": value,
                    "context_id": ctx_id,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "strength": strength,
                    "source": source,
                    "confidence": confidence
                })

            return results
        finally:
            conn.close()

def get_memory_for_prompt(memory: dict = None) -> str:
    """
    Format memory for inclusion in LLM prompts.
    Similar to the format_memory_for_prompt function in MEHDI_W_CLAP.

    Args:
        memory: Memory dictionary (if None, loads from database)

    Returns:
        Formatted string suitable for inclusion in LLM prompts
    """
    if memory is None:
        memory = load_memory()

    if not memory or all(not category_dict for category_dict in memory.values()):
        return ""

    lines = []

    # Identity section
    identity = memory.get("identity", {})
    if identity:
        id_fields = ["name", "age", "birthday", "city", "job", "language", "school", "nationality"]
        for field in id_fields:
            entry = identity.get(field)
            if entry and isinstance(entry, dict) and "value" in entry:
                val = entry["value"]
                if val:
                    lines.append(f"{field.title()}: {val}")

        # Add any other identity fields
        for key, entry in identity.items():
            if key not in id_fields and isinstance(entry, dict) and "value" in entry:
                val = entry["value"]
                if val:
                    lines.append(f"{key.replace('_', ' ').title()}: {val}")

    if identity:
        lines.append("")  # Empty line after identity

    # Preferences
    prefs = memory.get("preferences", {})
    if prefs:
        lines.append("Preferences:")
        for key, entry in list(prefs.items())[:10]:  # Limit to top 10
            if isinstance(entry, dict) and "value" in entry:
                val = entry["value"]
                if val:
                    lines.append(f"  - {key.replace('_', ' ').title()}: {val}")
        lines.append("")  # Empty line after preferences

    # Projects/Goals
    projects = memory.get("projects", {})
    if projects:
        lines.append("Projects & Goals:")
        for key, entry in list(projects.items())[:8]:  # Limit to top 8
            if isinstance(entry, dict) and "value" in entry:
                val = entry["value"]
                if val:
                    lines.append(f"  - {key.replace('_', ' ').title()}: {val}")
        lines.append("")  # Empty line after projects

    # Relationships
    relationships = memory.get("relationships", {})
    if relationships:
        lines.append("Relationships:")
        for key, entry in list(relationships.items())[:10]:  # Limit to top 10
            if isinstance(entry, dict) and "value" in entry:
                val = entry["value"]
                if val:
                    lines.append(f"  - {key.replace('_', ' ').title()}: {val}")
        lines.append("")  # Empty line after relationships

    # Wishes/Plans
    wishes = memory.get("wishes", {})
    if wishes:
        lines.append("Wishes & Plans:")
        for key, entry in list(wishes.items())[:8]:  # Limit to top 8
            if isinstance(entry, dict) and "value" in entry:
                val = entry["value"]
                if val:
                    lines.append(f"  - {key.replace('_', ' ').title()}: {val}")
        lines.append("")  # Empty line after wishes

    # Notes
    notes = memory.get("notes", {})
    if notes:
        lines.append("Notes:")
        for key, entry in list(notes.items())[:8]:  # Limit to top 8
            if isinstance(entry, dict) and "value" in entry:
                val = entry["value"]
                if val:
                    lines.append(f"  - {key}: {val}")

    if not lines:
        return ""

    # Add header
    header = "[WHAT YOU KNOW ABOUT THIS USER — use naturally, never recite like a list]\n"
    result = header + "\n".join(lines)

    # Limit total length to prevent overwhelming the prompt
    if len(result) > 2000:
        result = result[:1997] + "..."

    return result + "\n"

def remember(key: str, value: str, category: str = "notes") -> str:
    """
    Convenience function to remember a simple key-value pair.

    Args:
        key: Memory key
        value: Memory value
        category: Memory category (default: "notes")

    Returns:
        Confirmation message
    """
    if category not in MEMORY_CATEGORIES:
        category = "notes"

    entry_id = add_memory(category, key, value)
    return f"Remembered: {category}/{key} = {value}"

def forget(key: str, category: str = "notes") -> str:
    """
    Convenience function to forget a specific memory.

    Args:
        key: Memory key to forget
        category: Memory category (default: "notes")

    Returns:
        Confirmation message
    """
    if category not in MEMORY_CATEGORIES:
        return f"Invalid category: {category}"

    # Find the memory entry
    memories = get_memory(category, key)
    if not memories:
        return f"Not found: {category}/{key}"

    # Delete all matching entries (should typically be just one)
    deleted_count = 0
    for memory in memories:
        if delete_memory(memory["id"]):
            deleted_count += 1

    if deleted_count > 0:
        return f"Forgotten: {category}/{key} ({deleted_count} entries)"
    else:
        return f"Failed to forget: {category}/{key}"

# Alias for backward compatibility
forget_memory = forget