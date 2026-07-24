"""自然语言 → 标准检索筛选条件（智谱 GLM）。"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from settings import ZHIPU_API_BASE, ZHIPU_API_KEY, ZHIPU_MODEL


def _system_prompt() -> str:
    year = datetime.now().year
    return f"""你是「标准 PDF 下载平台」的检索意图解析助手。
今天是公历 {year} 年。用户会用自然语言描述想找的标准，请将其解析为 JSON 筛选条件，供系统查询标准库。

只输出一个 JSON 对象，不要 Markdown、不要解释。字段如下（无信息则省略该字段或置空）：
{{
  "q": "标准编号或名称关键词（短词，如 煤矿、GB/T 1002）",
  "ex_state": "1=现行，0=废止，2=即将实施；不确定则省略",
  "std_type": "标准类型原文，如 国家标准、行业标准、地方标准、团体标准",
  "province": "省/直辖市名，如 山东、北京",
  "city": "市名",
  "county": "区/县名",
  "product": "产品/品类词，如 饮料、牙膏",
  "company": "起草单位/公司名关键词",
  "unit_rank": "起草顺位：1/2/3 或 gt3（第4及以后）；需配合 company",
  "year_from": 起始年份整数,
  "year_to": 截止年份整数,
  "pdf_only": "1 只要有PDF，0 不限；默认 1",
  "summary": "一句话复述你理解的检索意图"
}}

规则：
- 「近N年」以 {year} 为截止年，year_from={year}-N+1，year_to={year}
- 「现行/有效」→ ex_state=1；「废止/作废」→ 0
- 「国标/国家标准」→ std_type 填「国家标准」（系统会映射为 GB）；「地标」→ 地方标准；「团标」→ 团体标准；「行标」可不填 std_type，把主题词放进 q/product
- 品类词（饮料、牙膏等）优先放入 product，主题词也可放 q
- 不要编造不存在的标准号
- 输出必须是合法 JSON
"""


def ai_configured() -> bool:
    return bool((ZHIPU_API_KEY or "").strip())


def _extract_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("模型返回为空")
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.I)
    if fence:
        raw = fence.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            raise ValueError("模型未返回可解析的 JSON")
        data = json.loads(m.group(0))
    if not isinstance(data, dict):
        raise ValueError("模型返回不是 JSON 对象")
    return data


def _normalize_filters(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}

    def _s(key: str) -> str:
        v = data.get(key)
        if v is None:
            return ""
        return str(v).strip()

    q = _s("q")
    if q:
        out["q"] = q

    ex = _s("ex_state")
    if ex in ("0", "1", "2"):
        out["ex_state"] = ex
    elif ex in ("现行", "有效"):
        out["ex_state"] = "1"
    elif ex in ("废止", "作废"):
        out["ex_state"] = "0"
    elif ex in ("即将实施",):
        out["ex_state"] = "2"

    for key in ("std_type", "province", "city", "county", "product", "company"):
        val = _s(key)
        if val:
            out[key] = val

    # 库内 std_type 多为 GB/T、DB、AQ 等代号，将口语类型映射为可 LIKE 匹配的片段
    type_map = {
        "国家标准": "GB",
        "国标": "GB",
        "行业标准": "",  # 代号分散，改靠关键词
        "行标": "",
        "地方标准": "DB",
        "地标": "DB",
        "团体标准": "T/",
        "团标": "T/",
        "企业标准": "Q/",
        "国际标准": "ISO",
    }
    mapped = type_map.get(out.get("std_type", ""))
    if mapped is not None:
        if mapped:
            out["std_type"] = mapped
        else:
            out.pop("std_type", None)

    # 「饮料相关」等品类：同时写入 product，便于产品簇扩展
    if out.get("q") and not out.get("product"):
        product_hints = ("饮料", "牙膏", "牛奶", "白酒", "茶叶", "酱油", "化妆品")
        for hint in product_hints:
            if hint in out["q"] or hint in _s("summary"):
                out["product"] = hint
                break

    rank = _s("unit_rank").lower()
    if rank in ("1", "2", "3", "gt3"):
        out["unit_rank"] = rank

    for key in ("year_from", "year_to"):
        raw = data.get(key)
        if raw is None or raw == "":
            continue
        try:
            year = int(str(raw).strip())
            if 1900 <= year <= 2100:
                out[key] = year
        except ValueError:
            pass

    pdf_only = _s("pdf_only")
    if pdf_only in ("0", "1"):
        out["pdf_only"] = pdf_only
    else:
        out["pdf_only"] = "1"

    summary = _s("summary")
    if summary:
        out["summary"] = summary

    # 至少要有可检索条件
    searchable = any(
        out.get(k)
        for k in (
            "q",
            "ex_state",
            "std_type",
            "province",
            "city",
            "county",
            "product",
            "company",
            "year_from",
            "year_to",
        )
    )
    if not searchable:
        raise ValueError("未能从描述中解析出可用检索条件，请换一种说法或补充关键词")
    return out


def parse_natural_query(prompt: str) -> dict[str, Any]:
    text = (prompt or "").strip()
    if not text:
        raise ValueError("请输入自然语言检索需求")
    if not ai_configured():
        raise RuntimeError("未配置智谱 API Key")

    url = f"{ZHIPU_API_BASE.rstrip('/')}/chat/completions"
    payload = {
        "model": ZHIPU_MODEL,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": text},
        ],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {ZHIPU_API_KEY.strip()}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"智谱 API 调用失败（HTTP {e.code}）：{err[:300]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"无法连接智谱 API：{e.reason}") from e

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"智谱 API 返回格式异常：{json.dumps(body, ensure_ascii=False)[:300]}") from e

    filters = _normalize_filters(_extract_json(content))
    return {
        "ok": True,
        "prompt": text,
        "filters": filters,
        "raw": content if isinstance(content, str) else str(content),
    }
