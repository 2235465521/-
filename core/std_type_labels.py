"""标准类型代号 → 中文名映射，用于「标准类型」分组下拉。

分组大类（依据 std_base.std_type_no）：
    00 国家标准 / 01 行业标准 / 02 地方标准 / 03 团体标准 / 04 ISO / 05 IEC

- 国家标准：GB(强制)/GB/T(推荐)/GB/Z(指导) 等，中文名标注层级。
- 行业标准：两字母代号 → 对应行业中文名（如 AQ→安全生产、BB→包装）。
- 地方标准：DB 等，统一标注「地方标准」。
- 团体 / ISO / IEC：单独成组，避免隐藏数据。

标签函数均返回「代号 中文名」形式的完整展示串，分组下拉的 option.value
仍使用原始代号，保证后端按 std_type 精确过滤不受影响。
"""

from __future__ import annotations

import re

# 行业标准两字母代号 → 中文行业名（依据《行业标准代号管理规定》对照）
INDUSTRY_NAMES: dict[str, str] = {
    "AQ": "安全生产",
    "BB": "包装",
    "CB": "船舶",
    "CJ": "城镇建设",
    "CY": "新闻出版",
    "DA": "档案",
    "DL": "电力",
    "DZ": "地质矿产",
    "EJ": "核工业",
    "FZ": "纺织",
    "GA": "公共安全",
    "GH": "供销合作",
    "GY": "广播电影电视",
    "HB": "航空",
    "HG": "化工",
    "HJ": "环境保护",
    "HS": "海关",
    "HY": "海洋",
    "JB": "机械",
    "JC": "建材",
    "JG": "建筑工业",
    "JR": "金融",
    "JT": "交通",
    "JY": "教育",
    "KA": "矿山安全",
    "LB": "旅游",
    "LD": "劳动和劳动安全",
    "LS": "粮食",
    "LY": "林业",
    "MH": "民用航空",
    "MT": "煤炭",
    "MZ": "民政",
    "NB": "能源",
    "NY": "农业",
    "QB": "轻工",
    "QC": "汽车",
    "QX": "气象",
    "RB": "认证认可",
    "SB": "国内贸易",
    "SC": "水产",
    "SF": "司法行政",
    "SH": "石油化工",
    "SJ": "电子",
    "SL": "水利",
    "SN": "出入境检验检疫",
    "SY": "石油天然气",
    "TB": "铁路运输",
    "TD": "土地管理",
    "TY": "体育",
    "WB": "物资",
    "WH": "文化",
    "WJ": "兵工民品",
    "WM": "外经贸",
    "WS": "卫生",
    "WW": "文物保护",
    "XB": "稀土",
    "XF": "消防",
    "YB": "黑色冶金",
    "YC": "烟草",
    "YD": "通信",
    "YS": "有色金属",
    "YY": "医药",
    "YZ": "邮政",
    "ZY": "中医药",
    "CH": "测绘",
    "GM": "密码",
    "DY": "地震",
    "RF": "人民防空",
    "SW": "水文",
    "ZB": "专业标准",
    "JGJ": "建筑工程",
    "CBM": "船舶（民用）",
    "JS": "建设",
}

# 需要精确匹配的特例（代号含斜杠 / 非两字母 / 历史写法）
EXACT_NAMES: dict[str, str] = {
    "NB/SH/T": "能源/石化",
    "ZBW": "专业标准（文具）",
    "ZBY": "专业标准（轻工）",
    "QBJS": "轻工（建设）",
    "JCJ/T": "建材（建工）",
}

# 描述性文本条目（本身已是中文，原样展示即可）
DESCRIPTIVE = {
    "行标", "方法标准", "产品标准", "基础标准",
    "管理标准", "通用", "其他标准", "团标", "地标", "国标",
}


def industry_name(std_type: str) -> str:
    """把行业标准代号解析为中文行业名；无法识别返回空串。"""
    t = (std_type or "").strip().rstrip("/")
    if not t:
        return ""
    if t in EXACT_NAMES:
        return EXACT_NAMES[t]
    if t in DESCRIPTIVE:
        return t
    m = re.match(r"^([A-Za-z]+)(?:/[A-Za-z]+)?$", t)
    if m:
        b = m.group(1).upper()
        # 结尾 T/Z 误写（如 NBT/DLT/CBT）→ 视作省略了斜杠的 /T //Z
        if b.endswith(("T", "Z")) and len(b) > 2:
            cand = b[:-1]
            if cand in INDUSTRY_NAMES:
                return INDUSTRY_NAMES[cand]
        if b in INDUSTRY_NAMES:
            return INDUSTRY_NAMES[b]
    return ""


def national_label(t: str) -> str:
    m = {
        "GB": "强制性国家标准",
        "GB/T": "推荐性国家标准",
        "GB/Z": "指导性国家标准",
        "国标": "国家标准",
    }
    return f"{t} {m.get(t, '国家标准')}"


def local_label(t: str) -> str:
    return f"{t} 地方标准"


def iso_label(t: str) -> str:
    if t == "ISO":
        return "ISO 国际标准化组织"
    if t == "IEC":
        return "IEC 国际电工委员会"
    return t


def group_label(t: str) -> str:
    if t in ("T", "团标"):
        return "团体标准"
    return t


def industry_label(t: str) -> str:
    name = industry_name(t)
    if name:
        # 描述性文本条目（行标/方法标准…）本身就是中文，不再重复拼接
        if t in DESCRIPTIVE:
            return t
        return f"{t} {name}"
    return t
