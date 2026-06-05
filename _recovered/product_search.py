"""同类产品标准检索服务。"""

from __future__ import annotations

from pathlib import Path

from config import PRODUCT_CLUSTERS_PATH
from core.db import db
from core.product_clusters import list_clusters_meta, resolve_keywords
from core.suggest import extract_phrases


class ProductSearch:
    def _clusters_ok(self) -> bool:
        return Path(PRODUCT_CLUSTERS_PATH).is_file()

    def is_ready(self) -> bool:
        return db.is_ready() and self._clusters_ok()

    def describe(self) -> str:
        if not db.is_ready():
            return "同类产品标准未就绪（需标准库索引）"
        if not self._clusters_ok():
            return "同类产品标准未就绪（缺少 data/product_clusters.json）"
        n = len(list_clusters_meta())
        return f"同类产品标准已就绪（{n} 个产品组，可编辑 product_clusters.json）"

    def list_clusters(self) -> list[dict]:
        return list_clusters_meta()

    def resolve(self, query: str) -> dict:
        return resolve_keywords(query)

    def suggest(self, query: str, *, limit: int = 10) -> dict:
        q = (query or "").strip()
        resolved = resolve_keywords(q)
        phrases = extract_phrases(q)[:5]
        items: list[dict] = []
        for c in list_clusters_meta():
            for kw in c.get("keywords") or []:
                if q and q not in kw and kw not in q:
                    continue
                items.append(
                    {
                        "title": f"{kw}（{c['name']}）",
                        "std_id": "",
                        "tuangbiao_id": None,
                    }
                )
                if len(items) >= limit:
                    break
            if len(items) >= limit:
                break
        return {"phrases": phrases, "items": items[:limit], "resolved": resolved}

    def search_page(
        self,
        query: str,
        *,
        page: int = 1,
        per_page: int = 10,
        pdf_only: bool = True,
        std_folder: str | None = None,
    ) -> dict:
        if not self.is_ready():
            return {"error": "标准库未就绪，请先运行 python build_index.py 或配置 MySQL"}
        resolved = resolve_keywords(query)
        keywords = resolved.get("keywords") or []
        if not keywords:
            return {"error": "请输入有效的产品名称"}
        primary = resolved.get("matched_keyword") or query
        data = db.search_page_cluster(
            keywords,
            page=page,
            per_page=per_page,
            pdf_only=pdf_only,
            std_folder=std_folder,
            primary_keyword=primary,
        )
        if data.get("error"):
            return data
        return {
            **data,
            "search_mode": "product_cluster",
            "resolved": resolved,
        }


product_search = ProductSearch()
