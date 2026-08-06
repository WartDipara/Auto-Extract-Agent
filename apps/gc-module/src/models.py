from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ArtifactGroup:
    """One reclaim unit: workspace + result CSVs + buf_done (+ optional downloads)."""

    task_id: str
    reason: str
    module_id: str = ""
    tasks_table: str = "tasks"
    workspace: Path | None = None
    result_csvs: list[Path] = field(default_factory=list)
    buf_done: Path | None = None
    downloads: list[Path] = field(default_factory=list)
    db_row: dict | None = None

    def existing_paths(self) -> list[tuple[str, Path]]:
        out: list[tuple[str, Path]] = []
        if self.buf_done is not None and self.buf_done.exists():
            out.append(("buf_done", self.buf_done))
        for path in self.result_csvs:
            if path.exists():
                out.append(("result", path))
        for path in self.downloads:
            if path.exists():
                out.append(("download", path))
        if self.workspace is not None and self.workspace.exists():
            out.append(("workspace", self.workspace))
        return out
