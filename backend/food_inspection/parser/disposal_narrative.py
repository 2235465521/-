"""核查处置 / 风险控制通告正文解析（东莞、浙江等地叙述型不合格公示）。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from food_inspection.parser.fields import (
    _extract_location_from_path,
    _extract_year_from_path,
    _merge_location,
    looks_like_inspection_item_not_product,
    normalize_failure_item_name,
    sanitize_product_name,
)
from food_inspection.parser.io import _read_all_sheets
from food_inspection.parser.models import Record
from food_inspection.parser.text import _clean, is_invalid_company, normalize_company_name, normalize_product_name


@dataclass
class _NarrativeCase:
    company: str
    products: list[str]
    unqualified_item: str


_TRIGGER_PATTERNS = (
    re.compile(r"(?:现将[^。；\n]{0,20}批?)?(?:核查处置|风险控制)情况通告如\s*下?\s*[：:]?"),
    re.compile(r"情况通告如\s*下?\s*[：:]?"),
    re.compile(r"通告如\s*下?\s*[：:]?"),
    re.compile(r"(?:核查处置|风险控制)(?:及信息)?情况(?:公告|公示)?如\s*下?\s*[：:]?"),
)
_ZJ_TRIGGER_MARKERS = (
    "抽检基本情况",
    "核查处置及信息情况",
    "检验结论为不合格",
    "项目不符合",
)
_ZJ_ENTITY_TAIL = (
    r"有限公司|有限责任公司|商贸有限公司|食品有限公司|"
    r"厂|企业|超市|商店|水果店|蔬菜店|生鲜店|餐饮店|小吃店|"
    r"食品店|小食杂店|调味品摊|腌制品店|加盟店|小餐饮店|"
    r"商贸公司|食品厂|酒店有限公司|大酒店有限公司|"
    r"经营部|炒货店|副肉店|活鱼摊|果品经营部|水果商行|"
    r"副食品店|食品经营部|小食杂|农贸市场|蔬菜摊|"
    r"贸易商行|分公司|活鱼摊|副肉摊|食品商行|"
    r"批发部|火锅店|餐饮店|副食店|生鲜商行|商行|豆腐作坊|生鲜店"
)
_ZJ_ENTITY_FULL = (
    rf"([\u4e00-\u9fff\*·]{{2,55}}(?:{_ZJ_ENTITY_TAIL})"
    rf"|个体户[\u4e00-\u9fff\*·]{{1,12}}"
    rf"|个体工商户[\u4e00-\u9fff\*·]{{1,20}})"
)
_ZJ_ENTITY_LOOSE = (
    rf"({_ZJ_ENTITY_FULL[1:-1]}|"
    rf"[\u4e00-\u9fff·]{{2,30}}(?:市场|商场)[\u4e00-\u9fff·]{{1,10}}|"
    rf"[\u4e00-\u9fff·]{{2,20}})"
)
_COMPANY = re.compile(
    rf"(?:标称)?((?:东莞市|广东省)?[^生、，。；\n]+?(?:有限公司|有限责任公司|公司|企业|食品厂|厂))(?:委托)?生产的"
)
_QUOTED_PRODUCTS = re.compile(r"[「『“\"]([^」』”\"]+)[」』”\"]")
_PRODUCT_QUOTED = re.compile(r"生产的[「『“\"]([^」』”\"]+)[」』”\"]")
_PRODUCT_BEFORE_TRADEMARK = re.compile(
    r"(?:生产的|、)((?:[^（标称“\"「]){2,30}?)（商标[：:]"
)
_SECTION_MARKER = re.compile(r"[一二三四五六七八九十百]+、")
_RE_ZJ_FOOD_NAME = re.compile(r"食品名称[：:]\s*([^；;。\n]+?)(?:;|；|。|$|该食品|检验结论)")
_RE_ZJ_SOLD = re.compile(
    rf"(?:本局对|依法对|[^，。；]{{0,25}}局对)?{_ZJ_ENTITY_FULL}(?:销售|经营|在售|生产经营|生产)的"
    r"([^（(进行，。；;\n]+?)(?:进行|[（(]|,|，|。|\.)"
)
_RE_ZJ_OPERATED = re.compile(
    r"经营[的](?:\d+批次)?([^，。；（]+?)，"
    r"(?:经抽样检验，)?([^，。；]+?)项目不符合"
)
_RE_ZJ_SALE_TIGHT = re.compile(
    r"([\u4e00-\u9fff·]{3,40})销售[的](?P<product>[^，。；]+?)"
    r"(?P<item>[^，。；]+?)项目不符合"
)
_ZJ_ENTITY_INNER = (
    rf"[\u4e00-\u9fff\*·]{{2,55}}(?:{_ZJ_ENTITY_TAIL})"
    rf"|个体户[\u4e00-\u9fff\*·]{{1,12}}"
    rf"|个体工商户[\u4e00-\u9fff\*·]{{1,20}}"
)
# 台州等：王挺春销售的山药氯氟氰菊酯…；台州市XX有限公司销售的鸭蛋，多西环素…
_RE_ZJ_COMPACT_SALE_CHAIN = re.compile(
    rf"(?:(?P<company>{_ZJ_ENTITY_INNER})|超标(?P<person>[\u4e00-\u9fff]{{2,4}})|[。；;](?P<person_tail>[\u4e00-\u9fff]{{2,4}}))"
    r"销售(?:的)?"
    r"(?P<body>[^。；]+?)"
    r"项目不符合(?:食品安全)?(?:国家标准)?(?:规定)?"
)
_NARRATIVE_CATEGORY_PREFIXES = (
    "农药残留超标",
    "农药残留量超标",
    "重金属污染物超标",
    "重金属超标",
    "超限量使用食品添加剂",
    "微生物污染超标",
    "有机物污染超标",
    "兽药残留超标",
    "生物毒素污染超标",
    "质量指标超标",
    "质量指标不合格",
    "其他污染物超标",
)
_NARRATIVE_CATEGORY_ITEMS = frozenset(_NARRATIVE_CATEGORY_PREFIXES)
_RE_ZJ_SECTION_ENTITY = re.compile(
    rf"[一二三四五六七八九十百]+、\s*({_ZJ_ENTITY_LOOSE[1:-1]})"
)
_RE_ZJ_NUMBERED = re.compile(
    rf"\d+、{_ZJ_ENTITY_FULL}销售的(?:抽样单编号为[^，]*?)的([^，,]+?)，"
    r"([^，。]+?)项目不符合"
)
_RE_ZJ_TOP_CASE = re.compile(
    rf"([一二三四五六七八九十百]+)、(?={_ZJ_ENTITY_FULL}|[\u4e00-\u9fff]{{2,8}}经营部|个体户)"
)
_RE_ZJ_OPERATE_HEADER = re.compile(
    rf"^[一二三四五六七八九十百]+、\s*{_ZJ_ENTITY_FULL}经营的\s*([^（(\n]+?)\s*[（(]"
)
_RE_ZJ_ABOUT = re.compile(r"现将有关([\u4e00-\u9fff\*·]{2,55}?)抽检")
_RE_ZJ_QUOTED_FAIL = re.compile(r"[“\"「]([^”\"」]+)[”\"」]项目不符合")
_RE_ZJ_ITEM_FAIL = re.compile(r"([\u4e00-\u9fffA-Za-z（）()·\-]+?)项目不符合")
_RE_NINGBO_HEADER = re.compile(
    r"^[一二三四五六七八九十百]+、(.+?)(?:购进|销售)[的]?([^（(]+?)(?:[（(]|$)"
)
_RE_INSPECTION_ITEM = re.compile(r"抽检项目中(.+?)项目不符合")
_RE_ZJ_BASIC_INSPECTION = re.compile(
    r"抽检基本情况"
    r"(.+?)"
    r"(?:销售|经营|进购|购进)的"
    r"([^，。；]+?)"
    r"，"
    r"([^，。；]+?)(?:项目)?不符合"
)
_RE_ZJ_SALE_INSPECT = re.compile(
    r"抽检基本情况"
    r"(.+?)销售[的]?"
    r"([^经，。；]+?)"
    r"经抽样检验[，,]?"
    r"([^，。；]+?)(?:项目)?不符合"
)
# 宁波等：购进/销售的YY，抽检项目中ZZ项目不符合
_RE_ZJ_PROJECT_ITEM = re.compile(
    r"抽检基本情况"
    r"(.+?)"
    r"(?:销售|经营|进购|购进)的"
    r"([^，。；]+?)"
    r"，抽检项目中"
    r"([^，。；]+?)(?:项目)?不符合"
)
# 余姚等生产环节：XX生产的YY，ZZ项目不符合
_RE_ZJ_PRODUCE_ITEM = re.compile(
    r"抽检基本情况"
    r"(.+?)生产的"
    r"([^，。；]+?)"
    r"，"
    r"([^，。；]+?)(?:项目)?不符合"
)
# 湖州吴兴等：公司名…对当事人/本单位销售的YY…经抽样检验，ZZ项目不符合
_RE_ZJ_HUZHOU = re.compile(
    r"([^\d。；]{2,60}?(?:有限公司|公司|超市|火锅店|小吃店|食品厂|蔬菜有限公司|商行|水果店|豆腐作坊|经营部|副食店|蔬菜店))"
    r"抽检基本情况。"
    r".{0,400}?"
    r"对(?:当事人|\1)(?:销售|使用|经营|生产)的"
    r"([^进，。；]+?)(?:进行(?:食品安全)?监督抽检|进行检测)。"
    r".{0,200}?"
    r"经抽样检验，"
    r"(?:[^，。；]{1,24}的)?"
    r"([^，。；]+?)(?:项目)?不符合"
)
# 北仑等：对XX监督抽检，抽样人员抽取YY，该批次YY的ZZ项目不符合
_RE_ZJ_DRAWN_SAMPLE = re.compile(
    r"对(.+?)进行(?:食品安全)?监督抽检。"
    r"抽样人员(?:现场随机)?抽取了"
    r"(.+?)"
    r"(?:（购进日期|，样品)"
    r".{0,280}?"
    r"(?:该批次)?\2的"
    r"([^，。；]+?)(?:项目)?不符合"
)
# 北仑餐饮等：该批次鸡蛋的检验项目氟苯尼考实测值…不符合
_RE_ZJ_DRAWN_ITEM_VALUE = re.compile(
    r"对(.+?)进行(?:食品安全)?监督抽检。"
    r"抽样人员(?:现场随机)?抽取了"
    r"(.+?)"
    r"(?:（购进日期|，样品)"
    r".{0,360}?"
    r"该批次\2的检验项目"
    r"([^实，。；]+?)实测值"
)
# 舟山等：XX销售/经营的1批次YY的ZZ项目不符合
_RE_ZJ_SALE_BATCH = re.compile(
    r"抽检基本情况"
    r"([\u4e00-\u9fff（）()·\*]{3,75}?)(?:（个体工商户）|（蛟头集贸市场）)?"
    r"(?:销售|经营)的(?:\d+批次)?"
    r"(?:"
    r"([^，。；]+?)，经抽样检验，(.+?)(?:项目)?不符合"
    r"|"
    r"([^的，。；]+?)的([^，。；]+?)(?:项目)?不符合"
    r"|"
    r"([^，。；]+?)，([^，。；]+?)(?:项目)?不符合"
    r")"
)
# 湖州吴兴等：个人/摊位名…对XX销售的YY
_RE_ZJ_HUZHOU_LOOSE = re.compile(
    r"([^\d。；]{2,35})"
    r"抽检基本情况。"
    r".{0,420}?"
    r"对(?:当事人|\1)销售的"
    r"([^进，。；]+?)进行(?:食品安全)?监督抽检。"
    r"经抽样检验，"
    r"(?:[^，。；]{1,40}的)?"
    r"([^，。；]+?)(?:项目)?不符合"
)
# 湖州南浔等：当事人：XX…检验结果为：YY中ZZ项目不符合
_RE_ZJ_NANXUN_PARTY = re.compile(
    r"当事人[：:]\s*([^，；。\d]+?)(?:，系个体工商户)?[。；]"
    r".{0,360}?"
    r"(?:对当事人经营的)?([^进。；]+?)进行了抽检。"
    r"检验结果为："
    r"([^中]+?)中"
    r"([^，。；]+?)(?:项目)?不符合"
)
# 绍兴个体户：个体工商户李龙琪当天销售的该批次的土豆…ZZ项目不合格土豆
_RE_ZJ_INDIVIDUAL_SOLD = re.compile(
    r"个体工商户([^当]+?)当天销售的该批次的([^，。；]+?)进行了抽验"
    r".{0,480}?"
    r"([^，。；]+?)(?:项目)?不合格\2"
)
# 宁波市局简表：XX生产的YY,ZZ不符合标准要求
_RE_ZJ_COMPACT_FAIL = re.compile(
    r"抽检基本情况"
    r"([\u4e00-\u9fff（）()·\*]{3,55}?(?:有限公司|公司|食品厂|餐饮店|小吃店|超市|商行|作坊|饭店))"
    r"(?:生产|销售)的"
    r"([^,，]+)"
    r"[,，]"
    r"([^,，。；]+?)(?:项目)?不符合(?:食品)?标准"
)
# 镇海等：抽检基本情况XX生产销售的YY，ZZ项目不符合
_RE_ZJ_PRODUCE_SALE_INLINE = re.compile(
    r"抽检基本情况"
    r"([\u4e00-\u9fff（）()·\*]{3,55}?(?:有限公司|公司|食品厂|餐饮店|小吃店|超市|商行|生鲜店|蔬菜店))"
    r"生产销售的?"
    r"(.+?)"
    r"([\u4e00-\u9fff（）()·\-,]+?)项目不符合"
)
# 绍兴生产追溯：在售的YY…由XX生产
_RE_ZJ_PRODUCED_BY = re.compile(
    r"在售的([^（(，。；]+?)"
    r"(?:[（(][^）)]*[）)])?"
    r"进行监督抽检，"
    r"该\1经[^，。]+检验，"
    r"([^，。；]+?)(?:项目)?不符合"
    r".{0,200}?"
    r"该\1由(.+?)生产"
)
# 绍兴销售抽检：依法对XX销售的YY进行食品安全监督抽检
_RE_ZJ_SALE_SUPERVISE = re.compile(
    r"依法对(.+?)销售的([^进行]+?)进行食品安全监督抽检。"
    r".{0,280}?"
    r"([^，。；]+?)(?:项目)?不符合"
)
# 绍兴当事人经营：当事人X月X日经营的YY
_RE_ZJ_PARTY_OPERATED = re.compile(
    r"当事人\d{4}年\d{1,2}月\d{1,2}日(?:经营|销售)的([^，。；]+?)，"
    r".{0,240}?"
    r"经抽样检验，([^，。；\"]+?)(?:项目)?不符合"
)
# 绍兴地址定位：对位于…的XX采购的YY
_RE_ZJ_LOCATE_PURCHASE = re.compile(
    r"对位于[^的]{10,120}?的(.+?)"
    r"采购的([^进行]+?)进行抽样检验"
    r".{0,320}?"
    r"经抽样检验，"
    r"([^，。；]+?)(?:项目)?不符合"
)
# 温州结构化字段体
_RE_ZJ_STRUCTURED_BLOCK = re.compile(
    r"食品生产经营单位名称[：:]\s*([^。\d]+?)。"
    r".{0,240}?"
    r"食品名称[：:]\s*([^。\d]+?)。"
    r".{0,240}?"
    r"不合格项目[：:]\s*([^。\d]+?)。"
)
# 温州当事人经营龙眼等
_RE_ZJ_PARTY_PRODUCT = re.compile(
    r"抽检基本情况。"
    r".{0,160}?"
    r"对当事人经营的([^进行]+?)进行监督抽检，"
    r".{0,240}?"
    r"(?:该批次)?\1中"
    r"([^，。；]+?)(?:项目)?不符合"
)
# 舟山编号简表：1、东港市场郑林英销售的抽样单编号…的麻糍
_RE_ZJ_NUMBERED_LOOSE = re.compile(
    r"\d+、([\u4e00-\u9fff·（）()]{2,35})销售的抽样单编号为[^，]*?的([^，,]+?)，"
    r"([^，。]+?)(?:项目)?不符合"
)
# 舟山生产：XX生产的豆干，经抽样检验，ZZ项目不符合
_RE_ZJ_SECTION_PRODUCE = re.compile(
    r"抽检基本情况"
    r"([\u4e00-\u9fff（）()·\*]{3,55}?(?:有限公司|公司|食品厂|餐饮店|小吃店|超市|商行|豆腐作坊|作坊))"
    r"生产的(?:\d+批次)?"
    r"([^，。；]+?)，"
    r"经抽样检验，"
    r"(.+?)(?:项目)?不符合"
)
# 舟山经营：XX店经营的芒果经抽样检验，ZZ项目不符合
_RE_ZJ_SECTION_OPERATE = re.compile(
    r"([\u4e00-\u9fff（）()·\*]{3,60}?(?:有限公司|公司|食品厂|餐饮店|小吃店|超市|商行|店))"
    r"经营的"
    r"([^经，。；]+?)"
    r"经抽样检验，"
    r"([^，。；]+?)(?:项目)?不符合"
)
# 金华：监督管理局对XX的YY进行了监督抽检，不合格项目为ZZ
_RE_ZJ_SUPERVISE_FAIL = re.compile(
    r"(?:市场)?监督管理局对(.+?)的([^进行]+?)进行了监督抽检。"
    r"经抽检不合格项目为([^。；]+?)。"
)
# 镇海永辉等：XX的/待售的YY的ZZ项目不符合食品安全国家标准
_RE_ZJ_POSSESS_FAIL = re.compile(
    r"抽检基本情况"
    r"([\u4e00-\u9fff（）()·\*]{3,75}?)(?:（个体工商户）)?"
    r"(?:的|待售的)"
    r"([^的]{2,40}?)的"
    r"([^，。；]+?)(?:项目)?不符合(?:食品)?安全国家标准"
)
# 余姚等：抽检基本情况XX采购的YY，ZZ项目不符合标准
_RE_ZJ_PURCHASE_INLINE = re.compile(
    r"抽检基本情况"
    r"([\u4e00-\u9fff（）()·\*]{3,55}?(?:有限公司|餐饮店|酒店有限公司|饭店))"
    r"采购的"
    r"([^，。；]+?)，"
    r"([^，。；]+?)(?:项目)?不符合(?:食品)?标准"
)
# 前湾等：XX生产的YY的ZZ不符合食品安全国家标准
_RE_ZJ_PRODUCE_POSSESS = re.compile(
    r"(?:抽样|抽检)基本情况"
    r"([\u4e00-\u9fff（）()·\*]{3,55}?(?:有限公司|公司|食品厂))"
    r"生产的"
    r"([^的]{2,40}?)的"
    r"([^，。；]+?)(?:项目)?不符合(?:食品)?安全国家标准"
)
# 湖州/绍兴：当事人销售的YY，经抽样检验，ZZ不符合
_RE_ZJ_SALE_INSPECT_INLINE = re.compile(
    r"(?:当事人)?销售的([^，；]+?)，经抽样检验，([^，。；]+?)(?:项目)?不符合"
)
# 湖州等：对XX销售的YY进行监督抽检（主体可不同于标题）
_RE_ZJ_THIRD_PARTY_SALE = re.compile(
    r"对(.+?)销售的([^进]+?)进行(?:食品安全)?监督抽检。"
    r"经抽样检验，"
    r"([^，。；]+?)(?:项目)?不符合"
)
# 湖州餐厅：对XX使用的食品原料YY进行监督抽检
_RE_ZJ_USE_MATERIAL = re.compile(
    r"对(.+?)使用的食品原料([^进]+?)进行(?:食品安全)?监督抽检。"
    r"经抽样检验，"
    r"([^，。；]+?)(?:项目)?不符合"
)
# 绍兴表格体：样品名称 + 被抽样单位
_RE_ZJ_STRUCTURED_TABLE = re.compile(
    r"样品名称([^购检]{2,24}?)(?:购进|检验)"
    r".{0,120}?"
    r"被抽样单位([^检]{4,40}?)检验结论"
    r"经抽样检验，([^，。；]+?)(?:项目)?不符合"
)
# 绍兴：依法对XX采购的YY进行监督抽检
_RE_ZJ_PROCURE_SUPERVISE = re.compile(
    r"依法对(.+?)采购的([^进行]+?)进行监督抽检。"
    r".{0,360}?"
    r"([^，。；]+?)(?:项目)?不符合"
)
# 绍兴：依法对XX在售的YY进行食品安全监督抽检
_RE_ZJ_ON_SALE_DIRECT = re.compile(
    r"依法对(.+?)在售的([^进行]+?)进行食品安全监督抽检。"
    r".{0,300}?"
    r"([^，。；]+?)(?:项目)?不符合"
)
# 鄞州等：加工的馒头，甜蜜素项目不符合
_RE_ZJ_PROCESS_PRODUCT = re.compile(
    r"抽检基本情况"
    r"([\u4e00-\u9fff（）()·\*]{3,55}?(?:有限公司|个体工商户|馒头店|食品厂))"
    r"(?:（个体工商户）)?"
    r"加工的"
    r"([^，。；]+?)，"
    r"([^，。；]+?)(?:项目)?不符合"
)
# 金华等：市场摊位销售的大山药咪鲜胺项目不符合
_RE_ZJ_MARKET_INLINE_SALE = re.compile(
    r"抽检基本情况(.+?)销售的(.+?)([^不符]{2,40}?)项目不符合食品安全国家标准"
)
# 舟山等：经营的荷兰豆…残留量不符合
_RE_ZJ_RESIDUE_FAIL = re.compile(
    r"抽检基本情况"
    r"(?:位于[^的]{10,100}?的)?"
    r"([\u4e00-\u9fff（）()·\*]{3,70}?(?:经营部|蔬菜摊|水产摊|超市))"
    r"经营的"
    r"([^经，。；]+?)"
    r"经抽样检验，"
    r"(.+?)(?:的残留量)?(?:项目)?不符合"
)
# 温州：对XX水产品店经营…该店经营的鲫鱼
_RE_ZJ_SHOP_OPERATE = re.compile(
    r"对(.+?(?:水产品店|农贸市场[^经]{0,30}))经营的商品进行抽样检验"
    r"。该店经营的([^（(]+?)"
    r"（购进日期[^）]*），经检验，"
    r"([^，。；]+?)(?:项目)?不符合"
)
# 绍兴多产品检验结论
_RE_ZJ_BATCH_CONCLUSION = re.compile(
    r"此批次([^的，；]+?)的检验结论为[“\"]"
    r"经抽样检验，([^，。；\"]+?)(?:项目)?不符合"
)
# 未名太研等：生产企业为XX的YY进行了抽样
_RE_ZJ_REMOTE_PRODUCE = re.compile(
    r"生产企业为([^的]+?)的([^进进行了]+?)进行了抽样"
    r".{0,500}?"
    r"([^，。；]+?)(?:项目)?不符合"
)
# 绍兴等：对位于…的XX在售的YY抽样检验
_RE_ZJ_ON_SALE_SAMPLE = re.compile(
    r"对位于[^的]{10,120}?的(.+?)"
    r"在售的([^抽]+?)抽样检验。"
    r".{0,360}?"
    r"经抽样检验，"
    r"([^，。；]+?)(?:项目)?不符合"
)
# 绍兴摊位：对马位娟摊位销售的黄鳝
_RE_ZJ_STALL_SALE = re.compile(
    r"对(.+?)摊位销售的([^进]+?)进行了监督抽检。"
    r".{0,420}?"
    r"经抽样检验，([^，。；\"]+?)(?:项目)?不符合"
)
# 舟山供应：XX供应的猪肉经抽样检验
_RE_ZJ_SUPPLY_INSPECT = re.compile(
    r"抽检基本情况"
    r"([\u4e00-\u9fff（）()·\*]{3,55}?(?:有限公司|公司))"
    r"供应的"
    r"([^经]+?)"
    r"经抽样检验，"
    r"([^，。；]+?)(?:项目)?不符合"
)
# 绍兴超市等：当天销售的该批次的胡萝卜进行了抽验
_RE_ZJ_STORE_SOLD = re.compile(
    r"([\u4e00-\u9fff（）()·\*]{3,55}?(?:有限公司|公司|超市|经营部|餐饮店))"
    r"当天销售的该批次的([^，。；]+?)进行了抽验"
    r".{0,480}?"
    r"([^，。；]+?)(?:项目)?不合格\2"
)
# 北仑餐饮：抽取煎炸过程用油（使用日期…）
_RE_ZJ_DRAWN_USE_SAMPLE = re.compile(
    r"对(.+?)进行(?:食品安全)?监督抽检。"
    r"抽样人员(?:现场随机)?抽取了"
    r"(.+?)"
    r"（使用日期"
    r".{0,420}?"
    r"\2(?:样品)?检验项目"
    r"([^，。；]+?)(?:项目)?不符合"
)
# 北仑等：实测值超标（无“项目不符合”字样）
_RE_ZJ_DRAWN_MEASURED = re.compile(
    r"对(.+?)进行(?:食品安全)?监督抽检。"
    r"抽样人员(?:现场随机)?抽取了"
    r"(.+?)"
    r"（购进日期"
    r".{0,360}?"
    r"(?:该批次)?\2的"
    r"([^，。；]+?)(?:项目)?实测值为"
)
# 福建漳州等：编号公示正文
_RE_FJ_ITEM = re.compile(
    r"（(?:生产日期|购进日期)[^）]*）"
    r"([^，,。]+?)项目检出值"
)
_RE_ZJ_FILENAME = re.compile(
    r"关于(.+?)(?:销售|经营|生产销售|生产经营)不符合(?:国家)?食品安全标准[的之]?(.+?)核查处置"
)
_RE_ZJ_FILENAME_ABOUT = re.compile(r"关于(.+?)(?:销售|经营)")
_NAV_MARKERS = ("当前位置", "信息索引号", "政府信息公开指南", "索 引 号", "索引号")
_CAPTCHA_MARKERS = (
    "正在验证您是否是真人",
    "需要先检查您的连接的安全性",
    "网站安全防护服务",
    "MethodNotAllowed",
    "405-MethodNotAllowed",
)
_ENTITY_PREFIX = re.compile(
    r"^[^，。；]*?(?:本局对|依法对|执法人员对|[^，。；]{0,20}监督管理局对|[^，。；]{0,20}局对)"
)


def _is_disposal_narrative_file(filepath: str) -> bool:
    name = os.path.basename(filepath)
    lower = name.lower()
    is_zhengwen = "_正文." in lower or lower.endswith(("_正文.xlsx", "_正文.xls", "_正文.pdf"))
    if "核查处置" in name or "风险控制" in name:
        return lower.endswith(".pdf") or is_zhengwen
    if is_zhengwen:
        return any(
            k in name
            for k in (
                "监督抽检情况",
                "抽检情况",
                "抽检不合格",
                "不合格食品",
                "你点我检",
            )
        )
    return False


def is_skippable_disposal_zhengwen(filepath: str, text: str | None = None) -> bool:
    """结构化网页核查处置正文（如台州黄岩【食品安全】字段体），不做入库。"""
    if not _is_disposal_narrative_file(filepath):
        return False
    name = os.path.basename(filepath)
    if "【食品安全】" in name:
        return True
    if text is None:
        text = extract_disposal_narrative_text(filepath)
    compact = re.sub(r"\s+", "", text)
    if (
        ("食品名称：" in compact or "食品名称:" in compact)
        and "进购日期" in compact
        and "抽样日期" in compact
    ):
        return True
    return False


def _pdf_text_via_ocr(filepath: str, max_pages: int = 20) -> str:
    from food_inspection.parser.io import (
        _pdf_cluster_ocr_boxes,
        _pdf_merge_ocr_row,
        _pdf_open_fitz,
        _pdf_run_rapidocr,
    )

    chunks: list[str] = []
    try:
        doc = _pdf_open_fitz(filepath)
        if doc is not None:
            for i in range(min(len(doc), max_pages)):
                page = doc[i]
                text = (page.get_text() or "").strip()
                if text:
                    chunks.append(text)
                    continue
                for row in _pdf_cluster_ocr_boxes(_pdf_run_rapidocr(page, fast=True) or []):
                    line = "".join(_pdf_merge_ocr_row(row))
                    if line:
                        chunks.append(line)
            doc.close()
            return "\n".join(chunks)
    except Exception:
        pass

    try:
        import pdfplumber
    except ImportError:
        return ""

    try:
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages[:max_pages]:
                text = (page.extract_text() or "").strip()
                if text:
                    chunks.append(text)
                    continue
                result = _pdf_run_rapidocr(page, fast=True)
                if not result:
                    continue
                for row in _pdf_cluster_ocr_boxes(result):
                    line = "".join(_pdf_merge_ocr_row(row))
                    if line:
                        chunks.append(line)
    except Exception:
        return ""
    return "\n".join(chunks)


def extract_disposal_narrative_text(filepath: str) -> str:
    ext = os.path.splitext(filepath)[1].lower()
    if ext in (".xlsx", ".xls"):
        parts: list[str] = []
        for _sheet, rows, sheet_text in _read_all_sheets(filepath):
            row_text = "".join(_clean(c) for row in rows for c in row if _clean(c))
            preview = sheet_text or ""
            if (
                len(row_text) > len(preview) * 1.2
                or "抽检基本情况" in row_text
                or re.search(r"[一二三四五六七八九十百]+、.+?(?:购进|销售)[的]", row_text)
            ):
                parts.append(row_text)
            elif preview:
                parts.append(preview)
            else:
                parts.append(row_text)
        return "".join(parts)
    if ext == ".pdf":
        return _pdf_text_via_ocr(filepath)
    return ""


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _strip_disposal_chrome(text: str) -> str:
    compact = _compact_text(text)
    compact = re.sub(r"^正文内容", "", compact)
    for marker in ("通告如下", "公告如下", "公示如下", "情况公示如下", "情况通告如下"):
        if marker in compact:
            compact = compact[compact.index(marker) :]
            break
    if "当前位置" in compact:
        for marker in (
            "核查处置情况通告如下",
            "不合格食品核查处置情况通告如下",
            "通告如下",
            "公告如下",
            "公示如下",
            "抽检基本情况",
            "检验结论",
        ):
            pos = compact.find(marker)
            if 0 < pos < len(compact) * 0.75:
                compact = compact[pos:]
                break
        else:
            m = re.search(
                r"[一二三四五六七八九十百]+、[^（]{4,80}?(?:购进|销售)[的]",
                compact,
            )
            if m:
                compact = compact[m.start() :]
    compact = re.sub(
        r"^信息索引号[:：][^发]*?(?:发布机构|成文日期|公开方式|主题分类|体裁分类)[:：][^一-龥]*",
        "",
        compact,
    )
    compact = re.sub(
        r"^索\s*引\s*号[:：][^成]*成文日期[:：][^公]*公开方式[:：][^一-龥]*",
        "",
        compact,
    )
    return compact


def _is_captcha_shell(text: str) -> bool:
    compact = _compact_text(text)
    return any(m.replace(" ", "") in compact for m in _CAPTCHA_MARKERS)


def _is_nav_shell_only(text: str) -> bool:
    compact = _compact_text(text)
    if _is_captcha_shell(text):
        return True
    if any(m in compact for m in _ZJ_TRIGGER_MARKERS):
        return False
    if "检验结论" in compact and "不合格" in compact:
        return False
    if "项目不符合" in compact or "不符合食品安全" in compact:
        return False
    if re.search(r"\d+、.{4,80}?(?:销售|委托|用于餐饮服务)", compact) and (
        "项目检出值" in compact or "不符合" in compact
    ):
        return False
    return any(m in compact for m in _NAV_MARKERS)


def _clean_zhejiang_entity(raw: str) -> str:
    raw = raw.strip("：:，,。；; ")
    raw = _ENTITY_PREFIX.sub("", raw)
    raw = re.sub(r"^关于", "", raw)
    raw = re.sub(r"^抽检基本情况", "", raw)
    raw = re.sub(r"^通告如下[：:]?", "", raw)
    return normalize_company_name(raw)


def _normalize_narrative_product(raw: str) -> str:
    text = normalize_product_name(raw.strip())
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"\s*\d+\s*个\s*$", "", text)
    text = re.sub(r"(\d+)个$", "", text)
    text = re.sub(r"（[^）]*）$", "", text)
    text = re.sub(r"\([^)]*\)$", "", text)
    while re.search(r"[（(][^）)]*[）)]$", text):
        text = re.sub(r"[（(][^）)]*[）)]$", "", text)
    text = re.sub(r"^[的之]", "", text)
    text = re.sub(r"^销售的?", "", text)
    return sanitize_product_name(text.strip("、，,。 "))


def _is_valid_narrative_product(name: str) -> bool:
    if len(name) < 1 or len(name) > 40:
        return False
    if re.search(r"市监处罚|〔\d{4}〕|\d{4}〕\d+号", name):
        return False
    junk = (
        "标称", "商标", "规格", "生产日期", "有限公司", "销售的", "检验", "通告",
        "我局", "当事人", "购进日期", "抽样单编号", "备样数量", "样品数量",
        "监督抽检", "进行", "批次", "信息", "情况", "报告", "本局", "依法", "食品的",
    )
    if looks_like_inspection_item_not_product(name):
        return False
    return not any(j in name for j in junk)


def _is_valid_zhejiang_entity(name: str) -> bool:
    if len(name) < 2 or len(name) > 80:
        return False
    if is_invalid_company(name):
        return False
    junk = ("现将", "通告", "如下", "抽检", "检验", "本局", "当事人", "我局", "监督管理", "依法")
    return not any(j in name for j in junk)


def _is_valid_compact_sale_entity(name: str) -> bool:
    """台州等正文：被抽单位可为个体户姓名（王挺春、佘建琼）。"""
    compact = re.sub(r"\s+", "", _clean(name))
    if not compact or len(compact) < 2 or len(compact) > 80:
        return False
    if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", compact):
        return True
    return _is_valid_zhejiang_entity(compact)


def _section_lead(section: str, limit: int = 450) -> str:
    lead = section.split("我局")[0].split("经调查")[0].split("执法人员")[0]
    return lead[:limit]


def _clean_product_candidate(raw: str) -> str:
    raw = raw.strip()
    if "销售的标称" in raw:
        raw = raw.split("销售的标称")[-1]
        raw = re.sub(r"^.*?生产的", "", raw)
    raw = re.sub(r"(?:标称)?[^生]+生产的", "", raw, count=1)
    raw = re.sub(r"^[^一-龥A-Za-z0-9@“\"「]+", "", raw)
    raw = raw.strip("“”\"「」'、， ")
    return _normalize_narrative_product(raw)


def _extract_failure_item(section: str) -> str:
    lead = _section_lead(section, limit=800)
    compact = re.sub(r"\s+", "", lead)

    m = _RE_INSPECTION_ITEM.search(compact)
    if m:
        chunk = m.group(1).strip("，,、 ")
        items: list[str] = []
        for part in re.split(r"[、和及与，,]", chunk):
            name = normalize_failure_item_name(part.strip())
            if name and name not in items and len(name) <= 30:
                items.append(name)
        if items:
            return "、".join(items)

    for pattern in (_RE_ZJ_QUOTED_FAIL,):
        m = pattern.search(compact)
        if m:
            item = normalize_failure_item_name(m.group(1).strip())
            if item and len(item) <= 30:
                return item

    for m in _RE_ZJ_ITEM_FAIL.finditer(compact):
        item = normalize_failure_item_name(m.group(1).strip())
        if not item or len(item) > 30:
            continue
        if item in _NARRATIVE_CATEGORY_ITEMS:
            continue
        if any(j in item for j in ("检验结论", "食品安全", "国家标准", "GB", "产品", "食品")):
            continue
        return item

    first_sent = lead.split("。")[0]
    markers = (
        "项目不符合食品安全国家标准规定",
        "项目不符合食品安全",
        "检测值不符合食品安全",
        "项目不符合",
        "项目不合格",
    )
    for marker in markers:
        for text in (first_sent, re.sub(r"\s+", "", first_sent)):
            pos = text.find(marker)
            if pos <= 0:
                continue
            before = text[:pos].rstrip("，,、 ")
            prod_tail = re.search(r"产品[，,]?(.+)$", before)
            if prod_tail:
                chunk = prod_tail.group(1)
            else:
                chunk = re.split(r"[，,）)]", before)[-1]
            chunk = re.sub(r"\s+", "", chunk)
            items: list[str] = []
            for part in re.split(r"[、和及与]", chunk):
                name = normalize_failure_item_name(part.strip())
                if name and name not in items and len(name) <= 20:
                    items.append(name)
            if items:
                return "、".join(items)
    return ""


def _split_narrative_products(raw: str) -> list[str]:
    raw = _normalize_narrative_product(raw)
    if not raw:
        return []
    parts = re.split(r"[、和及与]", raw)
    return [p for p in (_normalize_narrative_product(x) for x in parts) if _is_valid_narrative_product(p)]


def _extract_products(section: str) -> list[str]:
    products: list[str] = []
    lead = _section_lead(section)

    def _add(raw: str) -> None:
        for name in _split_narrative_products(raw) or []:
            if _is_valid_narrative_product(name) and name not in products:
                products.append(name)
        name = _clean_product_candidate(raw)
        if _is_valid_narrative_product(name) and name not in products:
            products.append(name)

    for m in _QUOTED_PRODUCTS.finditer(lead):
        _add(m.group(1))

    compact = re.sub(r"\s+", "", lead)
    for pattern in (_PRODUCT_QUOTED, _PRODUCT_BEFORE_TRADEMARK):
        for m in pattern.finditer(compact):
            _add(m.group(1))

    for pattern in (_RE_ZJ_FOOD_NAME,):
        for m in pattern.finditer(section):
            _add(m.group(1))

    for pattern in (_RE_ZJ_SOLD,):
        for m in pattern.finditer(section):
            _add(m.group(2))

    for m in _RE_ZJ_OPERATED.finditer(section):
        _add(m.group(1))

    for m in _RE_ZJ_SALE_TIGHT.finditer(section):
        company = _clean_zhejiang_entity(m.group(1))
        if _is_valid_zhejiang_entity(company):
            product = _normalize_narrative_product(m.group("product"))
            if _is_valid_narrative_product(product) and product not in products:
                products.append(product)

    if products:
        return products

    cm = _COMPANY.search(lead)
    if not cm:
        return products
    tail = lead[cm.end() :]
    head = re.split(r"[\n（“\"「]", tail, maxsplit=1)[0]
    head = re.split(r"项目\s*不符合|检测值\s*不符合|项目\s*不合格", head, maxsplit=1)[0]
    for part in re.split(r"[、和及与]", head):
        _add(part)
    return products


def _extract_company(section: str) -> str:
    m = _COMPANY.search(section)
    if m:
        company = normalize_company_name(m.group(1).strip())
        if not is_invalid_company(company):
            return company

    m = _RE_ZJ_SECTION_ENTITY.search(section)
    if m:
        company = _clean_zhejiang_entity(m.group(1))
        if _is_valid_zhejiang_entity(company):
            return company

    m = _RE_ZJ_SALE_TIGHT.search(section)
    if m:
        company = _clean_zhejiang_entity(m.group(1))
        if _is_valid_zhejiang_entity(company):
            return company

    for pattern in (_RE_ZJ_SOLD, _RE_ZJ_NUMBERED):
        m = pattern.search(section)
        if m:
            company = _clean_zhejiang_entity(m.group(1))
            if _is_valid_zhejiang_entity(company):
                return company

    m = _RE_ZJ_OPERATE_HEADER.search(section)
    if m:
        company = _clean_zhejiang_entity(m.group(1))
        if _is_valid_zhejiang_entity(company):
            return company

    m = _RE_ZJ_ABOUT.search(section)
    if m:
        company = _clean_zhejiang_entity(m.group(1))
        if _is_valid_zhejiang_entity(company):
            return company

    m = re.search(rf"{_ZJ_ENTITY_FULL}(?:销售|经营|生产经营)", section)
    if m:
        company = _clean_zhejiang_entity(m.group(1))
        if _is_valid_zhejiang_entity(company):
            return company
    return ""


def _is_narrative_text(text: str) -> bool:
    if _is_nav_shell_only(text):
        return False
    compact = _strip_disposal_chrome(text)
    if "不合格食品具体情况通告如下" in compact:
        return True
    if re.search(
        r"\d+[\.．、][\u4e00-\u9fff]{2,40}(?:使用|消毒|销售|经营)[的]",
        compact,
    ):
        return True
    if "核查处置情况通告如下" in compact:
        return True
    if "不合格食品基本情况" in compact and _RE_SC_DISPOSAL_BODY.search(compact):
        return True
    if _RE_SC_ANNOUNCE_SALE.search(compact) or _RE_SC_ANNOUNCE_PRODUCE.search(compact):
        return True
    if _RE_SC_ANNOUNCE_QUOTED.search(compact):
        return True
    if "XBJ" in compact and ("不合格数据" in compact or "不合格抽检数据" in compact):
        return True
    if any(p.search(compact) for p in _TRIGGER_PATTERNS):
        return True
    if any(m in compact for m in _ZJ_TRIGGER_MARKERS):
        return True
    if _SECTION_MARKER.search(compact) and _COMPANY.search(compact):
        return True
    if _COMPANY.search(compact) and ("不合格" in compact or "不符合" in compact):
        return True
    if re.search(rf"{_ZJ_ENTITY_FULL}(?:销售|经营)", compact) and (
        "不合格" in compact or "不符合" in compact
    ):
        return True
    if re.search(r"\d+、.{4,80}?(?:销售|委托|用于餐饮服务)", compact) and (
        "不符合" in compact or "项目检出值" in compact
    ):
        return True
    return False


def _body_start(text: str) -> int:
    compact = _strip_disposal_chrome(text)
    for pat in _TRIGGER_PATTERNS:
        m = pat.search(compact)
        if m:
            return m.end()
    m = _SECTION_MARKER.search(compact)
    return m.start() if m else 0


def _split_dongguan_sections(text: str) -> list[str]:
    body = _strip_disposal_chrome(text)[_body_start(text) :]
    body = re.split(r"东莞市市场监督管理局\s*\d{4}\s*年", body, maxsplit=1)[0]
    body = re.split(r"特此通告|此通告", body, maxsplit=1)[0]

    parts = _SECTION_MARKER.split(body)
    sections: list[str] = []
    for part in parts:
        part = part.strip()
        if "生产的" in part and _COMPANY.search(part):
            sections.append(part)

    if sections:
        return sections
    if "生产的" in body and _COMPANY.search(body):
        return [body.strip()]
    return []


def _split_zhejiang_top_sections(text: str) -> list[str]:
    compact = _strip_disposal_chrome(text)
    parts = re.split(r"(?=[一二三四五六七八九十百]+、|\d+、抽检基本情况)", compact)
    sections: list[str] = []
    for chunk in parts:
        chunk = chunk.strip()
        if len(chunk) < 25:
            continue
        if re.search(
            r"抽检基本情况|食品名称|项目不符合|检验结论|销售[的]|经营[的]|购进",
            chunk,
        ):
            sections.append(chunk)

    if len(sections) >= 2:
        return sections

    matches = list(_RE_ZJ_TOP_CASE.finditer(compact))
    if len(matches) >= 2:
        sections = []
        for idx, match in enumerate(matches):
            start = match.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(compact)
            chunk = compact[start:end].strip()
            if re.search(rf"{_ZJ_ENTITY_FULL}(?:销售|经营)|食品名称|经营[的]", chunk):
                sections.append(chunk)
        if sections:
            return sections
    return []


def _strip_narrative_category_prefix(text: str) -> str:
    compact = re.sub(r"\s+", "", _clean(text))
    compact = re.sub(r"^[一二三四五六七八九十百]+、", "", compact)
    for prefix in _NARRATIVE_CATEGORY_PREFIXES:
        if compact.startswith(prefix):
            compact = compact[len(prefix) :]
    return compact.strip()


def _split_glued_product_item(blob: str) -> tuple[str, str]:
    """山药氯氟氰菊酯和高效氯氟氰菊酯 → (山药, 氯氟氰菊酯和高效氯氟氰菊酯)。"""
    compact = re.sub(r"\s+", "", _clean(blob)).strip("，,、 ")
    if not compact:
        return "", ""
    parts = re.split(r"[，,]", compact, maxsplit=1)
    if len(parts) == 2:
        product = _normalize_narrative_product(parts[0])
        item = normalize_failure_item_name(parts[1])
        if product and item and item not in _NARRATIVE_CATEGORY_ITEMS:
            return product, item
    for i in range(2, len(compact)):
        product = _normalize_narrative_product(compact[:i])
        if not product or len(product) < 2 or not _is_valid_narrative_product(product):
            continue
        item_raw = compact[i:]
        if not looks_like_inspection_item_not_product(item_raw):
            continue
        item = normalize_failure_item_name(item_raw)
        if not item or item in _NARRATIVE_CATEGORY_ITEMS:
            continue
        if _is_valid_narrative_product(item):
            continue
        return product, item
    return compact, ""


def _extract_compact_sale_chain_cases(text: str) -> list[_NarrativeCase]:
    """台州黄岩等：一节多案「XX销售的山药咪鲜胺项目不符合」连写正文。"""
    cases: list[_NarrativeCase] = []
    compact = re.sub(r"\s+", "", _strip_disposal_chrome(text))
    for m in _RE_ZJ_COMPACT_SALE_CHAIN.finditer(compact):
        company = m.group("company") or m.group("person") or m.group("person_tail") or ""
        company = _strip_narrative_category_prefix(_clean_zhejiang_entity(company))
        if not company or not _is_valid_compact_sale_entity(company):
            continue
        product, item = _split_glued_product_item(m.group("body"))
        if not product or not _is_valid_narrative_product(product) or not item:
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_basic_inspection_cases(text: str) -> list[_NarrativeCase]:
    """丽水莲都等：抽检基本情况XX销售/进购的YY，ZZ项目不符合。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_BASIC_INSPECTION.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_sale_inspect_cases(text: str) -> list[_NarrativeCase]:
    """嘉兴等：抽检基本情况XX销售的YY经抽样检验，ZZ项目不符合。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_SALE_INSPECT.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_project_item_cases(text: str) -> list[_NarrativeCase]:
    """宁波等：抽检基本情况XX购进/销售的YY，抽检项目中ZZ项目不符合。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_PROJECT_ITEM.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_produce_item_cases(text: str) -> list[_NarrativeCase]:
    """余姚等：抽检基本情况XX生产的YY，ZZ项目不符合。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_PRODUCE_ITEM.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_huzhou_cases(text: str) -> list[_NarrativeCase]:
    """湖州吴兴等叙述型核查处置正文。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_HUZHOU.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company):
            continue
        for product in _split_narrative_products(m.group(2)):
            product = _normalize_narrative_product(product)
            if not _is_valid_narrative_product(product):
                continue
            cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_drawn_sample_cases(text: str) -> list[_NarrativeCase]:
    """北仑等：抽样人员现场抽取样品后报告不合格项目。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_DRAWN_SAMPLE.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_drawn_item_value_cases(text: str) -> list[_NarrativeCase]:
    """北仑餐饮等：检验项目实测值超标。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_DRAWN_ITEM_VALUE.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_sale_batch_cases(text: str) -> list[_NarrativeCase]:
    """舟山等：XX销售/经营的1批次YY不合格。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_SALE_BATCH.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        if m.group(2):
            product = _normalize_narrative_product(m.group(2))
            item = normalize_failure_item_name(m.group(3).strip())
        elif m.group(4):
            product = _normalize_narrative_product(m.group(4))
            item = normalize_failure_item_name(m.group(5).strip())
        else:
            product = _normalize_narrative_product(m.group(6))
            item = normalize_failure_item_name(m.group(7).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_nanxun_party_cases(text: str) -> list[_NarrativeCase]:
    """湖州南浔等：当事人字段 + 检验结果为。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_NANXUN_PARTY.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company):
            continue
        for product in _split_narrative_products(m.group(2)):
            product = _normalize_narrative_product(product)
            if not _is_valid_narrative_product(product):
                continue
            cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_individual_sold_cases(text: str) -> list[_NarrativeCase]:
    """绍兴等：个体工商户当天销售的该批次产品。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_INDIVIDUAL_SOLD.finditer(text):
        company = _clean_zhejiang_entity(f"个体工商户{m.group(1)}")
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_compact_fail_cases(text: str) -> list[_NarrativeCase]:
    """宁波市局简表：XX生产/销售的YY,ZZ不符合标准要求。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_COMPACT_FAIL.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_produce_sale_inline_cases(text: str) -> list[_NarrativeCase]:
    """镇海等：抽检基本情况XX生产销售的YY，ZZ项目不符合。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_PRODUCE_SALE_INLINE.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_produced_by_cases(text: str) -> list[_NarrativeCase]:
    """绍兴生产追溯：在售的YY检验不合格，由XX生产。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_PRODUCED_BY.finditer(text):
        product = _normalize_narrative_product(m.group(1))
        item = normalize_failure_item_name(m.group(2).strip())
        company = _clean_zhejiang_entity(m.group(3))
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_sale_supervise_cases(text: str) -> list[_NarrativeCase]:
    """绍兴等：依法对XX销售的YY进行食品安全监督抽检。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_SALE_SUPERVISE.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_party_operated_cases(text: str, filepath: str = "") -> list[_NarrativeCase]:
    """绍兴等：当事人X日经营的YY，检验不合格（主体取自文件名）。"""
    company = ""
    if filepath:
        m = _RE_ZJ_FILENAME_ABOUT.search(os.path.basename(filepath))
        if m:
            company = _clean_zhejiang_entity(m.group(1))
    if not company:
        return []
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_PARTY_OPERATED.finditer(text):
        product = _normalize_narrative_product(m.group(1))
        item = normalize_failure_item_name(m.group(2).strip())
        if not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_locate_purchase_cases(text: str) -> list[_NarrativeCase]:
    """绍兴等：对位于…的餐饮店采购的YY抽样不合格。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_LOCATE_PURCHASE.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_structured_block_cases(text: str) -> list[_NarrativeCase]:
    """温州等：食品生产经营单位名称/食品名称/不合格项目字段体。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_STRUCTURED_BLOCK.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_party_product_cases(text: str) -> list[_NarrativeCase]:
    """温州等：对当事人经营的YY，该批次YY中ZZ项目不符合。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_PARTY_PRODUCT.finditer(text):
        product = _normalize_narrative_product(m.group(1))
        item = normalize_failure_item_name(m.group(2).strip())
        if not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase("当事人", [product], item))
    return cases


