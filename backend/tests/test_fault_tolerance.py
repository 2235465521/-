"""单元测试：容错性与异常边界测试 (Fault Tolerance & Resilience Tests)"""

import os
import sys
import unittest

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from food_inspection.date_scope import _parse_iso_date, filter_records_by_date_range
from food_inspection.repository import InMemoryInspectionAdapter, get_current_repository
from food_inspection.web.routes import _safe_int


class TestFaultTolerance(unittest.TestCase):
    """测试系统在畸形输入、空值、极端边界下的容错能力"""

    def setUp(self):
        self.repo = InMemoryInspectionAdapter()

    def test_safe_int_parsing(self):
        """测试 _safe_int 面对非数字、None、越界参数时的安全解析"""
        self.assertEqual(_safe_int("123", default=1), 123)
        self.assertEqual(_safe_int("invalid_string", default=1), 1)
        self.assertEqual(_safe_int(None, default=50), 50)
        self.assertEqual(_safe_int("", default=10), 10)
        # 测试 min/max 边界限制
        self.assertEqual(_safe_int("-10", default=1, min_val=1), 1)
        self.assertEqual(_safe_int("999999", default=50, max_val=500), 500)

    def test_date_parsing_fault_tolerance(self):
        """测试畸形日期格式不会触发异常崩溃"""
        from datetime import date

        # 正常 ISO
        self.assertEqual(_parse_iso_date("2024-05-01", date(2000, 1, 1)), date(2024, 5, 1))
        # 仅年份文本提取
        self.assertEqual(_parse_iso_date("2024年公告", date(2000, 1, 1)), date(2024, 1, 1))
        # 纯乱码字符串回退为 default
        self.assertEqual(_parse_iso_date("not-a-date", date(2000, 1, 1)), date(2000, 1, 1))
        self.assertEqual(_parse_iso_date(None, date(2000, 1, 1)), date(2000, 1, 1))

    def test_filter_records_with_malformed_dates(self):
        """测试带畸形日期的记录列表筛选不会抛出异常"""
        records = [
            {"source_file": "Z:\\浙江省\\杭州市\\2024\\01号公告.xlsx", "product": "大米"},
            {"source_file": "invalid_path_without_year.xlsx", "product": "苹果"},
        ]
        # 传入畸形 date_from
        res = filter_records_by_date_range(records, date_from="invalid_date", date_to="2024-12-31")
        self.assertIsInstance(res, list)

    def test_search_records_empty_and_extreme_params(self):
        """测试在空数据和极端分页参数下的查询鲁棒性"""
        res = self.repo.search_records(
            status="qualified",
            province="不存在的省份",
            city="不存在的城市",
            page=9999,
            page_size=100,
            date_from="bad_date",
            date_to="bad_date",
        )
        self.assertEqual(res["items"], [])
        self.assertEqual(res["total"], 0)
        self.assertEqual(res["page"], 9999)

    def test_city_insights_missing_province(self):
        """测试获取城市洞察时的容错输出"""
        res = self.repo.get_city_insights(province="未知省份", city="未知城市", limit=10)
        self.assertIsInstance(res, dict)
        self.assertIn("province", res)

    def test_company_stats_special_characters(self):
        """测试包含特殊符号与 SQL 注入特征字符时的查询容错"""
        res = self.repo.get_company_stats(keyword="'; DROP TABLE test; --")
        self.assertIsInstance(res, dict)
        self.assertEqual(res["total"], 0)


if __name__ == "__main__":
    unittest.main()
