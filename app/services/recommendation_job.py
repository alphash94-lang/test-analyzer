from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import Lock, Thread
from typing import Any

from app.config import Settings
from app.models.recommendation import PortfolioProfile
from app.services.recommendation_service import RecommendationService


@dataclass(frozen=True)
class RecommendationJobSnapshot:
    status: str = "idle"
    processed: int = 0
    total: int = 0
    symbol: str = ""
    category: str = ""
    error: str | None = None
    result: Any | None = None


class RecommendationJobManager:
    """Run one full recommendation calculation outside the Streamlit request."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._snapshot = RecommendationJobSnapshot()

    def snapshot(self) -> RecommendationJobSnapshot:
        with self._lock:
            return self._snapshot

    def start(
        self,
        settings: Settings,
        *,
        as_of_at: datetime,
        profile: PortfolioProfile,
    ) -> bool:
        with self._lock:
            if self._snapshot.status == "running":
                return False
            self._snapshot = RecommendationJobSnapshot(status="running")

        Thread(
            target=self._run,
            args=(settings, as_of_at, profile),
            name="recommendation-run",
            daemon=True,
        ).start()
        return True

    def _run(
        self,
        settings: Settings,
        as_of_at: datetime,
        profile: PortfolioProfile,
    ) -> None:
        service = RecommendationService(settings)

        def progress(processed: int, total: int, symbol: str, category: str) -> None:
            with self._lock:
                self._snapshot = RecommendationJobSnapshot(
                    status="running",
                    processed=processed,
                    total=total,
                    symbol=symbol,
                    category=category,
                )

        try:
            result = service.run_universe(
                as_of_at=as_of_at,
                profile=profile,
                progress=progress,
            )
            with self._lock:
                self._snapshot = RecommendationJobSnapshot(
                    status="completed",
                    processed=result.processed_count,
                    total=result.total_count,
                    result=result,
                )
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._snapshot = RecommendationJobSnapshot(
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
        finally:
            service.close()


recommendation_jobs = RecommendationJobManager()
