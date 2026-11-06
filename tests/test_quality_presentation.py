"""Quality copy stays a pure function and does not start Gradio."""

import pytest


def test_quality_message_maps_completion_and_rejects_failed():
    from pdf2zh_next.quality import quality_message

    assert quality_message("success", warning_count=0) == "翻译完成"
    assert quality_message("degraded", warning_count=1) == "文件已生成，1 项需复核"
    assert quality_message("degraded", warning_count=3) == "文件已生成，3 项需复核"
    assert quality_message(None, warning_count=0) == "文件已生成，未提供质量报告"
    with pytest.raises(ValueError):
        quality_message("failed", warning_count=0)


def test_summarize_batch_quality_priority_and_empty_collection():
    from pdf2zh_next.quality import summarize_batch_quality

    success = {"status": "success", "warning_count": 0, "report_path": None}
    degraded = {"status": "degraded", "warning_count": 1, "report_path": "a.json"}
    other = {"status": "degraded", "warning_count": 4, "report_path": "b.json"}
    unknown = {"status": None, "warning_count": 0, "report_path": None}
    failed = {"status": "failed", "warning_count": 2, "report_path": None}

    assert summarize_batch_quality([]) == (None, 0)
    assert summarize_batch_quality([success, success]) == ("success", 0)
    assert summarize_batch_quality([success, degraded]) == ("degraded", 1)
    assert summarize_batch_quality([degraded, other]) == ("degraded", 5)
    assert summarize_batch_quality([degraded, unknown]) == ("degraded", 1)
    assert summarize_batch_quality([unknown, success]) == (None, 0)
    assert summarize_batch_quality([failed, degraded]) == ("failed", 3)
