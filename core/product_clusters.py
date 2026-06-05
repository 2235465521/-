"""产品同类词库：将用户输入扩展为一组相关检索词。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from paths import PRODUCT_CLUSTERS_PATH

_CACHE: list[dict] | None = None


def _default_clusters() -> list[dict]:
    return [
        {
            "id": "oral_care",
            "name": "口腔护理用品",
            "keywords": ["牙膏", "牙刷", "牙杯", "漱口杯", "牙线", "口腔", "牙齿"],
        }
    ]


def load_clusters(force: bool = False) -> list[dict]:
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE
    path = Path(PRODUCT_CLUSTERS_PATH)
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            clusters = raw.get("clusters") if isinstance(raw, dict) else raw
            if isinstance(clusters, list) and clusters:
                _CACHE = clusters
                return _CACHE
        except (OSError, json.JSONDecodeError):
            pass
    _CACHE = _default_clusters()
    return _CACHE


def list_clusters_brief() -> list[dict]:
    out: list[dict] = []
    for c in load_clusters():
        kws = [str(x).strip() for x in (c.get("keywords") or []) if str(x).strip()]
        if not kws:
            continue
        out.append(
            {
                "id": c.get("id") or "",
                "name": c.get("name") or c.get("id") or "",
                "keywords": kws,
                "sample": "、".join(kws[:6]) + ("…" if len(kws) > 6 else ""),
            }
        )
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").strip())


def _keyword_matches(query: str, keyword: str) -> bool:
    q, k = _norm(query), _norm(keyword)
    if not q or not k or len(q) < 2:
        return q == k and bool(q)
    if q == k:
        return True
    if q in k or k in q:
        return True
    return False


def resolve_keywords(query: str) -> dict:
    """根据输入解析扩展关键词列表。"""
    q = (query or "").strip()
    if not q:
        return {
            "query": "",
            "keywords": [],
            "clusters": [],
            "cluster_names": [],
            "expanded": False,
        }

    matched_clusters: list[dict] = []
    keywords: list[str] = []
    seen_kw: set[str] = set()

    def add_kw(kw: str) -> None:
        k = kw.strip()
        if not k or k in seen_kw:
            return
        seen_kw.add(k)
        keywords.append(k)

    add_kw(q)

    for cluster in load_clusters():
        kws = [str(x).strip() for x in (cluster.get("keywords") or []) if str(x).strip()]
        name = str(cluster.get("name") or "").strip()
        hit = _keyword_matches(q, name)
        if not hit:
            for kw in kws:
                if _keyword_matches(q, kw):
                    hit = True
                    break
        if hit:
            matched_clusters.append(
                {
                    "id": cluster.get("id") or "",
                    "name": name or cluster.get("id") or "",
                }
            )
            for kw in kws:
                add_kw(kw)

    cluster_names = [c["name"] for c in matched_clusters if c.get("name")]
    return {
        "query": q,
        "keywords": keywords,
        "clusters": matched_clusters,
        "cluster_names": cluster_names,
        "matched_keyword": q,
        "expanded": len(keywords) > 1 or bool(matched_clusters),
    }


def suggest_phrases(query: str, limit: int = 8) -> list[str]:
    """联想：匹配到的同类组名称 + 组内关键词。"""
    q = (query or "").strip()
    if not q:
        return []
    phrases: list[str] = []
    seen: set[str] = set()

    def add(p: str) -> None:
        p = p.strip()
        if not p or p in seen:
            return
        seen.add(p)
        phrases.append(p)

    resolved = resolve_keywords(q)
    for name in resolved.get("cluster_names") or []:
        add(name)
    for kw in resolved.get("keywords") or []:
        add(kw)
        if len(phrases) >= limit:
            return phrases[:limit]

    if len(phrases) < limit:
        for cluster in load_clusters():
            for kw in cluster.get("keywords") or []:
                k = str(kw).strip()
                if k and q in k:
                    add(k)
                if len(phrases) >= limit:
                    return phrases[:limit]
    return phrases[:limit]
