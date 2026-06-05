"""团标 / 制度目录索引文件批量 ZIP 打包。"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from core.batch_download import _unique_name
from core.disk_catalog import DiskCatalog

MAX_CATALOG_BULK = 100


def build_zip_from_catalog_ids(
    catalog: DiskCatalog,
    file_ids: list[int],
) -> tuple[io.BytesIO, dict[str, Any]]:
    unique: list[int] = []
    seen: set[int] = set()
    for raw in file_ids:
        try:
            fid = int(raw)
        except (TypeError, ValueError):
            continue
        if fid <= 0 or fid in seen:
            continue
        seen.add(fid)
        unique.append(fid)
        if len(unique) >= MAX_CATALOG_BULK:
            break

    buf = io.BytesIO()
    used_names: set[str] = set()
    results: list[dict] = []
    ok_count = 0

    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for idx, fid in enumerate(unique, start=1):
            entry = catalog.get_by_id(fid)
            path = catalog.resolve_path(fid)
            if not entry or not path:
                results.append(
                    {
                        "id": fid,
                        "status": "not_found",
                        "message": "索引记录或文件不存在",
                    }
                )
                continue
            prefix = f"{idx:03d}_"
            arc_name = _unique_name(used_names, prefix + entry.filename)
            folder = "PDF" if entry.file_ext == ".pdf" else "文件"
            zf.write(path, arcname=f"{folder}/{arc_name}")
            ok_count += 1
            results.append(
                {
                    "id": fid,
                    "status": "ok",
                    "filename": entry.filename,
                    "category": entry.category,
                    "title": entry.title,
                    "zip_entry": arc_name,
                }
            )

        manifest = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "catalog": catalog.name,
            "total": len(unique),
            "success": ok_count,
            "failed": len(unique) - ok_count,
            "results": results,
        }
        zf.writestr(
            "_批量下载清单.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
        lines = [
            f"{catalog.name} 批量下载清单",
            f"生成时间：{manifest['generated_at']}",
            f"共 {len(unique)} 条，成功 {ok_count} 条，失败 {len(unique) - ok_count} 条",
            "",
        ]
        for r in results:
            mark = "✓" if r.get("status") == "ok" else "✗"
            lines.append(
                f"{mark} id={r.get('id')} | {r.get('filename') or r.get('message') or '—'}"
            )
        zf.writestr("_批量下载清单.txt", "\n".join(lines))

    buf.seek(0)
    return buf, {
        "total": len(unique),
        "success": ok_count,
        "failed": len(unique) - ok_count,
        "results": results,
    }
