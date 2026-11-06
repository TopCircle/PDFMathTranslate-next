"""Per-file quality presentation for the GUI batch."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict


class FileQuality(TypedDict):
    status: str | None
    warning_count: int
    report_path: str | None


def quality_message(status: str | None, *, warning_count: int) -> str:
    """User-facing batch text. Failed is not a completion message."""
    if status == "success":
        return "翻译完成"
    if status == "degraded":
        return f"文件已生成，{warning_count} 项需复核"
    if status is None:
        return "文件已生成，未提供质量报告"
    raise ValueError(f"quality status {status} is not a completion message")


def summarize_batch_quality(items: Sequence[FileQuality]) -> tuple[str | None, int]:
    """Aggregate status and warning total. Empty input is not success."""
    if not items:
        return None, 0
    warning_count = sum(int(item["warning_count"]) for item in items)
    statuses = [item["status"] for item in items]
    if any(status == "failed" for status in statuses):
        return "failed", warning_count
    if any(status == "degraded" for status in statuses):
        return "degraded", warning_count
    if any(status is None for status in statuses):
        return None, warning_count
    return "success", warning_count