def _extract_numbered_loose_cases(text: str) -> list[_NarrativeCase]:
    """舟山等：编号简表，主体为市场摊位等。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_NUMBERED_LOOSE.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_section_produce_cases(text: str) -> list[_NarrativeCase]:
    """舟山等：XX生产的YY，经抽样检验不合格。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_SECTION_PRODUCE.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_section_operate_cases(text: str) -> list[_NarrativeCase]:
    """舟山等：XX经营的YY经抽样检验不合格。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_SECTION_OPERATE.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_supervise_fail_cases(text: str) -> list[_NarrativeCase]:
    """金华等：监督抽检不合格项目为ZZ。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_SUPERVISE_FAIL.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_huzhou_loose_cases(text: str) -> list[_NarrativeCase]:
    """湖州等：个人/摊位名抽检基本情况正文。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_HUZHOU_LOOSE.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_possess_fail_cases(text: str) -> list[_NarrativeCase]:
    """镇海等：XX的YY的ZZ项目不符合食品安全国家标准。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_POSSESS_FAIL.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_purchase_inline_cases(text: str) -> list[_NarrativeCase]:
    """余姚等：抽检基本情况XX采购的YY，ZZ不符合标准。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_PURCHASE_INLINE.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_produce_possess_cases(text: str) -> list[_NarrativeCase]:
    """前湾等：XX生产的YY的ZZ不符合食品安全国家标准。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_PRODUCE_POSSESS.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_multi_sale_section_cases(text: str) -> list[_NarrativeCase]:
    """湖州/绍兴：一节多产品，当事人销售的YY，经抽样检验，ZZ不符合。"""
    cases: list[_NarrativeCase] = []
    for block in re.split(r"(?=[一二三四五六七八九十百]+、)", text):
        m_header = re.search(r"[一二三四五六七八九十百]+、(.+?)销售[的]", block)
        if not m_header:
            continue
        company = _clean_zhejiang_entity(m_header.group(1))
        if not _is_valid_zhejiang_entity(company):
            continue
        for m in _RE_ZJ_SALE_INSPECT_INLINE.finditer(block):
            item = normalize_failure_item_name(m.group(2).strip())
            for product in _split_narrative_products(m.group(1)):
                product = _normalize_narrative_product(product)
                if not _is_valid_narrative_product(product):
                    continue
                cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_third_party_sale_cases(text: str) -> list[_NarrativeCase]:
    """湖州等：对XX销售的YY进行监督抽检（抽检对象可与标题主体不同）。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_THIRD_PARTY_SALE.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_use_material_cases(text: str) -> list[_NarrativeCase]:
    """湖州餐厅等：对XX使用的食品原料YY进行监督抽检。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_USE_MATERIAL.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_structured_table_cases(text: str) -> list[_NarrativeCase]:
    """绍兴表格体：样品名称 + 被抽样单位 + 检验结论。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_STRUCTURED_TABLE.finditer(text):
        product = _normalize_narrative_product(m.group(1))
        company = _clean_zhejiang_entity(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_procure_supervise_cases(text: str) -> list[_NarrativeCase]:
    """绍兴等：依法对XX采购的YY进行监督抽检。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_PROCURE_SUPERVISE.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_on_sale_direct_cases(text: str) -> list[_NarrativeCase]:
    """绍兴等：依法对XX在售的YY进行食品安全监督抽检。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_ON_SALE_DIRECT.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_process_product_cases(text: str) -> list[_NarrativeCase]:
    """鄞州等：加工的馒头，甜蜜素项目不符合。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_PROCESS_PRODUCT.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company):
            continue
        for product in _split_narrative_products(m.group(2)):
            product = _normalize_narrative_product(product)
            if not _is_valid_narrative_product(product):
                continue
            cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_market_inline_sale_cases(text: str) -> list[_NarrativeCase]:
    """金华等：市场摊位销售的大山药咪鲜胺项目不符合。"""
    cases: list[_NarrativeCase] = []
    for m in re.finditer(
        r"抽检基本情况(.+?)销售的(.{2,24}?)([一-龥（）()·\-,]{2,30}?)项目不符合食品安全国家标准",
        text,
    ):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_residue_fail_cases(text: str) -> list[_NarrativeCase]:
    """舟山等：经营的荷兰豆…残留量不符合。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_RESIDUE_FAIL.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_shop_operate_cases(text: str) -> list[_NarrativeCase]:
    """温州等：对XX水产品店经营…该店经营的鲫鱼。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_SHOP_OPERATE.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_batch_conclusion_cases(text: str, filepath: str = "") -> list[_NarrativeCase]:
    """绍兴等：此批次梅干菜的检验结论为经抽样检验，铅不符合。"""
    company = ""
    m_co = re.search(
        r"对(.+?(?:有限公司|公司|超市|经营部))销售的",
        text,
    )
    if m_co:
        company = _clean_zhejiang_entity(m_co.group(1))
    if not company and filepath:
        m_fn = _RE_ZJ_FILENAME.search(os.path.basename(filepath))
        if m_fn:
            company = _clean_zhejiang_entity(m_fn.group(1))
    if not company:
        return []
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_BATCH_CONCLUSION.finditer(text):
        product = _normalize_narrative_product(m.group(1))
        item = normalize_failure_item_name(m.group(2).strip())
        if not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_remote_produce_cases(text: str, filepath: str = "") -> list[_NarrativeCase]:
    """未名太研等：异地抽检，生产企业为本市企业。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_REMOTE_PRODUCE.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    if cases:
        return cases
    if not filepath:
        return []
    m_fn = _RE_ZJ_FILENAME.search(os.path.basename(filepath))
    if not m_fn:
        return []
    company = _clean_zhejiang_entity(m_fn.group(1))
    for m in re.finditer(
        r"的([^，。；]{2,30}?)进行了抽样"
        r".{0,400}?"
        r"([^，。；]+?)(?:项目)?不符合",
        text,
    ):
        product = _normalize_narrative_product(m.group(1))
        item = normalize_failure_item_name(m.group(2).strip())
        if not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_on_sale_sample_cases(text: str) -> list[_NarrativeCase]:
    """绍兴等：对位于…的XX在售的YY抽样检验。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_ON_SALE_SAMPLE.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_stall_sale_cases(text: str) -> list[_NarrativeCase]:
    """绍兴等：对XX摊位销售的YY进行了监督抽检。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_STALL_SALE.finditer(text):
        company = _clean_zhejiang_entity(m.group(1) + "摊位")
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_supply_inspect_cases(text: str) -> list[_NarrativeCase]:
    """舟山等：XX供应的YY经抽样检验不合格。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_SUPPLY_INSPECT.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_drawn_use_sample_cases(text: str) -> list[_NarrativeCase]:
    """北仑餐饮等：抽取使用中的食品原料。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_DRAWN_USE_SAMPLE.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_drawn_measured_cases(text: str) -> list[_NarrativeCase]:
    """北仑等：检验项目实测值超标。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_DRAWN_MEASURED.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_store_sold_cases(text: str) -> list[_NarrativeCase]:
    """绍兴等：超市当天销售的该批次产品抽验不合格。"""
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_STORE_SOLD.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        item = normalize_failure_item_name(m.group(3).strip())
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _clean_fujian_company(raw: str) -> str:
    raw = re.sub(r"^\d+、", "", raw.strip())
    return normalize_company_name(raw)


