# ABOUTME: Initial schema for Discourse exporter state tracking
# ABOUTME: Tracks export status, mappings, and failed operations

import sqlite3


def upgrade(conn: sqlite3.Connection) -> None:
    """Create Discourse exporter state tables."""
    
    # Export mapping: Google Chat → Discourse
    conn.execute("""
        CREATE TABLE IF NOT EXISTS export_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            
            discourse_type TEXT NOT NULL,
            discourse_id TEXT NOT NULL,
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            UNIQUE(source_type, source_id)
        )
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_mappings_source
        ON export_mappings(source_type, source_id)
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_mappings_discourse
        ON export_mappings(discourse_type, discourse_id)
    """)
    
    # Failed exports for retry
    conn.execute("""
        CREATE TABLE IF NOT EXISTS failed_exports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            operation TEXT NOT NULL,
            
            error_message TEXT,
            error_count INTEGER DEFAULT 1,
            
            blocked_by TEXT,
            
            first_attempt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_attempt TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            
            next_retry TIMESTAMP,
            
            UNIQUE(entity_type, entity_id, operation)
        )
    """)
    
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_failed_retry
        ON failed_exports(next_retry)
    """)
    
    # Export progress tracking
    conn.execute("""
        CREATE TABLE IF NOT EXISTS export_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            
            space_id TEXT NOT NULL UNIQUE,
            
            threads_exported INTEGER DEFAULT 0,
            messages_exported INTEGER DEFAULT 0,
            attachments_exported INTEGER DEFAULT 0,
            reactions_exported INTEGER DEFAULT 0,
            
            last_exported_message_time TIMESTAMP,
            
            status TEXT DEFAULT 'pending',
            
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Configuration and state
    conn.execute("""
        CREATE TABLE IF NOT EXISTS exporter_state (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Set initial state
    conn.execute("""
        INSERT INTO exporter_state (key, value)
        VALUES ('mapping_mode', 'hybrid')
    """)
    
    conn.commit()
