"""Cost tracking and system statistics."""

from __future__ import annotations

from datetime import datetime, date


class StatsTracker:
    """Track API usage, cost estimates, and alerts."""

    def __init__(self, daily_budget: float = 0.0, max_per_hour: int = 120) -> None:
        self._daily_budget = daily_budget  # 0 = unlimited
        self._max_per_hour = max_per_hour
        self._start_time = datetime.now()
        self._total_analyses = 0
        self._total_alerts = 0
        self._today: date = date.today()
        self._today_analyses = 0
        self._hour_analyses: list[datetime] = []

    def _check_day_rollover(self) -> None:
        today = date.today()
        if today != self._today:
            self._today = today
            self._today_analyses = 0

    def record_analysis(self) -> None:
        self._check_day_rollover()
        self._total_analyses += 1
        self._today_analyses += 1
        now = datetime.now()
        self._hour_analyses.append(now)
        # Prune entries older than 1 hour
        cutoff = datetime(
            now.year, now.month, now.day, now.hour, now.minute, now.second
        )
        from datetime import timedelta

        cutoff = now - timedelta(hours=1)
        self._hour_analyses = [t for t in self._hour_analyses if t >= cutoff]

    def record_alert(self) -> None:
        self._total_alerts += 1

    def _prune_hour_analyses(self) -> None:
        """Remove entries older than 1 hour from the hourly window."""
        from datetime import timedelta

        cutoff = datetime.now() - timedelta(hours=1)
        self._hour_analyses = [t for t in self._hour_analyses if t >= cutoff]

    def budget_exceeded(self) -> bool:
        self._check_day_rollover()
        # Estimate cost: ~$0.0003 per analysis (vision LLM with image)
        if self._daily_budget > 0:
            estimated_cost = self._today_analyses * 0.0003
            if estimated_cost >= self._daily_budget:
                return True
        # Hourly rate limit — prune stale entries first
        self._prune_hour_analyses()
        if len(self._hour_analyses) >= self._max_per_hour:
            return True
        return False

    def summary(self) -> dict:
        self._check_day_rollover()
        estimated_today_cost = self._today_analyses * 0.0003
        uptime = (datetime.now() - self._start_time).total_seconds()
        return {
            "total_analyses": self._total_analyses,
            "today_analyses": self._today_analyses,
            "estimated_today_cost_usd": round(estimated_today_cost, 4),
            "daily_budget_usd": self._daily_budget,
            "budget_remaining_pct": (
                round((1 - estimated_today_cost / self._daily_budget) * 100, 1)
                if self._daily_budget > 0
                else None
            ),
            "analyses_this_hour": len(self._hour_analyses),
            "max_per_hour": self._max_per_hour,
            "total_alerts": self._total_alerts,
            "uptime_seconds": round(uptime, 1),
        }
