"""Excel/PDF 文件读取。"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections import Counter
from typing import Any

import pandas as pd

from food_inspection.parser.text import _clean

_RAPIDOCR_ENGINE: Any = None
_OCR_LOCK = threading.Lock()


def _bootstrap_ocr_runtime_env() -> None:
    """在首次加载 ONNX 前补齐 cuDNN/CUDA 库路径（Linux GPU 服务器）。"""
    if os.environ.get("_PDF_OCR_ENV_BOOTSTRAPPED"):
        return
    os.environ["_PDF_OCR_ENV_BOOTSTRAPPED"] = "1"

    lib_dirs: list[str] = []
    for path in (
        "/usr/local/lib/python3.10/dist-packages/nvidia/cudnn/lib",
        "/usr/local/cuda/lib64",
        "/usr/lib/x86_64-linux-gnu",
    ):
        if os.path.isdir(path):
            lib_dirs.append(path)
    try:
        import nvidia.cudnn
        from pathlib import Path

        cudnn_lib = Path(nvidia.cudnn.__file__).resolve().parent / "lib"
        if cudnn_lib.is_dir():
            lib_dirs.insert(0, str(cudnn_lib))
    except ImportError:
        pass

    if lib_dirs:
        existing = os.environ.get("LD_LIBRARY_PATH", "")
        prepend = ":".join(lib_dirs)
        if not existing.startswith(prepend):
            os.environ["LD_LIBRARY_PATH"] = prepend + (":" + existing if existing else "")


_bootstrap_ocr_runtime_env()


def _ocr_use_cuda() -> bool:
    env = os.environ.get("PDF_OCR_USE_CUDA", "auto").strip().lower()
    if env in ("0", "false", "no"):
        return False
    if env in ("1", "true", "yes"):
        return True
    try:
        import onnxruntime as ort

        return "CUDAExecutionProvider" in ort.get_available_providers()
    except Exception:
        return False


def _get_rapidocr_engine() -> Any | None:
    global _RAPIDOCR_ENGINE
    if _RAPIDOCR_ENGINE is not None:
        return _RAPIDOCR_ENGINE
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return None
    if _ocr_use_cuda():
        _RAPIDOCR_ENGINE = RapidOCR(
            det_use_cuda=True, cls_use_cuda=True, rec_use_cuda=True
        )
    else:
        _RAPIDOCR_ENGINE = RapidOCR()
    return _RAPIDOCR_ENGINE


def _pdf_rows_have_header(raw_rows: list[list[Any]]) -> bool:
    return any(_pdf_row_is_header_row(cells) for cells in raw_rows)



def _trim_sheet_rows(rows: list[list[Any]]) -> list[list[Any]]:
    trimmed: list[list[Any]] = []
    for row in rows:
        cells: list[Any] = []
        for cell in row:
            if cell is None:
                cells.append("")
            else:
                cells.append(cell)
        while cells and not _clean(cells[-1]):
            cells.pop()
        if any(_clean(c) for c in cells):
            trimmed.append(cells)
    return trimmed


def _read_all_sheets_via_com(filepath: str) -> list[tuple[str, list[list[Any]], str]]:
    """Windows 备用：加密或特殊 OLE 格式 Excel 用 COM 读取。"""
    if os.name != "nt":
        return []
    try:
        import win32com.client  # type: ignore
    except ImportError:
        return []

    excel = None
    workbook = None
    sheets: list[tuple[str, list[list[Any]], str]] = []
    try:
        excel = win32com.client.Dispatch("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        workbook = excel.Workbooks.Open(os.path.abspath(filepath), ReadOnly=True)
        for sheet in workbook.Worksheets:
            used = sheet.UsedRange
            if used is None:
                continue
            values = used.Value
            if values is None:
                continue
            if not isinstance(values, tuple):
                values = ((values,),)
            rows = [list(row) for row in values]
            rows = _trim_sheet_rows(rows)
            if not rows:
                continue
            sheet_text = "".join(_clean(c) for row in rows[:20] for c in row)
            sheets.append((str(sheet.Name), rows, sheet_text))
    except Exception:
        return []
    finally:
        if workbook is not None:
            try:
                workbook.Close(False)
            except Exception:
                pass
        if excel is not None:
            try:
                excel.Quit()
            except Exception:
                pass
    return sheets


def _libreoffice_executable() -> str:
    for candidate in (
        os.environ.get("LIBREOFFICE_PATH", ""),
        shutil.which("libreoffice") or "",
        shutil.which("soffice") or "",
        "/usr/bin/libreoffice",
        "/usr/bin/soffice",
    ):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return ""


def _read_all_sheets_via_libreoffice(filepath: str) -> list[tuple[str, list[list[Any]], str]]:
    """Linux 备用：xlrd 报 encrypted 的旧版 .xls 用 LibreOffice 转 xlsx 再读。"""
    if os.name == "nt":
        return []

    executable = _libreoffice_executable()
    if not executable:
        return []

    sheets: list[tuple[str, list[list[Any]], str]] = []
    tmpdir = tempfile.mkdtemp(prefix="food_xls_conv_")
    try:
        env = os.environ.copy()
        env.pop("LD_LIBRARY_PATH", None)
        result = subprocess.run(
            [
                executable,
                "--headless",
                "--convert-to",
                "xlsx",
                "--outdir",
                tmpdir,
                os.path.abspath(filepath),
            ],
            capture_output=True,
            env=env,
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            return []

        converted = [
            os.path.join(tmpdir, name)
            for name in os.listdir(tmpdir)
            if name.lower().endswith(".xlsx")
        ]
        if not converted:
            return []

        book = pd.read_excel(
            converted[0], sheet_name=None, header=None, dtype=str, engine="openpyxl"
        )
        for sheet_name, df in book.items():
            df = df.fillna("")
            rows = df.values.tolist()
            sheet_text = "".join(_clean(c) for row in rows[:20] for c in row)
            sheets.append((str(sheet_name), rows, sheet_text))
    except Exception:
        return []
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return sheets


def _normalize_pdf_cell(value: Any) -> str:
    text = _clean(value)
    return re.sub(r"\s+", " ", text.replace("\n", " ").replace("\r", " ")).strip()


PDF_PRODUCT_HEADER_TOKENS = (
    "样品名称",
    "食品名称",
    "产品名称",
    "样品名",
    "食品名",
    "被抽样单位",
)


def _pdf_row_compact(cells: list[Any]) -> str:
    return re.sub(r"\s+", "", "".join(_normalize_pdf_cell(c) for c in (cells or [])))


def _pdf_row_is_header_row(cells: list[Any]) -> bool:
    compact = _pdf_row_compact(cells)
    if "序号" not in compact:
        return False
    return any(token in compact for token in PDF_PRODUCT_HEADER_TOKENS)


def _pdf_collect_table_rows(page: Any) -> list[list[Any]]:
    """从单页 PDF 抽取表格行（多种策略）。"""
    collected: list[list[Any]] = []
    seen: set[tuple[str, ...]] = set()

    def _add_rows(table_rows: list[list[Any]] | None) -> None:
        if not table_rows:
            return
        for row in table_rows:
            cells = [_normalize_pdf_cell(c) for c in (row or [])]
            if not any(cells):
                continue
            key = tuple(cells)
            if key in seen:
                continue
            seen.add(key)
            collected.append(cells)

    for table in page.extract_tables() or []:
        _add_rows(table)

    for settings in (
        {"vertical_strategy": "text", "horizontal_strategy": "text"},
        {"vertical_strategy": "lines", "horizontal_strategy": "text"},
    ):
        try:
            for table in page.extract_tables(table_settings=settings) or []:
                _add_rows(table)
        except Exception:
            continue

    single = page.extract_table()
    if single:
        _add_rows(single)

    return collected


def _pdf_lines_to_data_rows(lines: list[str]) -> list[list[Any]]:
    header_idx = None
    for idx, line in enumerate(lines[:30]):
        compact = re.sub(r"\s+", "", line)
        if "序号" not in compact:
            continue
        if any(token in compact for token in PDF_PRODUCT_HEADER_TOKENS):
            header_idx = idx
            break
    if header_idx is None:
        return []

    rows: list[list[Any]] = [[lines[header_idx]]]
    for line in lines[header_idx + 1 :]:
        if line.startswith("（声明") or line.startswith("声明"):
            break
        m = re.match(r"^(\d{1,4})\s+(.+)$", line)
        if not m:
            if rows and len(rows) > 1:
                break
            continue
        rest = m.group(2)
        parts = re.split(r"\s{2,}|\t", rest)
        if len(parts) < 3:
            parts = rest.split()
        rows.append([m.group(1), *parts])
    return rows if len(rows) >= 2 else []


def _pdf_rows_from_text(page: Any) -> list[list[Any]]:
    """文本层表格兜底：按行拆分，识别以序号开头的数据行。"""
    text = page.extract_text() or ""
    if len(text) < 80:
        return []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return _pdf_lines_to_data_rows(lines)


def _tesseract_available() -> str | None:
    """返回 tesseract 可执行路径；不可用则 None。"""
    import shutil

    cmd = os.environ.get("TESSERACT_CMD", "").strip()
    if cmd and os.path.isfile(cmd):
        return cmd
    found = shutil.which("tesseract")
    if found:
        return found
    for base in (
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    ):
        exe = os.path.join(base, "Tesseract-OCR", "tesseract.exe")
        if os.path.isfile(exe):
            return exe
    return None


def _pdf_ocr_page_rows(page: Any) -> list[list[Any]]:
    """扫描件 PDF：Tesseract OCR（效果一般，作兜底）。"""
    try:
        import pytesseract
        from PIL import ImageEnhance
    except ImportError:
        return []

    tesseract_cmd = _tesseract_available()
    if not tesseract_cmd:
        return []
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    try:
        image = page.to_image(resolution=400).original.convert("L")
        image = ImageEnhance.Contrast(image).enhance(1.8)
        text = pytesseract.image_to_string(
            image,
            lang="chi_sim",
            config="--psm 6 -c preserve_interword_spaces=1",
        )
    except Exception:
        return []

    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return _pdf_lines_to_data_rows(lines)


def _pdf_cluster_ocr_boxes(ocr_result: list[Any]) -> list[list[tuple[float, str]]]:
    items: list[tuple[float, float, float, str]] = []
    for entry in ocr_result or []:
        if not entry or len(entry) < 2:
            continue
        box, text = entry[0], _clean(entry[1])
        if not text:
            continue
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        h = max(ys) - min(ys)
        items.append((sum(ys) / len(ys), sum(xs) / len(xs), h, text))

    if not items:
        return []

    items.sort(key=lambda t: t[0])
    heights = [t[2] for t in items if t[2] > 4]
    tol = max((sum(heights) / len(heights)) * 0.65, 14) if heights else 18

    rows: list[list[tuple[float, str]]] = []
    row_y: float | None = None
    cells: list[tuple[float, str]] = []

    for cy, cx, _h, text in items:
        if row_y is None or abs(cy - row_y) <= tol:
            cells.append((cx, text))
            row_y = cy if row_y is None else (row_y + cy) / 2
        else:
            if cells:
                rows.append(sorted(cells, key=lambda x: x[0]))
            cells = [(cx, text)]
            row_y = cy
    if cells:
        rows.append(sorted(cells, key=lambda x: x[0]))

    return rows


def _pdf_merge_ocr_row(cells: list[tuple[float, str]], gap: float = 28) -> list[str]:
    if not cells:
        return []
    merged: list[str] = []
    buf = cells[0][1]
    last_x = cells[0][0]
    for cx, text in cells[1:]:
        if cx - last_x > gap:
            merged.append(buf)
            buf = text
        else:
            buf += text
        last_x = cx
    merged.append(buf)
    return [_clean(c) for c in merged if _clean(c)]


def _pdf_row_looks_like_header(row: list[str]) -> bool:
    compact = _pdf_row_compact(row)
    if "序号" in compact:
        return any(token in compact for token in PDF_PRODUCT_HEADER_TOKENS) or "不合格" in compact
    return "食品名称" in compact and ("被抽样" in compact or "不合格" in compact)


def _pdf_align_rows_to_header(
    header: list[str], data_rows: list[list[str]]
) -> list[list[str]]:
    """按表头列数对齐数据行（扫描 PDF 列数不稳定时补空列）。"""
    col_n = len(header)
    aligned: list[list[str]] = []
    for row in data_rows:
        if len(row) >= col_n:
            aligned.append(row[:col_n])
        elif len(row) > 1:
            padded = row + [""] * (col_n - len(row))
            aligned.append(padded[:col_n])
    return aligned


def _pdf_cluster_ocr_columns(ocr_result: list[Any]) -> list[list[tuple[float, str]]]:
    """扫描表格常呈纵向分列 OCR，按 X 聚类为列。"""
    items: list[tuple[float, float, str]] = []
    for entry in ocr_result or []:
        if not entry or len(entry) < 2:
            continue
        box, text = entry[0], _clean(entry[1])
        if not text:
            continue
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        items.append((sum(xs) / len(xs), sum(ys) / len(ys), text))

    if not items:
        return []

    items.sort(key=lambda t: t[0])
    widths = []
    for i in range(1, len(items)):
        widths.append(items[i][0] - items[i - 1][0])
    col_gap = max(sorted(widths)[len(widths) // 2], 35) if widths else 45

    columns: list[list[tuple[float, str]]] = []
    col_x: float | None = None
    cells: list[tuple[float, str]] = []

    for cx, cy, text in items:
        if col_x is None or abs(cx - col_x) <= col_gap:
            cells.append((cy, text))
            col_x = cx if col_x is None else (col_x + cx) / 2
        else:
            if cells:
                columns.append(sorted(cells, key=lambda x: x[0]))
            cells = [(cy, text)]
            col_x = cx
    if cells:
        columns.append(sorted(cells, key=lambda x: x[0]))

    return columns


def _pdf_columns_to_rows(columns: list[list[tuple[float, str]]]) -> list[list[str]]:
    if not columns:
        return []
    max_len = max(len(col) for col in columns)
    table: list[list[str]] = []
    for row_idx in range(max_len):
        row = [
            _clean(col[row_idx][1]) if row_idx < len(col) else ""
            for col in columns
        ]
        if any(_clean(c) for c in row):
            table.append(row)
    return table


PDF_STANDARD_HEADERS = (
    "序号",
    "标称生产企业名称",
    "标称生产企业地址",
    "被抽样单位名称",
    "被抽样单位地址",
    "食品名称",
    "规格型号",
    "商标",
    "不合格项目",
    "分类",
    "备注",
)

PDF_STRIP_HEADER_HINTS = (
    ("序号", "序号"),
    ("标称生产企业名", "标称生产企业名称"),
    ("标称生产企业地", "标称生产企业地址"),
    ("被抽样单位名称", "被抽样单位名称"),
    ("被抽样单位地址", "被抽样单位地址"),
    ("食品名称", "食品名称"),
    ("规格型号", "规格型号"),
    ("商标", "商标"),
    ("不合格项目", "不合格项目"),
    ("分类", "分类"),
    ("备注", "备注"),
)


def _pdf_split_merged_strip_header(header: str) -> list[str]:
    """OCR 常把相邻表头合并为一格，如「分类备注」「不合格项目商标」。"""
    compact = re.sub(r"\s+", "", _clean(header))
    if not compact:
        return []
    found: list[str] = []
    for hint, canonical in PDF_STRIP_HEADER_HINTS:
        if hint in compact:
            found.append(canonical)
    if found:
        return found
    return [compact]


def _pdf_strip_header_matches(header: str) -> bool:
    compact = re.sub(r"\s+", "", _clean(header))
    return any(hint in compact for hint, _ in PDF_STRIP_HEADER_HINTS)


def _pdf_ocr_is_vertical_column_layout(ocr_result: list[Any]) -> bool:
    """扫描表纵向按列 OCR：每条带首格为表头、后续为多条数据。"""
    strips = _pdf_cluster_ocr_boxes(ocr_result)
    if len(strips) < 5:
        return False
    header_like = 0
    wide = 0
    for cells in strips:
        row = _pdf_merge_ocr_row(cells)
        if len(row) < 2 and not _pdf_strip_header_matches(row[0] if row else ""):
            continue
        if _pdf_strip_header_matches(row[0]):
            header_like += 1
        if len(row) >= 4:
            wide += 1
    return header_like >= 4 and wide >= 3


def _pdf_distribute_strip_data(data_cells: list[str], n_rows: int) -> list[str]:
    if n_rows <= 0:
        return []
    if len(data_cells) <= n_rows:
        return [_clean(c) for c in data_cells] + [""] * (n_rows - len(data_cells))
    chunks: list[str] = []
    idx = 0
    base = len(data_cells) // n_rows
    extra = len(data_cells) % n_rows
    for i in range(n_rows):
        take = base + (1 if i < extra else 0)
        chunks.append("".join(_clean(c) for c in data_cells[idx : idx + take]))
        idx += take
    return chunks


_PDF_DATE_RE = re.compile(r"20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}")

_PDF_COLUMN_HEADER_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("序号", ("序号",)),
    ("标称生产企业名称", ("标识生产", "生产企业名称", "标称生产企业名称", "企业名称")),
    ("标称生产企业地址", ("生产企业地址", "标称生产企业地址", "企业地址")),
    ("被抽样单位名称", ("被抽样单位名称", "被抽样单位")),
    ("被抽样单位地址", ("被抽样单位地址",)),
    ("食品名称", ("样品名称", "样品名", "食品名称", "产品名称")),
    ("规格型号", ("规格型号", "样品规", "规格")),
    ("不合格项目", ("不合格项目", "不合格项目检验")),
    ("检验结果", ("检验结果",)),
    ("备注", ("备注",)),
)


def _pdf_column_header_text(cells: list[str], max_cells: int = 4) -> str:
    return re.sub(r"\s+", "", "".join(_clean(c) for c in cells[:max_cells]))


def _pdf_match_column_header(cells: list[str]) -> str | None:
    compact = _pdf_column_header_text(cells)
    if not compact or len(compact) > 80:
        return None
    for canonical, hints in _PDF_COLUMN_HEADER_RULES:
        if any(h in compact for h in hints):
            if canonical == "被抽样单位名称" and "地址" in compact:
                continue
            return canonical
    return None


def _pdf_column_data_start(cells: list[str]) -> int:
    """跳过列顶多行表头，返回数据区起始下标。"""
    start = 0
    for idx, cell in enumerate(cells[:6]):
        compact = re.sub(r"\s+", "", _clean(cell))
        if not compact:
            start = idx + 1
            continue
        if compact in ("附件1", "附件2", "附件3", "附件4", "附件5"):
            start = idx + 1
            continue
        if _pdf_match_column_header(cells[idx:]):
            start = idx + 1
            continue
        if any(h in compact for _, hints in _PDF_COLUMN_HEADER_RULES for h in hints):
            start = idx + 1
            continue
        break
    return start


def _pdf_is_date_like(text: str) -> bool:
    compact = re.sub(r"\s+", "", _clean(text))
    return bool(_PDF_DATE_RE.search(compact))


def _pdf_chunk_column_cells(cells: list[str], n_rows: int) -> list[str]:
    if n_rows <= 0:
        return []
    cleaned = [_clean(c) for c in cells if _clean(c)]
    if not cleaned:
        return [""] * n_rows
    if len(cleaned) <= n_rows:
        return cleaned + [""] * (n_rows - len(cleaned))
    per = (len(cleaned) + n_rows - 1) // n_rows
    merged: list[str] = []
    for i in range(n_rows):
        chunk = cleaned[i * per : (i + 1) * per]
        merged.append("".join(chunk))
    return merged


def _pdf_count_dates_in_columns(columns: list[list[tuple[float, str]]]) -> int:
    best = 0
    for col_cells in columns:
        texts = [_clean(t) for _, t in col_cells]
        start = _pdf_column_data_start(texts)
        best = max(best, sum(1 for t in texts[start:] if _pdf_is_date_like(t)))
    return best


def _pdf_infer_row_count_from_columns(column_data: dict[str, list[str]]) -> int:
    counts: list[int] = []
    for key in ("食品名称", "被抽样单位名称", "标称生产企业名称", "被抽样单位地址"):
        cells = column_data.get(key, [])
        if cells:
            counts.append(len(cells))
    for cells in column_data.values():
        date_n = sum(1 for c in cells if _pdf_is_date_like(c))
        if date_n:
            counts.append(date_n)
    if not counts:
        return 0
    return Counter(counts).most_common(1)[0][0]


def _pdf_table_from_ocr_column_strips(ocr_result: list[Any]) -> list[list[str]]:
    """广西等地扫描 PDF：按 X 分列，每列自上而下为表头+数据。"""
    columns = _pdf_cluster_ocr_columns(ocr_result)
    if len(columns) < 5:
        return []

    mapped: dict[str, list[str]] = {}
    for col_cells in columns:
        texts = [_clean(t) for _, t in col_cells]
        texts = [t for t in texts if t]
        if not texts:
            continue
        compact = _pdf_column_header_text(texts)
        if len(compact) > 120 or "食品安全监督抽检" in compact or "声明" in compact:
            continue
        header = _pdf_match_column_header(texts)
        if not header:
            continue
        start = _pdf_column_data_start(texts)
        data_cells = [t for t in texts[start:] if t and "声明" not in t]
        if not data_cells:
            continue
        if header in mapped:
            mapped[header].extend(data_cells)
        else:
            mapped[header] = list(data_cells)

    if "食品名称" not in mapped and "被抽样单位名称" not in mapped:
        return []

    n_rows = _pdf_count_dates_in_columns(columns)
    if n_rows < 1:
        n_rows = _pdf_infer_row_count_from_columns(mapped)
    if n_rows < 1:
        n_rows = max(len(v) for v in mapped.values())
    if n_rows < 1:
        return []

    headers = list(PDF_STANDARD_HEADERS)
    table: list[list[str]] = [headers]
    for i in range(n_rows):
        row: list[str] = []
        for h in headers:
            cells = mapped.get(h, [])
            if h == "序号":
                row.append(str(i + 1))
                continue
            if not cells:
                row.append("")
                continue
            if len(cells) == n_rows:
                row.append(_clean(cells[i]))
            else:
                chunked = _pdf_chunk_column_cells(cells, n_rows)
                row.append(chunked[i] if i < len(chunked) else "")
        if any(_clean(c) for c in row[1:]):
            table.append(row)
    return table if len(table) >= 2 else []


def _pdf_table_from_vertical_ocr_strips(ocr_result: list[Any]) -> list[list[str]]:
    """将纵向列条带还原为标准横表（莆田/泉州扫描 PDF）。"""
    if not _pdf_ocr_is_vertical_column_layout(ocr_result):
        return []

    strips: list[tuple[str, list[str]]] = []
    for cells in _pdf_cluster_ocr_boxes(ocr_result):
        row = _pdf_merge_ocr_row(cells)
        if not row or not _pdf_strip_header_matches(row[0]):
            continue
        for header in _pdf_split_merged_strip_header(row[0]):
            strips.append((header, row[1:]))

    if len(strips) < 5:
        return []

    row_count = 0
    for header, data in strips:
        if header == "食品名称" and data:
            row_count = len(data)
            break
    if row_count < 1:
        row_count = max((len(data) for _, data in strips), default=0)
    if row_count < 1:
        return []

    col_data: dict[str, list[str]] = {}
    for header, data in strips:
        col_data[header] = _pdf_distribute_strip_data(list(data), row_count)

    headers = list(PDF_STANDARD_HEADERS)
    table: list[list[str]] = [headers]
    for i in range(row_count):
        row: list[str] = []
        for h in headers:
            val = ""
            if h in col_data and i < len(col_data[h]):
                val = _clean(col_data[h][i])
            if h == "序号" and not val.replace(".", "").isdigit():
                val = str(i + 1)
            row.append(val)
        if any(_clean(c) for c in row[1:]):
            table.append(row)
    return table if len(table) >= 2 else []


def _pdf_render_fitz_page(page: Any, resolution: int = 200) -> Any:
    """PyMuPDF 渲染页面为 RGB numpy 数组（比 pdfplumber 更快）。"""
    import fitz
    import numpy as np

    scale = resolution / 72.0
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, 3
    )


def _pdf_open_fitz(filepath: str) -> Any | None:
    try:
        import fitz
    except ImportError:
        return None
    try:
        return fitz.open(filepath)
    except Exception:
        return None


def _pdf_page_ocr_image(page: Any, resolution: int = 320, max_dim: int = 2600) -> Any:
    """渲染 PDF 页为 OCR 输入；超大页自动缩小避免 ONNX OOM。"""
    import numpy as np
    from PIL import Image

    # PyMuPDF page（fitz.Page）走快速路径
    if hasattr(page, "get_pixmap"):
        image = _pdf_render_fitz_page(page, resolution=resolution)
        h, w = image.shape[:2]
        if max(w, h) > max_dim:
            from PIL import Image as PILImage

            pil = PILImage.fromarray(image)
            scale = max_dim / max(w, h)
            pil = pil.resize(
                (int(w * scale), int(h * scale)), PILImage.Resampling.LANCZOS
            )
            return np.array(pil)
        return image

    image = page.to_image(resolution=resolution).original
    if not isinstance(image, Image.Image):
        return np.array(image)
    w, h = image.size
    if max(w, h) > max_dim:
        scale = max_dim / max(w, h)
        image = image.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    return np.array(image)


def _pdf_run_ocr_on_image(image: Any) -> list[Any] | None:
    engine = _get_rapidocr_engine()
    if engine is None:
        return None
    try:
        with _OCR_LOCK:
            result, _ = engine(image)
        return result
    except Exception:
        return None


def _pdf_run_rapidocr(page: Any, *, fast: bool = False) -> list[Any] | None:
    engine = _get_rapidocr_engine()
    if engine is None:
        return None

    if fast:
        dpi = int(os.environ.get("PDF_OCR_DPI", "200"))
        try:
            image = _pdf_page_ocr_image(page, resolution=dpi)
            return _pdf_run_ocr_on_image(image)
        except Exception:
            return None

    # 低分辨率优先，多数扫描表 220dpi 即可，失败再升高
    for resolution in (220, 260, 320):
        try:
            image = _pdf_page_ocr_image(page, resolution=resolution)
            result = _pdf_run_ocr_on_image(image)
            if result:
                return result
        except Exception:
            continue
    return None


def _pdf_rows_from_rapidocr(page: Any) -> list[list[Any]]:
    """扫描件 PDF：RapidOCR + 按列聚类转成行（莆田/泉州/广西扫描表）。"""
    result = _pdf_run_rapidocr(page)
    if not result:
        return []

    table = _pdf_table_from_ocr_column_strips(result)
    if len(table) >= 2:
        return table

    table = _pdf_table_from_vertical_ocr_strips(result)
    if len(table) < 2:
        columns = _pdf_cluster_ocr_columns(result)
        table = _pdf_columns_to_rows(columns)
    if len(table) < 2:
        table = [_pdf_merge_ocr_row(row) for row in _pdf_cluster_ocr_boxes(result)]
        table = [row for row in table if row]

    header_idx = None
    for idx, row in enumerate(table):
        if _pdf_row_looks_like_header(row):
            header_idx = idx
            break
    if header_idx is None:
        for idx, row in enumerate(table):
            compact = _pdf_row_compact(row)
            if "序号" in compact or ("食品名称" in compact and "不合格" in compact):
                header_idx = idx
                break

    if header_idx is None:
        return []

    headers = [_clean(h) for h in table[header_idx]]
    data_rows: list[list[str]] = []
    for row in table[header_idx + 1 :]:
        cells = [_clean(c) for c in row]
        if not any(cells):
            continue
        joined = "".join(cells)
        if "声明" in joined:
            break
        first = cells[0] if cells else ""
        if first.replace(".", "").isdigit():
            data_rows.append(cells)

    data_rows = _pdf_align_rows_to_header(headers, data_rows)
    if not data_rows:
        return []

    return [headers] + data_rows


COMBINED_PRODUCT_INFO_MARKERS = (
    "食品监督抽检产品信息",
    "食品监督抽检产品信息表",
)


def _is_combined_product_info_file(filepath: str) -> bool:
    compact = os.path.basename(filepath).replace(" ", "")
    return any(m.replace(" ", "") in compact for m in COMBINED_PRODUCT_INFO_MARKERS)


COMBINED_PRODUCT_INFO_HEADERS = (
    "序号",
    "被抽样单位名称",
    "被抽样单位地址",
    "食品名称",
    "规格型号",
    "分类",
    "结论",
    "检验机构",
)


def _ocr_serial_number(cell: str) -> str | None:
    compact = re.sub(r"\s+", "", _clean(cell))
    if not compact:
        return None
    m = re.match(r"^(\d{1,4})(?:\.\d+)?$", compact)
    return m.group(1) if m else None


def _ocr_row_is_verdict(cell: str) -> bool:
    compact = re.sub(r"\s+", "", _clean(cell))
    if not compact:
        return False
    if compact in ("合格", "格合", "合", "符合"):
        return True
    if "不合" in compact or "不格" in compact or "格不合" in compact:
        return True
    if any(tok in cell for tok in ("||", "║", "mg/kg", "μg", "g/kg", "不得检出")):
        return True
    return False


def _ocr_row_verdict_status(verdict_cell: str, extra_cells: list[str]) -> str:
    joined = verdict_cell + "".join(extra_cells)
    compact = re.sub(r"\s+", "", _clean(verdict_cell))
    if compact in ("合格", "格合", "合", "符合"):
        return "qualified"
    if "不合" in compact or "不格" in compact:
        return "unqualified"
    if any(tok in joined for tok in ("||", "║", "mg/kg", "μg", "g/kg", "不得检出")):
        return "unqualified"
    if compact.startswith("合") and len(compact) <= 3:
        return "qualified"
    return "qualified"


def _ocr_row_is_agency(cell: str) -> bool:
    c = _clean(cell)
    return any(k in c for k in ("检验", "检测", "认证", "分析", "测试"))


def _pdf_normalize_row(cells: list[Any]) -> list[str]:
    return [_normalize_pdf_cell(c) for c in cells]


def _pdf_is_data_row(cells: list[Any]) -> bool:
    if not cells or not any(_clean(c) for c in cells):
        return False
    first = _normalize_pdf_cell(cells[0])
    if not first or first in ("序号", "备注"):
        return False
    if first.startswith("（声明") or first.startswith("声明"):
        return False
    return first.replace(".", "").isdigit()


def _pdf_pad_row(row: list[str], col_n: int) -> list[str]:
    if len(row) >= col_n:
        return row[:col_n]
    return row + [""] * (col_n - len(row))


def _pdf_append_page_rows(
    header_row: list[str] | None,
    data_rows: list[list[str]],
    page_rows: list[list[Any]],
    seen: set[tuple[str, ...]],
) -> list[str] | None:
    """合并单页表格行：自动识别表头、跳过重复表头行。"""
    out_header = header_row
    for cells in page_rows:
        norm = _pdf_normalize_row(cells)
        if not any(_clean(c) for c in norm):
            continue
        if _pdf_row_is_header_row(norm) or (
            out_header is None and _pdf_row_looks_like_header(norm)
        ):
            if out_header is None:
                out_header = norm
            continue
        if out_header is None:
            continue
        if not _pdf_is_data_row(norm):
            if "声明" in "".join(norm):
                break
            continue
        padded = _pdf_pad_row(norm, len(out_header))
        key = tuple(padded)
        if key in seen:
            continue
        seen.add(key)
        data_rows.append(padded)
    return out_header


def _extract_ocr_header_table(ocr_result: list[Any]) -> list[list[str]] | None:
    """OCR 聚类后识别表头，按列名映射还原数据（不假设固定列序）。"""
    if not ocr_result:
        return None

    for builder in (_pdf_table_from_ocr_column_strips, _pdf_table_from_vertical_ocr_strips):
        built = builder(ocr_result)
        if len(built) >= 2 and _pdf_row_is_header_row(built[0]):
            headers = _pdf_normalize_row(built[0])
            data = [_pdf_pad_row(_pdf_normalize_row(r), len(headers)) for r in built[1:] if _pdf_is_data_row(r)]
            if data:
                return [headers] + data

    table = [_pdf_merge_ocr_row(cells) for cells in _pdf_cluster_ocr_boxes(ocr_result)]
    table = [_pdf_normalize_row(r) for r in table if r and any(_clean(c) for c in r)]
    if len(table) < 2:
        return None

    header_idx = None
    for idx, row in enumerate(table):
        if _pdf_row_is_header_row(row) or _pdf_row_looks_like_header(row):
            header_idx = idx
            break
    if header_idx is None:
        return None

    from food_inspection.parser.layout import _build_column_map

    headers = table[header_idx]
    col_map = _build_column_map(headers)
    if "product" not in col_map and "sampled_unit" not in col_map:
        return None

    data_rows: list[list[str]] = []
    for row in table[header_idx + 1 :]:
        if not _pdf_is_data_row(row):
            if "声明" in "".join(row):
                break
            continue
        data_rows.append(_pdf_pad_row(row, len(headers)))
    if not data_rows:
        return None
    return [headers] + data_rows


def _pdf_extract_best_page_table(page: Any) -> list[list[Any]]:
    """单页取最佳表格，避免多策略重复提取。"""
    candidates: list[list[list[Any]]] = []
    try:
        for table in page.extract_tables() or []:
            if table and len(table) >= 2:
                candidates.append([[_normalize_pdf_cell(c) for c in row] for row in table])
    except Exception:
        pass

    if not candidates:
        collected = _pdf_collect_table_rows(page)
        if collected:
            return _pdf_dedupe_single_table_rows(collected)
        return _pdf_rows_from_text(page)

    def _score(table: list[list[Any]]) -> tuple[int, int]:
        header = table[0] if table else []
        header_ok = 1 if _pdf_row_is_header_row(header) else 0
        return (header_ok, len(header), len(table))

    return max(candidates, key=_score)


def _pdf_dedupe_single_table_rows(rows: list[list[Any]]) -> list[list[Any]]:
    """多策略提取的重复表只保留第一份。"""
    if not rows:
        return []
    header_idx = None
    for idx, cells in enumerate(rows):
        if _pdf_row_is_header_row(_pdf_normalize_row(cells)):
            header_idx = idx
            break
    if header_idx is None:
        return rows

    header = _pdf_normalize_row(rows[header_idx])
    col_n = len(header)
    result: list[list[Any]] = [header]
    seen: set[tuple[str, ...]] = set()
    for cells in rows[header_idx + 1 :]:
        norm = _pdf_normalize_row(cells)
        if _pdf_row_is_header_row(norm):
            break
        if not _pdf_is_data_row(norm):
            if "声明" in "".join(norm):
                break
            continue
        padded = _pdf_pad_row(norm, col_n)
        key = tuple(padded)
        if key in seen:
            continue
        seen.add(key)
        result.append(padded)
    return result


def _read_pdf_sheet_via_plumber(filepath: str) -> list[tuple[str, list[list[Any]], str]] | None:
    """pdfplumber 提取表格并按表头列映射（支持多页）。"""
    try:
        import pdfplumber
    except ImportError:
        return None

    header_row: list[str] | None = None
    data_rows: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()

    try:
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_rows = _pdf_extract_best_page_table(page)
                header_row = _pdf_append_page_rows(header_row, data_rows, page_rows, seen)
    except Exception:
        return None

    if header_row is None or not data_rows:
        return None

    rows: list[list[Any]] = [header_row] + data_rows
    sheet_text = "".join(_clean(c) for row in rows[:20] for c in row)
    return [("PDF", rows, sheet_text)]


def _read_pdf_sheet_via_ocr(filepath: str) -> list[tuple[str, list[list[Any]], str]] | None:
    """扫描件 PDF：OCR 后识别表头列映射（支持多页）。"""
    ocr_max_pages = max(int(os.environ.get("PDF_OCR_MAX_PAGES", "80")), 1)
    if ocr_max_pages <= 0:
        ocr_max_pages = 10_000

    header_row: list[str] | None = None
    data_rows: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()

    def _consume_page(page: Any) -> None:
        nonlocal header_row
        table = None
        result = _pdf_run_rapidocr(page, fast=False)
        if result:
            table = _extract_ocr_header_table(result)
        if table is None:
            legacy = _pdf_rows_from_rapidocr(page)
            if len(legacy) >= 2:
                table = [_pdf_normalize_row(r) for r in legacy]
        if not table or len(table) < 2:
            return
        page_header = table[0]
        if header_row is None:
            header_row = page_header
        col_n = len(header_row)
        for row in table[1:]:
            if not _pdf_is_data_row(row):
                continue
            padded = _pdf_pad_row(row, col_n)
            key = tuple(padded)
            if key in seen:
                continue
            seen.add(key)
            data_rows.append(padded)

    try:
        doc = _pdf_open_fitz(filepath)
        if doc is not None:
            for i in range(min(len(doc), ocr_max_pages)):
                _consume_page(doc[i])
            doc.close()
        else:
            import pdfplumber

            with pdfplumber.open(filepath) as pdf:
                for page in pdf.pages[:ocr_max_pages]:
                    _consume_page(page)
    except Exception:
        return None

    if header_row is None or not data_rows:
        return None

    rows: list[list[Any]] = [header_row] + data_rows
    sheet_text = "".join(_clean(c) for row in rows[:20] for c in row)
    return [("PDF", rows, sheet_text)]


def _ocr_product_info_data_row(row: list[str]) -> list[str] | None:
    if len(row) < 5:
        return None
    serial = _ocr_serial_number(row[0])
    if not serial:
        return None

    verdict_idx = None
    for idx in range(2, len(row)):
        if _ocr_row_is_verdict(row[idx]):
            verdict_idx = idx
            break
    if verdict_idx is None:
        return None

    unit = _clean(row[1]) if len(row) > 1 else ""
    addr = _clean(row[2]) if len(row) > 2 else ""
    product = _clean(row[3]) if len(row) > 3 else ""
    spec = _clean(row[4]) if len(row) > 4 else ""
    category = _clean(row[5]) if len(row) > 5 and verdict_idx > 5 else ""
    from food_inspection.category_junk import is_junk_category

    if is_junk_category(category):
        category = ""
    verdict = _clean(row[verdict_idx])

    tail_cells = [_clean(c) for c in row[verdict_idx + 1 :] if _clean(c)]
    agency_parts: list[str] = []
    failure_parts: list[str] = []
    for cell in tail_cells:
        if _ocr_row_is_agency(cell) and not failure_parts:
            agency_parts.append(cell)
        elif agency_parts:
            agency_parts.append(cell)
        else:
            failure_parts.append(cell)
    agency = "".join(agency_parts)

    status = _ocr_row_verdict_status(verdict, failure_parts)
    if status == "unqualified":
        if failure_parts:
            verdict = "不合格：" + "；".join(failure_parts)
        elif verdict in ("合不格", "格不合", "不合格"):
            verdict = "不合格"
        else:
            verdict = "不合格：" + verdict
    elif verdict in ("格合", "合"):
        verdict = "合格"

    if not product or product in ("食品名称", "样品名称"):
        return None

    return [
        serial,
        unit,
        addr,
        product,
        spec,
        category,
        verdict,
        agency,
    ]


def _read_combined_product_info_pdf(filepath: str) -> list[tuple[str, list[list[Any]], str]]:
    """扫描版「食品监督抽检产品信息」：优先 OCR 表头映射，兜底简化列 OCR。"""
    max_pages = int(os.environ.get("PDF_PRODUCT_INFO_OCR_MAX_PAGES", "80"))
    if max_pages <= 0:
        max_pages = 10_000

    header_row: list[str] | None = None
    data_rows: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()

    def _consume_page_header(page: Any) -> bool:
        nonlocal header_row
        result = _pdf_run_rapidocr(page, fast=True)
        if not result:
            return False
        table = _extract_ocr_header_table(result)
        if not table or len(table) < 2:
            return False
        page_header = table[0]
        if header_row is None:
            header_row = page_header
        col_n = len(header_row)
        for row in table[1:]:
            if not _pdf_is_data_row(row):
                continue
            padded = _pdf_pad_row(row, col_n)
            key = tuple(padded)
            if key in seen:
                continue
            seen.add(key)
            data_rows.append(padded)
        return True

    try:
        doc = _pdf_open_fitz(filepath)
        if doc is not None:
            for i in range(min(len(doc), max_pages)):
                _consume_page_header(doc[i])
            doc.close()
        else:
            import pdfplumber

            with pdfplumber.open(filepath) as pdf:
                for page in pdf.pages[:max_pages]:
                    _consume_page_header(page)
    except Exception:
        pass

    if header_row is not None and len(data_rows) >= 1:
        rows: list[list[Any]] = [header_row] + data_rows
        sheet_text = "".join(_clean(c) for row in rows[:20] for c in row)
        return [("PDF", rows, sheet_text)]

    # 兜底：东莞等无完整表头的扫描简表（固定列序 OCR）
    legacy_rows: list[list[str]] = []
    legacy_seen: set[tuple[str, ...]] = set()

    def _consume_page_legacy(page: Any) -> None:
        result = _pdf_run_rapidocr(page, fast=True)
        if not result:
            return
        for cells in _pdf_cluster_ocr_boxes(result):
            merged = _pdf_merge_ocr_row(cells)
            parsed = _ocr_product_info_data_row(merged)
            if not parsed:
                continue
            key = tuple(parsed[:4])
            if key in legacy_seen:
                continue
            legacy_seen.add(key)
            legacy_rows.append(parsed)

    try:
        doc = _pdf_open_fitz(filepath)
        if doc is not None:
            for i in range(min(len(doc), max_pages)):
                _consume_page_legacy(doc[i])
            doc.close()
        else:
            import pdfplumber

            with pdfplumber.open(filepath) as pdf:
                for page in pdf.pages[:max_pages]:
                    _consume_page_legacy(page)
    except Exception:
        return []

    if len(legacy_rows) < 2:
        return []

    headers = list(COMBINED_PRODUCT_INFO_HEADERS)
    rows: list[list[Any]] = [headers] + legacy_rows
    sheet_text = "".join(_clean(c) for row in rows[:20] for c in row)
    return [("PDF", rows, sheet_text)]


def _read_pdf_sheet(filepath: str) -> list[tuple[str, list[list[Any]], str]]:
    """解析 PDF 抽检表：优先 pdfplumber 表头映射 → OCR 表头映射 → 简化列 OCR 兜底。"""
    result = _read_pdf_sheet_via_plumber(filepath)
    if result:
        return result

    result = _read_pdf_sheet_via_ocr(filepath)
    if result:
        return result

    if _is_combined_product_info_file(filepath):
        combined = _read_combined_product_info_pdf(filepath)
        if combined:
            return combined

    return []


def _read_all_sheets(filepath: str) -> list[tuple[str, list[list[Any]], str]]:
    ext = os.path.splitext(filepath)[1].lower()
    sheets: list[tuple[str, list[list[Any]], str]] = []

    if ext == ".pdf":
        return _read_pdf_sheet(filepath)

    if ext not in (".xlsx", ".xls"):
        return sheets

    engines: list[str | None] = []
    if ext == ".xlsx":
        engines = ["openpyxl", "xlrd"]
    else:
        engines = ["xlrd", "openpyxl"]

    book = None
    for engine in engines:
        try:
            book = pd.read_excel(filepath, sheet_name=None, header=None, dtype=str, engine=engine)
            break
        except Exception:
            continue

    if book is not None:
        for sheet_name, df in book.items():
            df = df.fillna("")
            rows = df.values.tolist()
            sheet_text = "".join(_clean(c) for row in rows[:20] for c in row)
            sheets.append((str(sheet_name), rows, sheet_text))
        return sheets

    sheets = _read_all_sheets_via_libreoffice(filepath)
    if sheets:
        return sheets

    return _read_all_sheets_via_com(filepath)