def _extract_fujian_block(block: str) -> _NarrativeCase | None:
    block = block.strip()
    if len(block) < 40:
        return None
    item_m = _RE_FJ_ITEM.search(block)
    if not item_m:
        item_m = re.search(r"）([^，,。]+?)项目检出值", block)
    if not item_m:
        return None
    item = normalize_failure_item_name(item_m.group(1).strip())

    m = re.search(
        r"(?:\d+、)?(.+?(?:有限公司|公司))委托(.+?(?:有限公司|公司|食品厂))"
        r"生产的([^（(委托]+)",
        block,
    )
    if m:
        company = _clean_fujian_company(m.group(2))
        product = _normalize_narrative_product(m.group(3))
        return _NarrativeCase(company, [product], item)

    m = re.search(
        r"(?:\d+、)?(.+?(?:有限公司|公司|餐饮管理有限公司|餐饮店))"
        r"用于餐饮服务的([^经（(]+)",
        block,
    )
    if m:
        company = _clean_fujian_company(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        return _NarrativeCase(company, [product], item)

    m = re.search(
        r"(?:\d+、)?(.+?(?:有限公司|有限责任公司|购物商场|超市|商场|公司|店))"
        r"销售的([^（(经，,]+)",
        block,
    )
    if m:
        company = _clean_fujian_company(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        return _NarrativeCase(company, [product], item)
    return None


def _extract_fujian_cases(text: str) -> list[_NarrativeCase]:
    """福建漳州等：编号列表式核查处置公示。"""
    compact = _strip_disposal_chrome(text)
    start = re.search(r"\d+、", compact)
    if start:
        compact = compact[start.start() :]
    cases: list[_NarrativeCase] = []
    seen: set[tuple[str, str]] = set()
    for block in re.split(r"(?=\d+、)", compact):
        case = _extract_fujian_block(block)
        if not case or len(case.company) < 4:
            continue
        for product in case.products:
            if not _is_valid_narrative_product(product):
                continue
            key = (case.company, product)
            if key in seen:
                continue
            seen.add(key)
            cases.append(_NarrativeCase(case.company, [product], case.unqualified_item))
    return cases


_SC_ENTITY = (
    r"[\u4e00-\u9fff·（）()A-Za-z0-9@]{2,100}?"
    r"(?:有限责任公司|有限公司|公司|食品厂|酒厂|超市|商场|购物商场|"
    r"经营部|副食店|水果摊|水果行|干货经营部|副食干货经营部|生活超市|"
    r"白酒门市|土特产门市|水果超市|食品经营部|副食经营部|蔬菜有限公司|"
    r"火锅店|小吃店|豆腐作坊|生鲜店|包子铺|酒楼|购物中心|干杂店|"
    r"农贸市场[^）)]*|(?:市场|菜市场)[\u4e00-\u9fff]{2,10}|店|部|摊|厂|行|门市)"
)
_SC_COMPANY = rf"(?:{_SC_ENTITY}|[\u4e00-\u9fff·（）()0-9]{{2,80}}?(?:市场|菜市场)[\u4e00-\u9fff]{{2,10}})"
_RE_SC_ANNOUNCE_QUOTED = re.compile(
    rf"(?:（[一二三四五六七八九十]+）)?"
    rf"(?P<company>{_SC_COMPANY})"
    rf"(?:（个体工商户）)?"
    rf"(?:购进/?)?销售[的]?"
    rf"[“\"「](?P<product>[^”\"」]+)[”\"」]"
    rf"[，,]"
    rf"(?P<item>[^。；;]+?)"
    rf"(?:项目)?不符合(?:食品安全)?(?:国家标准)?(?:规定)?"
)
_RE_SC_ANNOUNCE_ABBR_SALE = re.compile(
    r"[；;]销售[的]?"
    r"[“\"「](?P<product>[^”\"」]+)[”\"」]"
    r"[，,]"
    r"(?P<item>[^。；;]+?)"
    r"(?:项目)?不符合(?:食品安全)?(?:国家标准)?(?:规定)?"
)
_RE_SC_ANNOUNCE_SALE = re.compile(
    rf"(?:（[一二三四五六七八九十]+）)?"
    rf"(?P<company>{_SC_ENTITY})"
    rf"销售[的]?(?P<product>[^，,。；;（(]+?)"
    rf"(?:（[^）]*）)?[，,]"
    rf"[“\"「]?(?P<item>[^，,。；;“\"」]+)[”\"」]?"
    rf"(?:项目)?不符合(?:食品安全)?(?:国家标准)?(?:规定)?"
)
_RE_SC_ANNOUNCE_PRODUCE = re.compile(
    rf"(?P<company>{_SC_ENTITY})"
    rf"生产[的]?(?P<product>[^，,。；;（(]+?)"
    rf"(?:（[^）]*）)?[，,]"
    rf"[“\"「]?(?P<item>[^，,。；;“\"」]+)[”\"」]?"
    rf"(?:项目)?不符合(?:食品安全)?(?:国家标准)?(?:规定)?"
)
_RE_SC_DISPOSAL_BODY = re.compile(
    rf"(?P<company>{_SC_ENTITY})"
    rf"(?:销售|经营|购进|生产|使用)[的]?"
    rf"(?P<product>[^（(、，,；;]+?)"
    rf"（[^）]*）"
)
_RE_SC_QUOTED_ITEM_FAIL = re.compile(
    r"[“\"「](?P<item>[^”\"」]+)[”\"」]项目不符合(?:食品安全)?(?:国家标准)?(?:规定)?"
)
_RE_SC_SUMMARY_SAMPLE = re.compile(
    r"(?:任务时，|抽检任务，|监督抽检任务，)在(?P<company>.+?)(?:抽取了|进行了抽)[^，,。；;]*?"
    r"(?:自制经营销售)?(?:\d+批次)?(?:超市经营的|经营的|食品|，即|即)?"
    r"(?P<product>[^（(，,；;]+?)"
    r"[，,]?（[^）]*）[^经]*经检验[，,]"
    r"(?:均为)?(?P<item>[^。；;]+?)项目不合格"
)
_RE_SC_INLINE_BATCH = re.compile(
    r"(?P<company>.+?)"
    r"(?:\d{4}年\d{1,2}月\d{1,2}日)?"
    r"(?:制售|生产|销售|加工)的?\d+批次[“\"「](?P<product>[^”\"」]+)[”\"」]"
    r"[，,]经检验[，,](?P<item>[^。；;《]+?)项目不符合"
)
_RE_SC_CHOUJIAN_DETECT = re.compile(
    r"(?:\d+批次)?在(?P<company>.+?)"
    r"(?:生产|销售|经营|使用)的?[“\"「](?P<product>[^”\"」]+)[”\"」]"
    r"（[^）]*）被检出[“\"「](?P<item>[^”\"」]+)[”\"」]?(?:项目)?不合格"
)
_RE_SC_XBJ_ROW = re.compile(
    r"XBJ\d+(?:\d)?"
    r"(?P<body>.*?)"
    r"(?:加工日期|购进日期)[：:]\d{4}-\d{2}-\d{2}"
)

# 陕西：武功/乾县/泾阳等县局及市级「不合格食品具体情况通告如下」正文
_SN_ENTITY_TAIL = (
    r"有限责任公司|有限公司|公司|食品厂|超市|商场|经营部|副食店|生活超市|"
    r"饭店|饭馆|面馆|泡馍馆|餐饮店|干杂店|干菜店|酒家|羊肉馆|川菜馆|"
    r"批发部|配送店|蔬菜店|粮油店|小面馆|火锅店|小吃店|回坊|门市|"
    r"加工厂|肉食加工厂|科技开发|分公司|"
    r"大饭店|酒店|酿酒坊|专业合作社|"
    r"豆制品厂|酒厂|生产基地|"
    r"坊|商贸|餐饮|厂|"
    r"店|部|馆|行|摊"
)
_SN_COMPANY = rf"[\u4e00-\u9fff·（）()0-9]{{2,55}}?(?:{_SN_ENTITY_TAIL})"
_SN_ITEM = rf"(?P<item>[^，,。；;\n]{{2,120}}?)"
_SN_FAIL_TAIL = (
    r"(?:检测值)?(?:项目)?不符合"
    r"(?:GB[/／T][^，。；\n]{0,80}?|"
    r"(?:食品安全)?(?:国家标准|产品明示标准和质量要求)?)"
    r"(?:规定|要求)?"
)
_RE_SN_NUMBERED_FAIL = re.compile(
    r"(?<![\d\.])"
    r"(?:[一二三四五六七八九十]+、[^。\d]{4,40}?问题)?"
    r"(?P<num>\d+)[\.．、]"
    rf"(?P<company>{_SN_COMPANY})"
    r"(?:使用|消毒|销售|经营|制售)[的]?"
    rf"(?P<product>[^，,。；;\n]{{1,40}}?)"
    r"[，,]"
    r"(?:\d+批次)?"
    rf"{_SN_ITEM}"
    rf"{_SN_FAIL_TAIL}"
)
_RE_SN_SALE_LABELED = re.compile(
    rf"(?P<company>{_SN_COMPANY})"
    r"销售(?:的)?"
    rf"(?:、标称[\u4e00-\u9fff·（）()0-9A-Za-z]+(?:{_SN_ENTITY_TAIL})生产的)?"
    rf"(?P<product>[^，,。；;\n]{{1,40}}?)"
    r"[，,]"
    r"(?:\d+批次)?"
    rf"{_SN_ITEM}"
    rf"{_SN_FAIL_TAIL}"
)
_RE_SN_SALE_DELEGATE = re.compile(
    rf"(?P<company>{_SN_COMPANY})"
    r"销售的"
    rf"(?:、[\u4e00-\u9fff·（）()0-9A-Za-z]+(?:{_SN_ENTITY_TAIL})委托[\u4e00-\u9fff·（）()0-9A-Za-z]+(?:{_SN_ENTITY_TAIL})生产的)?"
    rf"(?P<product>[^，,。；;\n]{{1,40}}?)"
    r"[，,]"
    r"(?:\d+批次)?"
    rf"{_SN_ITEM}"
    rf"{_SN_FAIL_TAIL}"
)
_RE_SN_PROCURE_LABELED = re.compile(
    rf"(?P<company>{_SN_COMPANY})"
    r"采购的"
    rf"(?:、标称[\u4e00-\u9fff·（）()0-9A-Za-z]+(?:{_SN_ENTITY_TAIL})生产的)?"
    rf"(?P<product>[^，,。；;\n]{{1,40}}?)"
    r"[，,]"
    r"(?:\d+批次)?"
    rf"{_SN_ITEM}"
    rf"{_SN_FAIL_TAIL}"
)
_RE_SN_PRODUCE_BATCH = re.compile(
    rf"(?P<company>{_SN_COMPANY})"
    r"生产的"
    rf"(?P<product>[^，,。；;\n]{{1,40}}?)"
    r"[，,]"
    r"(?:\d+批次)?"
    rf"{_SN_ITEM}"
    rf"{_SN_FAIL_TAIL}"
)
_RE_SN_USE_BATCH = re.compile(
    rf"(?P<company>{_SN_COMPANY})"
    r"使用的"
    rf"(?P<product>[^，,。；;\n]{{1,40}}?)"
    r"[，,]"
    r"(?:\d+批次)?"
    rf"{_SN_ITEM}"
    rf"{_SN_FAIL_TAIL}"
)
_RE_SN_PRODUCE_INSPECT = re.compile(
    r"(?:在食品安全监督抽检中，)?"
    rf"(?P<company>{_SN_COMPANY})"
    r"(?:\d{4}年\d{1,2}月\d{1,2}日)?"
    r"生产的"
    rf"(?P<product>.+?)"
    r"经[^，,。；;\n]+?(?:抽样)?检验[，,]"
    rf"{_SN_ITEM}"
    rf"{_SN_FAIL_TAIL}"
)
_RE_SN_TRIGGER_BODY = re.compile(
    r"(?:现将[^。；\n]{0,30}批?)?(?:监督抽检)?不合格食品具体情况通告如下[：:]?"
)


def _clean_shaanxi_entity(raw: str) -> str:
    raw = re.sub(r"\s+", "", _clean(raw)).strip("（()、，,：: ")
    raw = re.sub(r"^[（(][一二三四五六七八九十百]+[）)]", "", raw)
    if "委托" in raw:
        return ""
    raw = re.sub(r"^标称", "", raw)
    raw = re.sub(r"^(?:[一二三四五六七八九十]+、)?抽检基本情况", "", raw)
    if re.match(
        r"^(?:河南|北京|山东|广东|四川|浙江|江苏|河北|山西|甘肃|宁夏|青海|新疆|西藏|云南|贵州|广西|海南|内蒙|黑龙江|吉林|辽宁|天津|重庆|上海|福建|江西|湖南|湖北|安徽)(?:省|市)",
        raw,
    ):
        return ""
    company = normalize_company_name(raw)
    if is_invalid_company(company) or len(company) < 3:
        return ""
    junk = ("现将", "通告", "如下", "检验机构", "特此通告", "市场监督管理局关于")
    if any(j in company for j in junk):
        return ""
    return company


def _extract_shaanxi_body(text: str) -> str:
    compact = _strip_disposal_chrome(text)
    start = 0
    m = _RE_SN_TRIGGER_BODY.search(compact)
    if m:
        start = m.end()
    else:
        m2 = re.search(r"不合格食品监督抽检情况的通告", compact)
        if m2:
            m3 = re.search(r"\d+[\.．、]", compact[m2.end() :])
            if m3:
                start = m2.end() + m3.start()
    if not start:
        return compact
    end = len(compact)
    for marker in ("检验机构为", "对抽检中发现", "特此通告", "附件：", "附件:", "附件1"):
        pos = compact.find(marker, start)
        if pos > start:
            end = min(end, pos)
    return compact[start:end]


def _split_shaanxi_items(raw_item: str) -> list[str]:
    text = (raw_item or "").strip()
    if not text:
        return []
    if "、" in text and not re.search(r"[（(].*[）)]", text):
        parts = [normalize_failure_item_name(p.strip()) for p in text.split("、")]
        valid = [p for p in parts if p]
        if len(valid) >= 2:
            return valid
    normalized = normalize_failure_item_name(text)
    return [normalized] if normalized else []


def _add_shaanxi_case(
    cases: list[_NarrativeCase],
    seen: set[tuple[str, str, str]],
    company: str,
    product: str,
    item_raw: str,
) -> None:
    company = _clean_shaanxi_entity(company)
    product = _normalize_narrative_product(product)
    if not company or not _is_valid_narrative_product(product):
        return
    for item in _split_shaanxi_items(item_raw):
        if not item or looks_like_inspection_item_not_product(product):
            continue
        key = (company, product, item)
        if key in seen:
            continue
        seen.add(key)
        cases.append(_NarrativeCase(company, [product], item))


_SN_BODY_PATTERNS = (
    _RE_SN_NUMBERED_FAIL,
    _RE_SN_SALE_DELEGATE,
    _RE_SN_SALE_LABELED,
    _RE_SN_PROCURE_LABELED,
    _RE_SN_USE_BATCH,
    _RE_SN_PRODUCE_BATCH,
)


def _extract_shaanxi_cases(text: str) -> list[_NarrativeCase]:
    """陕西县/市监局通告：X.XX店使用的YY，ZZ不符合…"""
    body = _extract_shaanxi_body(text)
    cases: list[_NarrativeCase] = []
    seen: set[tuple[str, str, str]] = set()
    for pattern in _SN_BODY_PATTERNS:
        for m in pattern.finditer(body):
            _add_shaanxi_case(cases, seen, m.group("company"), m.group("product"), m.group("item"))
    for m in _RE_SN_PRODUCE_INSPECT.finditer(_strip_disposal_chrome(text)):
        _add_shaanxi_case(cases, seen, m.group("company"), m.group("product"), m.group("item"))
    if not cases:
        chrome = _strip_disposal_chrome(text)
        for pattern in (_RE_SN_SALE_LABELED, _RE_SN_SALE_DELEGATE, _RE_SN_PROCURE_LABELED):
            for m in pattern.finditer(chrome):
                _add_shaanxi_case(cases, seen, m.group("company"), m.group("product"), m.group("item"))
    return cases


def _header_company_from_section(header: str) -> str:
    for verb in ("销售", "经营", "购进", "生产", "使用"):
        pos = header.find(verb)
        if pos > 0:
            return _clean_sichuan_entity(header[:pos])
    return ""


def _header_product_from_section(header: str) -> str:
    for verb in ("销售", "经营", "购进", "生产", "使用"):
        m = re.search(rf"{verb}[的]?([^（(、和]+)", header)
        if m:
            return _normalize_narrative_product(m.group(1))
    return ""


def _clean_sichuan_entity(raw: str) -> str:
    raw = re.sub(r"\s+", "", _clean(raw)).strip("（()、，,：: ")
    raw = re.sub(r"^[（(][一二三四五六七八九十百]+[）)]", "", raw)
    raw = re.sub(r"^在", "", raw)
    raw = re.sub(r"\d{4}年\d{1,2}月\d{1,2}日$", "", raw)
    raw = re.sub(r"(?:购进/?)?销售$", "", raw)
    raw = re.sub(r"购进$", "", raw)
    if "在" in raw:
        raw = raw.split("在")[-1]
    raw = re.sub(
        r"^(?:[一二三四五六七八九十百]+、)?(?:[^（(]{0,40}?(?:问题|情况|批次))?",
        "",
        raw,
    )
    for prefix in (
        "农药残留量超标",
        "重金属污染物超标",
        "超限量使用食品添加剂",
        "微生物污染超标",
        "有机物污染超标",
        "兽药残留超标",
    ):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
    company = normalize_company_name(raw)
    if is_invalid_company(company) or len(company) < 4:
        return ""
    return company


def _split_sichuan_items(raw: str) -> list[str]:
    text = re.sub(r"^[“\"「]|[”\"」]$", "", _clean(raw))
    if not text:
        return []
    parts = re.split(r"[、/]", text) if len(text) <= 48 else [text]
    items: list[str] = []
    for part in parts:
        item = normalize_failure_item_name(part)
        if not item:
            continue
        if any(j in item for j in ("检验机构", "食品安全标准", "国家标准", "GB", "销售", "生产", "经营部")):
            continue
        if len(item) > 24:
            continue
        items.append(item)
    return items


def _add_sichuan_case(
    cases: list[_NarrativeCase],
    seen: set[tuple[str, str, str]],
    company: str,
    product: str,
    item: str,
) -> None:
    company = _clean_sichuan_entity(company)
    product = sanitize_product_name(
        re.sub(r"^\d+批次", "", _normalize_narrative_product(product))
    )
    product = re.sub(r"^食品", "", product).strip()
    if not company or not product or not _is_valid_narrative_product(product):
        return
    if "不合格食品基本情况" in company or "核查处置" in company:
        return
    item_list = _split_sichuan_items(item) if item.strip() else [""]
    for one_item in item_list:
        key = (company, product, one_item)
        if key in seen:
            continue
        seen.add(key)
        cases.append(_NarrativeCase(company, [product], one_item))


def _parse_sichuan_field_body(
    body: str,
    header_company: str,
) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    chunks = re.split(r"(?=\d+\.(?:\d+\.)?产品名称：)", body)
    if len(chunks) <= 1:
        chunks = [body]
    for chunk in chunks:
        if "产品名称：" not in chunk:
            continue
        pm = re.search(r"产品名称：([^；;]+)", chunk)
        cm = re.search(r"被抽样单位：([^；;]+)", chunk)
        im = re.search(r"不合格项目：([^。；;]+)", chunk)
        if not pm or not im:
            continue
        company = _clean_sichuan_entity(cm.group(1) if cm else header_company)
        product = pm.group(1).strip()
        item = im.group(1).strip()
        if company and product and item:
            rows.append((company, product, item))
    return rows


def _extract_sichuan_disposal_cases(text: str) -> list[_NarrativeCase]:
    """宜宾/攀枝花等：核查处置正文（不合格食品基本情况）。"""
    compact = _strip_disposal_chrome(text)
    for marker in ("核查处置情况通告如下：", "核查处置情况通告如下:", "核查处置情况通告如下"):
        pos = compact.find(marker)
        if pos >= 0:
            compact = compact[pos + len(marker) :]
            break
    cases: list[_NarrativeCase] = []
    seen: set[tuple[str, str, str]] = set()
    for section in _SECTION_MARKER.split(compact):
        if "不合格食品基本情况" not in section:
            continue
        idx = section.find("不合格食品基本情况")
        header = section[:idx]
        body = section[idx + len("不合格食品基本情况") :]
        header_company = _header_company_from_section(header)
        if "产品名称：" in body or "被抽样单位：" in body:
            for company, product, field_item in _parse_sichuan_field_body(body, header_company):
                _add_sichuan_case(cases, seen, company, product, field_item)
            continue
        item = ""
        qm = re.search(r"[“\"「]([^”\"」]+)[”\"」]项目不符合", body)
        if qm:
            item = qm.group(1)
        else:
            item_m = re.search(
                r"([^，,。；;（()]{2,24})项目不符合(?:食品安全)?(?:国家标准)?(?:规定)?",
                body,
            )
            if item_m:
                item = item_m.group(1)
        if not item:
            continue
        found = False
        for m in _RE_SC_DISPOSAL_BODY.finditer(body):
            company = _clean_sichuan_entity(m.group("company")) or header_company
            _add_sichuan_case(cases, seen, company, m.group("product"), item)
            found = True
        if not found and header_company:
            product = ""
            for verb in ("销售", "经营", "购进", "生产", "使用"):
                pm = re.search(rf"{verb}[的]?([^（(、，,；;]+)", header)
                if pm:
                    product = pm.group(1)
                    break
            _add_sichuan_case(cases, seen, header_company, product, item)
    for section in _SECTION_MARKER.split(compact):
        if "抽检基本情况" not in section:
            continue
        idx = section.find("抽检基本情况")
        header = section[:idx]
        body = section[idx + len("抽检基本情况") :]
        header_company = _header_company_from_section(header)
        header_product = _header_product_from_section(header)
        found = False
        for m in _RE_SC_CHOUJIAN_DETECT.finditer(body):
            company = _clean_sichuan_entity(m.group("company")) or header_company
            product = m.group("product") or header_product
            _add_sichuan_case(cases, seen, company, product, m.group("item"))
            found = True
        if not found and header_company and header_product:
            item_m = re.search(
                r"被检出[“\"「](?P<item>[^”\"」]+)[”\"」]?(?:项目)?不合格",
                body,
            )
            if item_m:
                _add_sichuan_case(cases, seen, header_company, header_product, item_m.group("item"))
                found = True
        if not found and header_company:
            header_product = header_product or _header_product_from_section(header)
            qm = _RE_SC_QUOTED_ITEM_FAIL.search(body)
            if qm and header_product:
                _add_sichuan_case(cases, seen, header_company, header_product, qm.group("item"))
    for section in _SECTION_MARKER.split(compact):
        if "不合格食品抽检的基本情况" not in section and "抽检的基本情况" not in section:
            continue
        _extract_sichuan_summary_section(section, cases, seen)
    for part in re.split(r"（[一二三四五六七八九十]+）抽检基本情况", compact):
        for m in _RE_SC_INLINE_BATCH.finditer(part):
            _add_sichuan_case(
                cases,
                seen,
                m.group("company"),
                m.group("product"),
                m.group("item"),
            )
    for section in _SECTION_MARKER.split(compact):
        if "不合格食品基本情况" not in section:
            continue
        _extract_sichuan_summary_section(section, cases, seen)
    for m in _RE_SC_SUMMARY_SAMPLE.finditer(compact):
        _add_sichuan_case(
            cases,
            seen,
            m.group("company"),
            m.group("product"),
            m.group("item"),
        )
    last_sample = None
    for m in re.finditer(
        r"在(?P<company>.+?)抽取了\d+批次(?P<product>[^（(，,；;]+?)"
        r"（[^）]*）[^经]*经检验[，,](?P<item>[^。；;]+?)项目不合格",
        compact,
    ):
        last_sample = m
    if last_sample:
        _add_sichuan_case(
            cases,
            seen,
            last_sample.group("company"),
            last_sample.group("product"),
            last_sample.group("item"),
        )
    return cases


def _parse_sichuan_xbj_body(body: str) -> tuple[str, str] | None:
    body = re.sub(r"^\d+", "", body.strip())
    if not body:
        return None
    m = re.match(
        r"^(?P<company>.+?(?:店|部|铺|酒楼|超市|经营部|包子铺|干杂店|副食品店|"
        r"（个体工商户）))(?:四川省(?P<addr>[^加工购进]+))?"
        r"(?P<product>.+?)$",
        body,
    )
    if m:
        return m.group("company"), _normalize_narrative_product(m.group("product"))
    m = re.match(
        r"^(?P<company>[^四]{2,80}?(?:店|部|铺|酒楼|超市|经营部))"
        r"(?P<addr>[^加工购进]{4,80}?(?:市场|居委会|组|号|街|路|苑|层))"
        r"(?P<product>.+?)$",
        body,
    )
    if m:
        return m.group("company"), _normalize_narrative_product(m.group("product"))
    return None


def _extract_sichuan_xbj_table(text: str) -> list[_NarrativeCase]:
    """自流井等：正文内嵌 XBJ 抽样编号扁平表格（无不合格项目列）。"""
    compact = _strip_disposal_chrome(text)
    if "XBJ" not in compact or "食品名称" not in compact:
        return []
    if "不合格" not in compact and "不合格数据" not in compact:
        return []
    cases: list[_NarrativeCase] = []
    seen: set[tuple[str, str, str]] = set()
    for m in _RE_SC_XBJ_ROW.finditer(compact):
        parsed = _parse_sichuan_xbj_body(m.group("body"))
        if not parsed:
            continue
        company, product = parsed
        _add_sichuan_case(cases, seen, company, product, "")
    return cases


def _extract_sichuan_summary_section(
    section: str,
    cases: list[_NarrativeCase],
    seen: set[tuple[str, str, str]],
) -> None:
    multi = re.search(
        r"在(?P<company>.+?)抽取了\d+批次食品，即(?P<body>.+?)上述[^经]*经检验，均为(?P<item>[^。；;]+?)项目不合格",
        section,
    )
    if multi:
        company = multi.group("company")
        item = multi.group("item")
        for pm in re.finditer(
            r"([^，,]+?)（[^）]*?(?:购进日期|生产日期|加工时间|抽检编号)",
            multi.group("body"),
        ):
            _add_sichuan_case(cases, seen, company, pm.group(1), item)
        return
    for m in _RE_SC_SUMMARY_SAMPLE.finditer(section):
        _add_sichuan_case(
            cases,
            seen,
            m.group("company"),
            m.group("product"),
            m.group("item"),
        )


def _extract_sichuan_announce_cases(text: str) -> list[_NarrativeCase]:
    """凉山/南充/自贡等：通告正文内嵌不合格描述。"""
    compact = _strip_disposal_chrome(text)
    for marker in (
        "现将监督抽检不合格食品具体情况通告如下：",
        "现将监督抽检不合格食品具体情况重点通告如下：",
        "现将监督抽检不合格食品具体情况通告如下",
        "现将监督抽检不合格食用农产品具体情况通告如下：",
        "现将监督抽检不合格食用农产品具体情况通告如下",
        "监督抽检不合格食品具体情况通告如下：",
        "监督抽检不合格食品具体情况通告如下",
        "不合格食品具体情况通告如下：",
        "不合格食品具体情况重点通告如下：",
        "不合格食品具体情况通告如下",
        "不合格食用农产品具体情况通告如下：",
        "不合格食用农产品具体情况通告如下",
    ):
        pos = compact.find(marker)
        if pos >= 0:
            compact = compact[pos + len(marker) :]
            break
    cases: list[_NarrativeCase] = []
    seen: set[tuple[str, str, str]] = set()
    for m in _RE_SC_ANNOUNCE_QUOTED.finditer(compact):
        company = _clean_sichuan_entity(m.group("company"))
        if not company:
            continue
        _add_sichuan_case(
            cases,
            seen,
            company,
            m.group("product"),
            m.group("item"),
        )
        tail = compact[m.end() : m.end() + 220]
        stop = re.search(
            r"(?:[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）|检验机构|消费者如在)",
            tail,
        )
        abbr_slice = tail[: stop.start()] if stop else tail
        for am in _RE_SC_ANNOUNCE_ABBR_SALE.finditer(abbr_slice):
            _add_sichuan_case(
                cases,
                seen,
                company,
                am.group("product"),
                am.group("item"),
            )
    if cases:
        return cases
    for pattern in (_RE_SC_ANNOUNCE_SALE, _RE_SC_ANNOUNCE_PRODUCE):
        for m in pattern.finditer(compact):
            _add_sichuan_case(
                cases,
                seen,
                m.group("company"),
                m.group("product"),
                m.group("item"),
            )
    return cases


def _extract_sichuan_cases(text: str) -> list[_NarrativeCase]:
    disposal = _extract_sichuan_disposal_cases(text)
    if disposal:
        return disposal
    announce = _extract_sichuan_announce_cases(text)
    if announce:
        return announce
    return _extract_sichuan_xbj_table(text)


def _extract_zhejiang_numbered_cases(text: str) -> list[_NarrativeCase]:
    cases: list[_NarrativeCase] = []
    for m in _RE_ZJ_NUMBERED.finditer(text):
        company = _clean_zhejiang_entity(m.group(1))
        product = _normalize_narrative_product(m.group(2))
        if not _is_valid_zhejiang_entity(company) or not _is_valid_narrative_product(product):
            continue
        item = normalize_failure_item_name(m.group(3).strip())
        cases.append(_NarrativeCase(company, [product], item))
    return cases


def _extract_ningbo_header_case(section: str) -> _NarrativeCase | None:
    compact = re.sub(r"\s+", "", section)
    m = _RE_NINGBO_HEADER.match(compact)
    if not m:
        m = re.search(
            r"^[一二三四五六七八九十百]+、(.+?)(?:购进|销售)[的]?([^（(]+?)(?:[（(]|$)",
            compact,
        )
    if not m:
        return None
    company = _clean_zhejiang_entity(m.group(1))
    products = _split_narrative_products(m.group(2))
    if not company or not products:
        return None
    return _NarrativeCase(company, products, _extract_failure_item(section))


def _extract_case_from_section(section: str) -> _NarrativeCase | None:
    ningbo = _extract_ningbo_header_case(section)
    if ningbo:
        return ningbo

    company = _extract_company(section)
    products = _extract_products(section)
    unqualified_item = _extract_failure_item(section)

    if not company:
        m = _RE_ZJ_OPERATE_HEADER.search(section)
        if m:
            company = _clean_zhejiang_entity(m.group(1))
            product = _normalize_narrative_product(m.group(2))
            if _is_valid_narrative_product(product):
                products = [product]

    if not products and company:
        operated: list[tuple[str, str]] = []
        for m in _RE_ZJ_OPERATED.finditer(section):
            operated.append((m.group(1), m.group(2)))
        for m in _RE_ZJ_SALE_TIGHT.finditer(section):
            if _clean_zhejiang_entity(m.group(1)) == company:
                operated.append((m.group("product"), m.group("item")))
        if operated:
            products = [p for p, _ in operated]
            if not unqualified_item and operated:
                unqualified_item = normalize_failure_item_name(operated[0][1])

    if not _is_valid_zhejiang_entity(company) or not products:
        return None
    return _NarrativeCase(company, products, unqualified_item)


def _cases_from_filename(filepath: str) -> list[_NarrativeCase]:
    m = _RE_ZJ_FILENAME.search(os.path.basename(filepath))
    if not m:
        return []
    company = _clean_zhejiang_entity(m.group(1))
    products = _split_narrative_products(m.group(2))
    if not _is_valid_zhejiang_entity(company) or not products:
        return []
    return [_NarrativeCase(company, products, "")]


def _extract_zhejiang_cases(text: str, filepath: str = "") -> list[_NarrativeCase]:
    compact = _strip_disposal_chrome(text)
    if not compact:
        return []

    cases: list[_NarrativeCase] = []
    seen: set[tuple[str, str]] = set()

    def _add_case(case: _NarrativeCase | None) -> None:
        if not case:
            return
        if case.company != "当事人" and not _is_valid_compact_sale_entity(case.company):
            return
        for product in case.products:
            if not _is_valid_narrative_product(product):
                continue
            key = (case.company, product)
            if key in seen:
                continue
            seen.add(key)
            cases.append(_NarrativeCase(case.company, [product], case.unqualified_item))

    for compact_sale in _extract_compact_sale_chain_cases(compact):
        _add_case(compact_sale)

    for project_item in _extract_project_item_cases(compact):
        _add_case(project_item)

    for produce in _extract_produce_item_cases(compact):
        _add_case(produce)

    for sale_inspect in _extract_sale_inspect_cases(compact):
        _add_case(sale_inspect)

    for huzhou in _extract_huzhou_cases(compact):
        _add_case(huzhou)

    for huzhou_loose in _extract_huzhou_loose_cases(compact):
        _add_case(huzhou_loose)

    for drawn in _extract_drawn_sample_cases(compact):
        _add_case(drawn)

    for drawn_val in _extract_drawn_item_value_cases(compact):
        _add_case(drawn_val)

    for drawn_use in _extract_drawn_use_sample_cases(compact):
        _add_case(drawn_use)

    for drawn_meas in _extract_drawn_measured_cases(compact):
        _add_case(drawn_meas)

    for possess in _extract_possess_fail_cases(compact):
        _add_case(possess)

    for purchase in _extract_purchase_inline_cases(compact):
        _add_case(purchase)

    for produce_pos in _extract_produce_possess_cases(compact):
        _add_case(produce_pos)

    for multi_sale in _extract_multi_sale_section_cases(compact):
        _add_case(multi_sale)

    for third_sale in _extract_third_party_sale_cases(compact):
        _add_case(third_sale)

    for use_mat in _extract_use_material_cases(compact):
        _add_case(use_mat)

    for struct_table in _extract_structured_table_cases(compact):
        _add_case(struct_table)

    for procure in _extract_procure_supervise_cases(compact):
        _add_case(procure)

    for on_sale_dir in _extract_on_sale_direct_cases(compact):
        _add_case(on_sale_dir)

    for process in _extract_process_product_cases(compact):
        _add_case(process)

    for market_sale in _extract_market_inline_sale_cases(compact):
        _add_case(market_sale)

    for residue in _extract_residue_fail_cases(compact):
        _add_case(residue)

    for shop_op in _extract_shop_operate_cases(compact):
        _add_case(shop_op)

    for batch_conc in _extract_batch_conclusion_cases(compact, filepath):
        _add_case(batch_conc)

    for remote in _extract_remote_produce_cases(compact, filepath):
        _add_case(remote)

    for on_sale in _extract_on_sale_sample_cases(compact):
        _add_case(on_sale)

    for stall in _extract_stall_sale_cases(compact):
        _add_case(stall)

    for supply in _extract_supply_inspect_cases(compact):
        _add_case(supply)

    for sale_batch in _extract_sale_batch_cases(compact):
        _add_case(sale_batch)

    for nanxun in _extract_nanxun_party_cases(compact):
        _add_case(nanxun)

    for individual in _extract_individual_sold_cases(compact):
        _add_case(individual)

    for store_sold in _extract_store_sold_cases(compact):
        _add_case(store_sold)

    for compact_fail in _extract_compact_fail_cases(compact):
        _add_case(compact_fail)

    for inline in _extract_produce_sale_inline_cases(compact):
        _add_case(inline)

    for produced_by in _extract_produced_by_cases(compact):
        _add_case(produced_by)

    for sale_sup in _extract_sale_supervise_cases(compact):
        _add_case(sale_sup)

    for party in _extract_party_operated_cases(compact, filepath):
        _add_case(party)

    for locate in _extract_locate_purchase_cases(compact):
        _add_case(locate)

    for structured in _extract_structured_block_cases(compact):
        _add_case(structured)

    for party_prod in _extract_party_product_cases(compact):
        _add_case(party_prod)

    for numbered_loose in _extract_numbered_loose_cases(compact):
        _add_case(numbered_loose)

    for section_prod in _extract_section_produce_cases(compact):
        _add_case(section_prod)

    for section_op in _extract_section_operate_cases(compact):
        _add_case(section_op)

    for supervise_fail in _extract_supervise_fail_cases(compact):
        _add_case(supervise_fail)

    for basic in _extract_basic_inspection_cases(compact):
        _add_case(basic)

    for numbered in _extract_zhejiang_numbered_cases(compact):
        _add_case(numbered)

    for section in _split_zhejiang_top_sections(compact):
        _add_case(_extract_case_from_section(section))

    if cases:
        return cases

    _add_case(_extract_case_from_section(compact))
    return cases


def _extract_dongguon_cases(text: str) -> list[_NarrativeCase]:
    cases: list[_NarrativeCase] = []
    for section in _split_dongguan_sections(text):
        company = _extract_company(section)
        products = _extract_products(section)
        if not company or not products:
            continue
        cases.append(
            _NarrativeCase(company, products, _extract_failure_item(section))
        )
    return cases


def _merge_cases(*groups: list[_NarrativeCase]) -> list[_NarrativeCase]:
    merged: list[_NarrativeCase] = []
    seen: set[tuple[str, str, str]] = set()
    for group in groups:
        for case in group:
            for product in case.products:
                key = (case.company, product, case.unqualified_item)
                if key in seen:
                    continue
                seen.add(key)
                merged.append(_NarrativeCase(case.company, [product], case.unqualified_item))
    return merged


def parse_disposal_narrative_text(
    text: str,
    filepath: str,
    path_province: str = "",
    path_city: str = "",
) -> list[Record]:
    if not text or not _is_narrative_text(text):
        return []

    if not path_province and not path_city:
        path_province, path_city = _extract_location_from_path(filepath)

    year = _extract_year_from_path(filepath)
    filename = os.path.basename(filepath)

    if path_province == "四川省":
        case_groups = (_extract_sichuan_cases(text),)
    elif path_province in ("陕西省", "宁夏回族自治区"):
        case_groups = (_extract_shaanxi_cases(text),)
    elif path_province == "浙江省" or _strip_disposal_chrome(text).find("抽检基本情况") >= 0:
        case_groups = (
            _extract_zhejiang_cases(text, filepath),
            _cases_from_filename(filepath),
        )
    elif path_province == "福建省" or re.search(
        r"\d+、.{4,80}?(?:销售|委托|用于餐饮服务)", _strip_disposal_chrome(text)
    ):
        case_groups = (_extract_fujian_cases(text),)
    else:
        case_groups = (_extract_dongguon_cases(text),)

    cases = _merge_cases(*case_groups)
    if not cases and path_province not in ("浙江省", "四川省", "陕西省", "宁夏回族自治区"):
        cases = _merge_cases(_extract_dongguon_cases(text))

    if not cases:
        return []

    records: list[Record] = []
    for case in cases:
        unqualified_item = case.unqualified_item
        reason = (
            f"不合格项目：{unqualified_item}"
            if unqualified_item
            else "不合格食品通告"
        )
        province, city, display_loc = _merge_location(
            "", "", case.company, "", filepath, path_province, path_city
        )
        for product in case.products:
            records.append(
                Record(
                    status="unqualified",
                    company=case.company,
                    product=product,
                    province=province,
                    city=city,
                    province_city=display_loc,
                    unqualified_item=unqualified_item,
                    reason=reason,
                    category="",
                    source_file=filepath,
                    source_file_name=filename,
                    source_sheet="正文",
                    source_province=path_province,
                    source_city=path_city,
                    sampled_unit=case.company,
                    manufacturer=case.company,
                    year=year,
                )
            )
    return records


_DISPOSAL_PERIOD_RE = re.compile(r"(\d{4})年\s*第(\d+)期")


def _disposal_period_token(filepath: str) -> str | None:
    match = _DISPOSAL_PERIOD_RE.search(os.path.basename(filepath))
    if not match:
        return None
    return f"{match.group(1)}年第{match.group(2)}期"


def should_skip_risk_control_followup(filepath: str) -> bool:
    """同一期已有核查处置正文时，跳过风险控制正文，避免同批次重复计数。"""
    name = os.path.basename(filepath)
    if "风险控制" not in name:
        return False
    token = _disposal_period_token(filepath)
    if not token:
        return False
    year_dir = os.path.dirname(os.path.dirname(filepath))
    if not os.path.isdir(year_dir):
        return False
    year, issue = token.replace("年第", " ").replace("期", "").split()
    for sibling_dir in os.listdir(year_dir):
        if "核查处置" not in sibling_dir:
            continue
        compact = re.sub(r"\s+", "", sibling_dir)
        if f"{year}年第{issue}期" not in compact:
            continue
        folder = os.path.join(year_dir, sibling_dir)
        if not os.path.isdir(folder):
            continue
        for fname in os.listdir(folder):
            lower = fname.lower()
            if "_正文." not in lower and not lower.endswith(".pdf"):
                continue
            if os.path.isfile(os.path.join(folder, fname)):
                return True
    return False


def parse_disposal_narrative_file(filepath: str) -> list[Record]:
    from food_inspection.parser.disposal_dedup import (
        claim_disposal_body,
        should_skip_disposal_narrative,
    )

    text = extract_disposal_narrative_text(filepath)
    if not text:
        return []
    skip = should_skip_disposal_narrative(filepath, text)
    if skip:
        return []
    if not claim_disposal_body(filepath, text):
        return []
    path_province, path_city = _extract_location_from_path(filepath)
    return parse_disposal_narrative_text(text, filepath, path_province, path_city)
