"""单元测试：InspectionRepository 与数据仓储适配器 (TDD)"""

import os
import sys
import unittest

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from food_inspection.repository import (
    InMemoryInspectionAdapter,
    InspectionRepository,
    MySQLInspectionAdapter,
    get_current_repository,
)


class TestInspectionRepository(unittest.TestCase):
    """测试 InspectionRepository Seam 与两套适配器"""

    def setUp(self):
        self.in_memory_repo = InMemoryInspectionAdapter()
        self.mysql_repo = MySQLInspectionAdapter()

    def test_repository_implements_protocol(self):
        """验证 InMemoryInspectionAdapter 与 MySQLInspectionAdapter 均符合协议契约"""
        self.assertTrue(isinstance(self.in_memory_repo, InspectionRepository))
        self.assertTrue(isinstance(self.mysql_repo, InspectionRepository))

    def test_adapter_is_mysql_flags(self):
        """验证两套适配器的 is_mysql 标识符合预期"""
        self.assertFalse(self.in_memory_repo.is_mysql)
        self.assertTrue(self.mysql_repo.is_mysql)

    def test_get_scan_info_seam(self):
        """验证 get_scan_info 统一暴露在仓储接口上"""
        info_mem = self.in_memory_repo.get_scan_info()
        self.assertIsInstance(info_mem, dict)
        info_sql = self.mysql_repo.get_scan_info()
        self.assertIsInstance(info_sql, dict)

    def test_in_memory_adapter_search_records(self):
        """测试内存检索的基本分页与结构"""
        res = self.in_memory_repo.search_records(
            status="qualified",
            province="全部",
            city="全部",
            page=1,
            page_size=20,
        )
        self.assertIn("items", res)
        self.assertIn("total", res)
        self.assertIn("page", res)
        self.assertIn("page_size", res)
        self.assertIn("total_pages", res)
        self.assertEqual(res["page"], 1)
        self.assertEqual(res["page_size"], 20)

    def test_in_memory_adapter_stats(self):
        """测试总体统计接口返回格式"""
        res = self.in_memory_repo.get_stats()
        self.assertIn("qualified_count", res)
        self.assertIn("unqualified_count", res)

    def test_in_memory_adapter_overview_chart(self):
        """测试概览图表接口返回"""
        res = self.in_memory_repo.get_overview_chart(province="全部", city="全部")
        self.assertIsInstance(res, dict)
        self.assertIn("date_from", res)
        self.assertIn("date_to", res)

    def test_in_memory_adapter_company_stats(self):
        """测试企业主体统计接口"""
        res_empty = self.in_memory_repo.get_company_stats(keyword="")
        self.assertEqual(res_empty["total"], 0)
        self.assertEqual(res_empty["items"], [])

    def test_get_current_repository_factory(self):
        """测试仓储工厂函数返回有效对象"""
        active_repo = get_current_repository()
        self.assertIsNotNone(active_repo)
        self.assertTrue(isinstance(active_repo, InspectionRepository))
        self.assertIsInstance(active_repo.is_mysql, bool)


if __name__ == "__main__":
    unittest.main()
