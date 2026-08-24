"""统一食品分类、归一化与清洗引擎 (TaxonomyEngine)

深模块 (Deep Module)：
- 小接口 (Small Interface)：对外暴露 classify()、is_junk()、canonical_tableware() 与 SQL 表达式生成器。
- 深实现 (Deep Implementation)：内部封装 SC 许可目录、农产品/餐具规则、垃圾标记过滤与多级大类推导。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from food_inspection.category_junk import (
    MYSQL_CATEGORY_JUNK_REGEXP,
    _CATEGORY_COMPACT_DATE_RE,
    _CATEGORY_DATE_IN_TEXT_RE,
    _CATEGORY_DATETIME_RE,
    _CATEGORY_JUNK_MARKERS,
    _CATEGORY_JUNK_RE,
    is_junk_category,
)
from food_inspection.category_sql import (
    MYSQL_CATEGORY_ALIAS_EXPR,
    MYSQL_CATEGORY_EXPR,
)
from food_inspection.product_super_category import propose_super_category
from food_inspection.product_taxonomy import (
    SUBCLASS_SYNONYMS,
    SUBCLASS_TO_MAJOR,
    match_standard_subclass,
    resolve_major_category,
)


@dataclass(frozen=True)
class ClassificationResult:
    """分类与标准化结果"""

    super_category: str  # 超级大类（如：水果类、蔬菜类、肉制品、餐饮具等）
    major_category: str  # 标准大类（如：食用农产品、糕点、餐饮食品等）
    sub_category: str  # 标准小类（如：大米、猪肉、苹果、复用餐饮具）
    normalized_product: str  # 清洗后的产品名称
    is_junk: bool  # 是否为无效/垃圾记录
    is_tableware: bool  # 是否为餐饮具


# 餐饮具关键字与排除词
_TABLEWARE_KEYWORDS: tuple[str, ...] = (
    "碗", "筷", "碟", "盘", "勺", "盆", "餐饮具", "餐具", "骨碟", "菜碟",
    "汤碗", "饭碗", "面碗", "菜碗", "料碗", "蘸料碟", "消毒", "复用",
    "阴离子合成洗涤剂", "密胺", "仿瓷", "Melamine"
)
_TABLEWARE_EXCLUDE: tuple[str, ...] = (
    "大米", "盘锦", "牛腩", "烧鸭", "叉烧", "披萨", "比萨", "套餐",
    "宽粉", "火锅", "麻辣烫", "茶叶", "食用油", "菜籽", "坚果"
)


class TaxonomyEngine:
    """分类与清洗引擎（单例/类方法聚合）"""

    @classmethod
    def is_junk(cls, category: str | None) -> bool:
        """检查分类字段是否为误入的日期、批号或表头等垃圾数据"""
        return is_junk_category(category)

    @classmethod
    def is_tableware(cls, product_name: str, category: str = "") -> bool:
        """判断是否为餐饮具相关记录"""
        combined = f"{product_name} {category}".strip()
        if any(ex in combined for ex in _TABLEWARE_EXCLUDE):
            return False
        return any(kw in combined for kw in _TABLEWARE_KEYWORDS)

    @classmethod
    def canonical_tableware_name(cls, product_name: str) -> str:
        """将餐具类名称规范化（如各类饭碗、菜碟等统一归为'复用餐饮具'）"""
        if not product_name:
            return ""
        text = str(product_name).strip()
        text = re.sub(r"[.。…,:;，；\s]+$", "", text).strip()
        if not any(ex in text for ex in _TABLEWARE_EXCLUDE) and any(kw in text for kw in _TABLEWARE_KEYWORDS):
            return "复用餐饮具"
        return text

    @classmethod
    def classify(
        cls,
        product_name: str,
        raw_category: str = "",
        license_no: str = "",
    ) -> ClassificationResult:
        """对单条食品记录进行全面分类与清洗"""
        clean_product_name = (product_name or "").strip()
        clean_category = (raw_category or "").strip()

        # 1. 垃圾数据检测
        is_junk = cls.is_junk(clean_category)

        # 2. 餐饮具特殊处理
        if cls.is_tableware(clean_product_name, clean_category):
            normalized_product = cls.canonical_tableware_name(clean_product_name)
            return ClassificationResult(
                super_category="餐饮具",
                major_category="餐饮具",
                sub_category="复用餐饮具",
                normalized_product=normalized_product,
                is_junk=is_junk,
                is_tableware=True,
            )

        # 3. 标准小类与大类匹配
        subclass_match = match_standard_subclass(clean_product_name, original=clean_product_name)
        standard_sub_category = subclass_match[0] if subclass_match else ""

        if standard_sub_category:
            standard_major_category, _ = resolve_major_category(
                standard_sub_category, original=clean_product_name
            )
        elif clean_category and not is_junk:
            standard_major_category, _ = resolve_major_category(
                clean_category, original=clean_product_name
            )
        else:
            standard_major_category = "未分类"

        # 4. 超级大类推导
        standard_super_category, _ = propose_super_category(
            standard_sub_category,
            major=standard_major_category,
            original=clean_product_name,
        )

        return ClassificationResult(
            super_category=standard_super_category,
            major_category=standard_major_category,
            sub_category=standard_sub_category or clean_product_name,
            normalized_product=clean_product_name,
            is_junk=is_junk,
            is_tableware=False,
        )

    @classmethod
    def get_sql_category_expr(cls) -> str:
        """获取用于 MySQL 查询的食品大类 CASE 表达式"""
        return MYSQL_CATEGORY_EXPR

    @classmethod
    def get_sql_category_alias_expr(cls) -> str:
        """获取用于 MySQL 快速别名映射的 CASE 表达式"""
        return MYSQL_CATEGORY_ALIAS_EXPR
