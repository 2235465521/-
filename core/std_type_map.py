"""标准类型大类映射。

依据 STSC_standard_database.std_base.std_type_no 的真实取值（共 6 类）建立映射，
把零散的 std_type 代号（GB/T、JB/T、DB、T、ISO、IEC …）归并到上层大类：

    00 -> 国家标准
    01 -> 行业标准（可进一步按 std_type 细分为 JB/T、YD/T …）
    02 -> 地方标准
    03 -> 团体标准
    04 -> ISO
    05 -> IEC

该映射已用线上备份（STSC_standard_database_backup_2026-07-19）全量核对：
`SELECT std_type_no, std_type, COUNT(*) ... GROUP BY 1,2` 仅产出这 6 个 std_type_no，
每个代号都能稳定归到对应大类。
"""

from __future__ import annotations

# std_type_no -> 大类中文名
STD_TYPE_NO_CATEGORY: dict[str, str] = {
    "00": "国家标准",
    "01": "行业标准",
    "02": "地方标准",
    "03": "团体标准",
    "04": "ISO",
    "05": "IEC",
}

# 数据里 std_type_no 偶尔为空 / 非法值时的兜底
STD_TYPE_UNKNOWN = "其他"


def std_type_category(std_type_no: str | None) -> str:
    """把 std_type_no（如 '00'）映射为大类名；未知 / 空 -> '其他'。"""
    if std_type_no is None:
        return STD_TYPE_UNKNOWN
    return STD_TYPE_NO_CATEGORY.get(str(std_type_no).strip(), STD_TYPE_UNKNOWN)
