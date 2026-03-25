import json
from datetime import datetime, timedelta
from typing import List, Dict

class StatsService:
    @staticmethod
    def get_stats():
        """
        Returns real analytics data mixed with trend simulation.
        """
        from backend.core.database import db_manager
        db_stats = db_manager.get_summary_stats()
        
        # Actual savings calculation, don't round to 2 decimals if it's tiny
        savings = db_stats.get("total_cost", 0) * 0.85 # Assume 85% savings vs GPT-4o
        display_savings = round(savings, 4) if savings < 1 else round(savings, 2)
        
        # Build dynamic 7-day array
        cursor = db_manager.get_cursor()
        days_array = []
        actual_cost_array = []
        saved_cost_array = []
        
        if cursor:
            for i in range(6, -1, -1):
                target_date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
                days_array.append(target_date[-5:]) # MM-DD
                
                cursor.execute("SELECT SUM(cost) FROM request_logs WHERE DATE(timestamp) = ?", (target_date,))
                day_cost = cursor.fetchone()[0] or 0.0
                actual_cost_array.append(day_cost)
                saved_cost_array.append(day_cost * 0.85)

        return {
            "total_savings": display_savings,
            "total_queries": db_stats.get("total_queries", 0),
            "queries_cached": db_stats.get("queries_cached", 0),
            "top_models": db_stats.get("top_models", []),
            "cost_over_time": {
                "days": days_array if days_array else ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                "actual_cost": actual_cost_array if actual_cost_array else [0]*7,
                "saved_cost": saved_cost_array if saved_cost_array else [0]*7
            }
        }

stats_service = StatsService()
