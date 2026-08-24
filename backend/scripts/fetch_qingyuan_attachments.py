#!/usr/bin/env python3
"""从 gdqy.gov.cn 抓取清远市抽检通告附件（绕过 Cloudflare 需 Playwright 会话）。"""

from __future__ import annotations

import argparse
import html
import re
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import DATA_ROOT  # noqa: E402

QY_ROOT = Path(DATA_ROOT) / "广东省" / "清远市"

LIST_URLS = [
    "https://www.gdqy.gov.cn/gdqy/newxxgk/zdly/spypaqbz/zlxx/",
    "https://www.gdqy.gov.cn/channel/qysscjdglj/zdly/zlxx/",
    "https://www.gdqy.gov.cn/xxgk/zzjg/zfjg/qysscjdglj/gzdt/qyscjggg/",
]

FOOD_MARKER = "食品安全监督抽检"
SKIP_TITLE_MARKERS = (
    "工业产品",
    "食品相关产品",
    "实施细则",
)


def _norm_title(text: str) -> str:
    text = html.unescape(text or "")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", "", text)


def _wait_cloudflare(page, *, max_wait: int = 90) -> None:
    for _ in range(max_wait // 2):
        body = page.inner_text("body")
        head = body[:300]
        if "正在验证" not in head and "请稍候" not in head[:80]:
            return
        time.sleep(2)
    raise TimeoutError("Cloudflare 验证超时")


def _list_page_urls(base: str, max_pages: int = 80) -> list[str]:
    base = base.rstrip("/") + "/"
    urls = [base]
    for i in range(2, max_pages + 1):
        urls.append(f"{base}index_{i}.html")
    return urls


def crawl_notice_index(context) -> dict[str, str]:
    """标题 -> 通告页 URL。"""
    page = context.new_page()
    index: dict[str, str] = {}
    try:
        for list_base in LIST_URLS:
            for list_url in _list_page_urls(list_base):
                try:
                    page.goto(list_url, timeout=120_000)
                    _wait_cloudflare(page)
                except Exception:
                    break
                items = page.eval_on_selector_all(
                    "a",
                    """els => els.map(e => ({
                        href: e.href,
                        text: (e.innerText || '').trim()
                    })).filter(x => x.text && x.href.includes('/content/post_'))""",
                )
                if not items:
                    break
                added = 0
                for item in items:
                    title = item.get("text", "")
                    if FOOD_MARKER not in title and "校园食品安全" not in title:
                        continue
                    if any(m in title for m in SKIP_TITLE_MARKERS):
                        continue
                    key = _norm_title(title)
                    if key and key not in index:
                        index[key] = item["href"]
                        added += 1
                if added == 0 and list_url != list_base.rstrip("/") + "/":
                    break
    finally:
        page.close()
    return index


def _pick_attachments(page) -> list[tuple[str, str]]:
    links = page.eval_on_selector_all(
        "a",
        """els => els.map(e => ({
            href: e.href,
            text: (e.innerText || '').trim()
        })).filter(x => x.href && x.href.includes('/attachment/'))""",
    )
    picked: list[tuple[str, str]] = []
    for item in links:
        href = item["href"]
        text = item.get("text", "")
        low = text.lower()
        if not href.lower().endswith((".xls", ".xlsx")):
            continue
        if "合格产品" in text or "合格产品" in href:
            picked.append(("qualified", href))
        elif "不合格产品" in text or "不合格产品" in href:
            picked.append(("unqualified", href))
    return picked


def _target_name(kind: str, original_name: str) -> str:
    ext = Path(original_name).suffix or ".xls"
    if kind == "qualified":
        return f"附件2.监督抽检合格产品信息{ext}"
    return f"附件3.监督抽检不合格产品信息{ext}"


def download_for_folder(context, folder: Path, post_url: str) -> tuple[int, str]:
    page = context.new_page()
    downloaded = 0
    try:
        page.goto(post_url, timeout=120_000)
        _wait_cloudflare(page)
        attachments = _pick_attachments(page)
        if not attachments:
            return 0, "无合格/不合格 xls 附件"
        for kind, href in attachments:
            name = _target_name(kind, Path(href).name)
            target = folder / name
            if target.is_file() and target.stat().st_size > 2048:
                continue
            resp = context.request.get(href)
            if resp.status != 200:
                continue
            body = resp.body()
            if len(body) < 2048 or body[:15].lower().startswith(b"<!doctype"):
                continue
            target.write_bytes(body)
            downloaded += 1
    finally:
        page.close()
    if downloaded == 0 and not any(
        (folder / n).is_file() and (folder / n).stat().st_size > 2048
        for n in (
            "附件2.监督抽检合格产品信息.xls",
            "附件3.监督抽检不合格产品信息.xls",
            "附件2.监督抽检合格产品信息.xlsx",
            "附件3.监督抽检不合格产品信息.xlsx",
        )
    ):
        return 0, "下载失败或附件为空"
    return downloaded, "ok"


def iter_food_folders() -> list[Path]:
    folders: list[Path] = []
    if not QY_ROOT.is_dir():
        return folders
    for year_dir in sorted(QY_ROOT.iterdir()):
        if not year_dir.is_dir():
            continue
        for notice_dir in sorted(year_dir.iterdir()):
            if not notice_dir.is_dir():
                continue
            name = notice_dir.name
            if FOOD_MARKER not in name and "校园食品安全" not in name:
                continue
            if any(m in name for m in SKIP_TITLE_MARKERS):
                continue
            folders.append(notice_dir)
    return folders


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="抓取清远市 gdqy.gov.cn 抽检附件")
    parser.add_argument("--limit", type=int, default=0, help="仅处理前 N 个目录（0=全部）")
    parser.add_argument("--dry-run", action="store_true", help="只爬索引、不下载")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("请先安装: pip install playwright && playwright install chromium", file=sys.stderr)
        return 1

    folders = iter_food_folders()
    if args.limit:
        folders = folders[: args.limit]

    print(f"清远食品抽检目录: {len(folders)} 个")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
        )

        print("爬取通告索引…")
        index = crawl_notice_index(context)
        print(f"索引条目: {len(index)}")

        if args.dry_run:
            matched = sum(1 for f in folders if _norm_title(f.name) in index)
            print(f"可匹配目录: {matched}/{len(folders)}")
            browser.close()
            return 0

        ok = miss = 0
        for i, folder in enumerate(folders, 1):
            key = _norm_title(folder.name)
            post_url = index.get(key)
            if not post_url:
                print(f"[{i}/{len(folders)}] 未找到: {folder.name[:50]}…")
                miss += 1
                continue
            n, msg = download_for_folder(context, folder, post_url)
            if msg == "ok":
                print(f"[{i}/{len(folders)}] +{n} 文件: {folder.name[:55]}…")
                ok += 1
            else:
                print(f"[{i}/{len(folders)}] {msg}: {folder.name[:55]}…")
                miss += 1
            time.sleep(0.3)

        browser.close()

    print(f"完成: 成功 {ok}, 失败/跳过 {miss}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
