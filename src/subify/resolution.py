"""Shared orchestration for resolving playlist tracks against a server."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

from .check import CheckAborted, CheckResult, CheckService
from .match import PlaylistTrack


class TrackResolutionService:
    """Resolve a playlist in order while centralising cache persistence."""

    def __init__(self, service: CheckService) -> None:
        self.service = service

    def run(
        self,
        tracks: list[PlaylistTrack],
        *,
        resume_after: int = 0,
        start_index: int = 1,
        total: int | None = None,
        on_result: Callable[[int, list[CheckResult]], None] | None = None,
    ) -> list[CheckResult]:
        """Resolve tracks; resumed tracks are never allowed to prompt again."""
        self.service.libraries_for_search()
        results: list[CheckResult] = []
        workers = self.service.config.workers
        executor = ThreadPoolExecutor(max_workers=workers) if workers > 1 else None
        searches: list[Future[list] | None] = (
            [executor.submit(self.service.search_initial, track) for track in tracks]
            if executor
            else [None] * len(tracks)
        )
        try:
            track_total = total if total is not None else len(tracks)
            for index, track in enumerate(tracks, start=start_index):
                future = searches[index - start_index]
                result = self.service.resolve_track(
                    track,
                    index=index,
                    total=track_total,
                    interactive=index - start_index >= resume_after,
                    initial_candidates=future.result() if future else None,
                )
                results.append(result)
                self.service.print_result(index, track_total, result)
                if on_result:
                    on_result(index, results)
        except CheckAborted:
            self.service.cache.save()
            raise
        finally:
            if executor:
                executor.shutdown(wait=True, cancel_futures=True)
        self.service.cache.save()
        return results
