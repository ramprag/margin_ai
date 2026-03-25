import sqlite3
import json
import logging
from datetime import datetime
from backend.config import settings

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self.db_path = settings.DATABASE_URL.replace("sqlite:///", "")
        self._init_db()

    def _init_db(self):
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
            conn.commit()

    def log_request(self, data: dict):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO request_logs 
                    (id, model, provider, prompt_tokens, completion_tokens, total_tokens, cost, strategy, latency_ms, cached, optimized)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
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
        except Exception as e:
            logger.error(f"Failed to log request to DB: {e}")

    def get_cursor(self):
        try:
            return sqlite3.connect(self.db_path).cursor()
        except:
            return None

    def get_summary_stats(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                # Basic aggregation
                cursor.execute("SELECT COUNT(*) as total_queries, SUM(cost) as total_cost, SUM(CASE WHEN cached=1 THEN 1 ELSE 0 END) as cached_count FROM request_logs")
                row = cursor.fetchone()
                
                # Model distribution
                cursor.execute("SELECT model, COUNT(*) as count FROM request_logs GROUP BY model")
                models = [{"name": r["model"], "usage": r["count"]} for r in cursor.fetchall()]
                
                return {
                    "total_queries": row["total_queries"] or 0,
                    "total_cost": row["total_cost"] or 0.0,
                    "queries_cached": row["cached_count"] or 0,
                    "top_models": models
                }
        except Exception as e:
            logger.error(f"Failed to fetch stats from DB: {e}")
            return {}

db_manager = DatabaseManager()
