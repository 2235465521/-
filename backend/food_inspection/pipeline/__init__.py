"""统一解析 → 校验 → 纠错 → 入库管道。"""

from food_inspection.pipeline.guard import guard_file_records, guard_record, parse_file_guarded
from food_inspection.pipeline.runner import PipelineResult, run_parse_pipeline

__all__ = [
    "PipelineResult",
    "guard_file_records",
    "guard_record",
    "parse_file_guarded",
    "run_parse_pipeline",
]
