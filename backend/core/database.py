import json
import logging
from datetime import datetime
from backend.config import settings

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Database abstraction layer for Margin AI analytics.

    Supports two backends:
    - SQLite: For lightweight local dev mode (single-user, no Docker needed).
    - PostgreSQL: For production deployments (concurrent async, Docker Compose).

    The backend is auto-detected from the DATABASE_URL in the .env file.
    """
    def __init__(self):
        self.db_url = settings.DATABASE_URL
        self.is_postgres = self.db_url.startswith("postgresql")
        
        if self.is_postgres:
            self._init_postgres()
        else:
            self.db_path = self.db_url.replace("sqlite:///", "")
            self._init_sqlite()

    # --- SQLite Backend ---

    def _init_sqlite(self):
        import sqlite3
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS request_logs (
                    id TEXT PRIMARY KEY,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    model TEXT,
                    provider TEXT,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    total_tokens INTEGER,
                    cost FLOAT,
                    strategy TEXT,
                    latency_ms INTEGER,
                    cached BOOLEAN,
                    optimized BOOLEAN
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS security_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    event_type TEXT NOT NULL,
                    pattern_matched TEXT,
                    prompt_preview TEXT,
                    source_ip TEXT
                )
            """)
            conn.commit()

    # --- PostgreSQL Backend ---

    def _init_postgres(self):
        try:
            import psycopg2
            conn = psycopg2.connect(self.db_url)
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS request_logs (
                    id TEXT PRIMARY KEY,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    model TEXT,
                    provider TEXT,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    total_tokens INTEGER,
                    cost FLOAT,
                    strategy TEXT,
                    latency_ms INTEGER,
                    cached BOOLEAN,
                    optimized BOOLEAN
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS security_events (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    event_type TEXT NOT NULL,
                    pattern_matched TEXT,
                    prompt_preview TEXT,
                    source_ip TEXT
                )
            """)
            cur.close()
            conn.close()
            logger.info("PostgreSQL database initialized.")
        except ImportError:
            logger.error("psycopg2 not installed. Install with: pip install psycopg2-binary")
            raise
        except Exception as e:
            logger.error(f"PostgreSQL init failed: {e}. Falling back to SQLite.")
            self.is_postgres = False
            self.db_path = "./margin_ai.db"
            self._init_sqlite()

    # --- Unified Write Operations ---

    def _get_connection(self):
        """Get a database connection for the configured backend."""
        if self.is_postgres:
            import psycopg2
            return psycopg2.connect(self.db_url)
        else:
            import sqlite3
            return sqlite3.connect(self.db_path)

    def log_request(self, data: dict):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            
            placeholder = "%s" if self.is_postgres else "?"
            sql = f"""
                INSERT INTO request_logs 
                (id, model, provider, prompt_tokens, completion_tokens, total_tokens, cost, strategy, latency_ms, cached, optimized)
                VALUES ({', '.join([placeholder] * 11)})
            """
            
            cur.execute(sql, (
                data.get("id"),
                data.get("model"),
                data.get("provider", "openai"),
                data.get("usage", {}).get("prompt_tokens", 0),
                data.get("usage", {}).get("completion_tokens", 0),
                data.get("usage", {}).get("total_tokens", 0),
                data.get("estimated_cost", 0.0),
                data.get("strategy", "direct"),
                data.get("latency_ms", 0),
                data.get("cached", False),
                data.get("margin_ai_optimized", True)
            ))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to log request to DB: {e}")

    def log_security_event(self, event_type: str, pattern_matched: str = None, prompt_preview: str = None, source_ip: str = None):
        """Log a real security event (injection block, PII redaction, etc.) to the database."""
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            
            placeholder = "%s" if self.is_postgres else "?"
            sql = f"""
                INSERT INTO security_events (event_type, pattern_matched, prompt_preview, source_ip)
                VALUES ({', '.join([placeholder] * 4)})
            """
            
            cur.execute(sql, (
                event_type,
                pattern_matched,
                (prompt_preview[:100] + "...") if prompt_preview and len(prompt_preview) > 100 else prompt_preview,
                source_ip
            ))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to log security event: {e}")

    # --- Unified Read Operations ---

    def get_blocked_injection_count(self) -> int:
        """Return the real count of blocked injection attempts from the database."""
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM security_events WHERE event_type = 'injection_blocked'")
            row = cur.fetchone()
            count = row[0] if row else 0
            cur.close()
            conn.close()
            return count
        except Exception as e:
            logger.error(f"Failed to fetch injection count: {e}")
            return 0

    def get_cursor(self):
        """Returns a cursor with its parent connection for read operations."""
        try:
            if self.is_postgres:
                import psycopg2
                conn = psycopg2.connect(self.db_url)
                return conn.cursor()
            else:
                import sqlite3
                conn = sqlite3.connect(self.db_path)
                return conn.cursor()
        except Exception:
            return None

    def get_summary_stats(self):
        try:
            conn = self._get_connection()
            cur = conn.cursor()
            
            # Basic aggregation
            cur.execute("SELECT COUNT(*) as total_queries, SUM(cost) as total_cost, SUM(CASE WHEN cached=true THEN 1 ELSE 0 END) as cached_count FROM request_logs")
            row = cur.fetchone()
            
            total_queries = row[0] or 0
            total_cost = row[1] or 0.0
            cached_count = row[2] or 0

            # Model distribution
            cur.execute("SELECT model, COUNT(*) as count FROM request_logs GROUP BY model")
            models = [{"name": r[0], "usage": r[1]} for r in cur.fetchall()]
            
            cur.close()
            conn.close()

            return {
                "total_queries": total_queries,
                "total_cost": total_cost,
                "queries_cached": cached_count,
                "top_models": models
            }
        except Exception as e:
            logger.error(f"Failed to fetch stats from DB: {e}")
            return {}


db_manager = DatabaseManager()
