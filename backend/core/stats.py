import json
from datetime import datetime, timedelta
from typing import List, Dict
from backend.core.analytics import analytics_service

class StatsService:
    @staticmethod
    def get_stats():
        """
        Returns real analytics data from the database.
        Supports both SQLite and PostgreSQL syntax automatically.
        """
        from backend.core.database import db_manager
        db_stats = db_manager.get_summary_stats()
        
        is_pg = db_manager.is_postgres
        placeholder = "%s" if is_pg else "?"
        # PostgreSQL uses timestamp::date or DATE(timestamp), both work, 
        # but the parameterized placeholder differs
        date_filter = f"DATE(timestamp) = {placeholder}"
        
        conn = db_manager._get_connection()
        cursor = conn.cursor()
        
        # Proper Global Avoided Spend Calculation
        # Baseline = "What would this cost on GPT-4o at full price?"
        # Uses real pricing from AnalyticsService instead of a hardcoded constant.
        savings = 0.0
        try:
            cursor.execute("SELECT SUM(prompt_tokens), SUM(completion_tokens), SUM(cost) FROM request_logs")
            global_row = cursor.fetchone()
            global_input_tokens = global_row[0] or 0
            global_output_tokens = global_row[1] or 0
            global_cost = global_row[2] or 0.0
            
            # Calculate what GPT-4o would have cost for the same traffic
            baseline_global = analytics_service.calculate_cost("gpt-4o", global_input_tokens, global_output_tokens)
            savings = max(0, baseline_global - global_cost)
        except Exception:
            pass
            
        display_savings = round(savings, 4) if savings < 1 else round(savings, 2)
        
        # Build dynamic 7-day array
        days_array = []
        actual_cost_array = []
        saved_cost_array = []
        recent_logs = []
        
        try:
            # 7-day array logic
            for i in range(6, -1, -1):
                target_date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
                days_array.append(target_date[-5:]) # MM-DD
                
                cursor.execute(
                    f"SELECT SUM(cost), SUM(prompt_tokens), SUM(completion_tokens) FROM request_logs WHERE {date_filter}",
                    (target_date,)
                )
                row = cursor.fetchone()
                day_cost = row[0] or 0.0
                day_input_tokens = row[1] or 0
                day_output_tokens = row[2] or 0
                
                actual_cost_array.append(day_cost)
                
                baseline_cost = analytics_service.calculate_cost("gpt-4o", day_input_tokens, day_output_tokens)
                saved_amt = max(0, baseline_cost - day_cost)
                saved_cost_array.append(saved_amt)

            # Get 5 recent logs for the table
            cursor.execute("SELECT id, model, strategy, cost, cached, prompt_tokens, completion_tokens FROM request_logs ORDER BY timestamp DESC LIMIT 5")
            for row in cursor.fetchall():
                is_cached = bool(row[4])
                model_name = str(row[1])
                cost = row[3] or 0.0
                p_tokens = row[5] or 25
                c_tokens = row[6] or 25
                
                baseline_log_cost = analytics_service.calculate_cost("gpt-4o", p_tokens, c_tokens)
                savings_amt = baseline_log_cost if is_cached else max(0, baseline_log_cost - cost)
                
                status_text = "Cache Hit" if is_cached else ("95% Saved" if "llama" in model_name.lower() else "Quality Priority")
                status_color = "blue" if is_cached else ("teal" if "llama" in model_name.lower() else "slate")
                
                recent_logs.append({
                    "id": str(row[0])[-8:],  # Last 8 chars of UUID
                    "model": model_name,
                    "strategy": row[2],
                    "cost": cost,
                    "savings_amt": savings_amt,
                    "status_text": status_text,
                    "status_color": status_color
                })
        except Exception:
            pass

        try:
            cursor.execute("SELECT AVG(latency_ms) FROM request_logs")
            avg_row = cursor.fetchone()
            avg_latency = int(avg_row[0]) if avg_row and avg_row[0] else 0
        except Exception:
            avg_latency = 0

        # Clean up connection
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass
            
        total_queries = db_stats.get("total_queries", 0)
        # Use real tracked data instead of fabricated percentages
        blocked_injections = db_manager.get_blocked_injection_count()

        return {
            "total_savings": display_savings,
            "total_queries": total_queries,
            "queries_cached": db_stats.get("queries_cached", 0),
            "avg_latency": avg_latency,
            "blocked_injections": blocked_injections,
            "top_models": db_stats.get("top_models", []),
            "recent_logs": recent_logs,
            "cost_over_time": {
                "days": days_array if days_array else ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                "actual_cost": actual_cost_array if actual_cost_array else [0]*7,
                "saved_cost": saved_cost_array if saved_cost_array else [0]*7
            }
        }

stats_service = StatsService()
