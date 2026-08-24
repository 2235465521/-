"""单元测试：TaxonomyEngine 分类与清洗引擎"""

import os
import sys
import unittest

# 确保 backend 路径在 sys.path 中
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from food_inspection.taxonomy import TaxonomyEngine


class TestTaxonomyEngine(unittest.TestCase):
    """测试 TaxonomyEngine 的小接口与深实现"""

    def test_junk_category_detection(self):
        """测试误入 category 列的表头与日期等垃圾值识别"""
        self.assertTrue(TaxonomyEngine.is_junk("生产日期"))
        self.assertTrue(TaxonomyEngine.is_junk("购进日期"))
        self.assertTrue(TaxonomyEngine.is_junk("2024-05-01"))
        self.assertTrue(TaxonomyEngine.is_junk("2023.12.01"))
        self.assertTrue(TaxonomyEngine.is_junk("20240101"))
        self.assertFalse(TaxonomyEngine.is_junk("食用农产品"))
        self.assertFalse(TaxonomyEngine.is_junk("粮食加工品"))

    def test_tableware_normalization(self):
        """测试餐具类产品的识别与归一化为'复用餐饮具'"""
        self.assertTrue(TaxonomyEngine.is_tableware("饭碗"))
        self.assertTrue(TaxonomyEngine.is_tableware("消毒骨碟"))
        self.assertEqual(TaxonomyEngine.canonical_tableware_name("饭碗"), "复用餐饮具")
        self.assertEqual(TaxonomyEngine.canonical_tableware_name("密胺骨碟"), "复用餐饮具")
        # 排除项不应被误判为餐饮具
        self.assertFalse(TaxonomyEngine.is_tableware("盘锦大米"))
        self.assertEqual(TaxonomyEngine.canonical_tableware_name("盘锦大米"), "盘锦大米")

    def test_classify_standard_food(self):
        """测试标准食品的分类结果"""
        res = TaxonomyEngine.classify("东北大米")
        self.assertEqual(res.major_category, "粮食加工品")
        self.assertEqual(res.sub_category, "大米")
        self.assertEqual(res.super_category, "粮油类")
        self.assertFalse(res.is_junk)
        self.assertFalse(res.is_tableware)

    def test_classify_agricultural_product(self):
        """测试食用农产品的分类结果"""
        res = TaxonomyEngine.classify("红富士苹果")
        self.assertEqual(res.major_category, "食用农产品")
        self.assertEqual(res.sub_category, "苹果")
        self.assertEqual(res.super_category, "水果类")
        self.assertFalse(res.is_junk)

    def test_classify_tableware(self):
        """测试餐饮具的分类结果"""
        res = TaxonomyEngine.classify("汤碗", raw_category="餐饮具")
        self.assertTrue(res.is_tableware)
        self.assertEqual(res.normalized_product, "复用餐饮具")
        self.assertEqual(res.super_category, "餐饮具")

    def test_sql_expression_generation(self):
        """测试 SQL CASE 表达式生成"""
        sql = TaxonomyEngine.get_sql_category_expr()
        self.assertIn("CASE", sql)
        self.assertIn("食用农产品", sql)
        self.assertIn("餐饮具", sql)


if __name__ == "__main__":
    unittest.main()
