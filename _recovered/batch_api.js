/** 批量 Excel 导入 → 检索 PDF → ZIP 下载 */
(function () {
  const el = id => document.getElementById(id);
  const batchToolbar = el("batchToolbar");
  const batchFile = el("batchFile");
  const btnBatchParse = el("btnBatchParse");
  const btnBatchPreview = el("btnBatchPreview");
  const btnBatchDownload = el("btnBatchDownload");
  const batchScanDisk = el("batchScanDisk");
  const batchMeta = el("batchMeta");
  const batchTableWrap = el("batchTableWrap");
  const results = el("results");
  const searchPanel = el("searchPanel");
  const historyWrap = el("historyWrap");
  const statsToolbar = el("statsToolbar");
  const statsCharts = el("statsCharts");

  let parsedItems = [];
  let previewMap = new Map();

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s || "";
    return d.innerHTML;
  }

  function statusLabel(status) {
    const map = {
      ok: "可下载",
      not_found: "未找到",
      no_pdf: "无 PDF",
      empty: "空行",
      error: "错误",
    };
    return map[status] || status || "—";
  }

  function statusClass(status) {
    if (status === "ok") return "batch-ok";
    if (status === "not_found" || status === "no_pdf") return "batch-warn";
    return "batch-fail";
  }

  function renderTable() {
    if (!batchTableWrap) return;
    if (!parsedItems.length) {
      batchTableWrap.innerHTML = "";
      return;
    }
    let html = `<table class="batch-table"><thead><tr>
      <th>行</th><th>查询内容</th><th>匹配标准号</th><th>标准名称</th><th>状态</th>
    </tr></thead><tbody>`;
    parsedItems.forEach(it => {
      const prev = previewMap.get(it.row);
      const st = prev?.status || "—";
      html += `<tr>
        <td>${it.row}</td>
        <td>${escapeHtml(it.query)}</td>
        <td>${escapeHtml(prev?.std_id || "—")}</td>
        <td class="batch-name">${escapeHtml(prev?.std_chinesename || "—")}</td>
        <td><span class="batch-status ${statusClass(st)}">${escapeHtml(statusLabel(st))}</span></td>
      </tr>`;
    });
    html += "</tbody></table>";
    batchTableWrap.innerHTML = html;
  }

  function setMeta(text) {
    if (batchMeta) batchMeta.textContent = text || "";
  }

  function setBusy(busy) {
    [btnBatchParse, btnBatchPreview, btnBatchDownload].forEach(b => {
      if (b) b.disabled = busy;
    });
  }

  async function doParse() {
    const file = batchFile?.files?.[0];
    if (!file) {
      results.innerHTML = '<div class="alert">请先选择 Excel 或 CSV 文件</div>';
      return;
    }
    setBusy(true);
    previewMap = new Map();
    results.innerHTML = '<div class="loading"><div class="spinner"></div>正在解析 Excel…</div>';
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await fetch("/api/batch/parse", { method: "POST", body: fd });
      const data = await res.json();
      if (!data.ok) {
        results.innerHTML = `<div class="alert">${escapeHtml(data.error || "解析失败")}</div>`;
        parsedItems = [];
        renderTable();
        return;
      }
      parsedItems = data.items || [];
      const meta = data.meta || {};
      const trunc = meta.truncated ? `（已达上限 ${meta.max_rows} 条）` : "";
      setMeta(`已识别 ${parsedItems.length} 条待下载${trunc}`);
      renderTable();
      results.innerHTML = `<div class="batch-hint">解析完成。可先「预览匹配」确认结果，再「下载 ZIP 压缩包」。勾选「扫描磁盘」可查找库外 PDF，但更慢。</div>`;
      if (btnBatchPreview) btnBatchPreview.disabled = false;
      if (btnBatchDownload) btnBatchDownload.disabled = false;
    } catch (e) {
      results.innerHTML = `<div class="alert">解析失败：${escapeHtml(e.message)}</div>`;
    } finally {
      setBusy(false);
    }
  }

  async function doPreview() {
    if (!parsedItems.length) {
      results.innerHTML = '<div class="alert">请先解析 Excel</div>';
      return;
    }
    setBusy(true);
    results.innerHTML = '<div class="loading"><div class="spinner"></div>正在匹配标准（预览）…</div>';
    try {
      const res = await fetch("/api/batch/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          items: parsedItems,
          scan_disk: batchScanDisk?.checked === true,
        }),
      });
      const data = await res.json();
      if (!data.ok) {
        results.innerHTML = `<div class="alert">${escapeHtml(data.error || "预览失败")}</div>`;
        return;
      }
      previewMap = new Map();
      (data.items || []).forEach((r, i) => {
        const row = parsedItems[i]?.row ?? i + 1;
        previewMap.set(row, r);
      });
      renderTable();
      const s = data.summary || {};
      results.innerHTML = `<div class="batch-hint">预览完成：共 ${s.total} 条，预计可下载 <strong>${s.success}</strong> 条，失败 ${s.failed} 条。</div>`;
    } catch (e) {
      results.innerHTML = `<div class="alert">预览失败：${escapeHtml(e.message)}</div>`;
    } finally {
      setBusy(false);
    }
  }

  async function doDownload() {
    if (!parsedItems.length) {
      results.innerHTML = '<div class="alert">请先解析 Excel</div>';
      return;
    }
    setBusy(true);
    results.innerHTML = '<div class="loading"><div class="spinner"></div>正在检索并打包 PDF，请稍候…</div>';
    try {
      const scan = batchScanDisk?.checked !== false;
      const res = await fetch(
        `/api/batch/download?scan_disk=${scan ? "1" : "0"}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ items: parsedItems, scan_disk: scan }),
        }
      );
      const ctype = res.headers.get("content-type") || "";
      if (!res.ok) {
        let err = "下载失败";
        if (ctype.includes("json")) {
          const data = await res.json();
          err = data.error || err;
          if (data.summary) {
            previewMap = new Map();
            (data.summary.results || []).forEach(r => previewMap.set(r.row, r));
            renderTable();
          }
        }
        results.innerHTML = `<div class="alert">${escapeHtml(err)}</div>`;
        return;
      }
      const blob = await res.blob();
      const disp = res.headers.get("content-disposition") || "";
      let name = "标准PDF批量下载.zip";
      const m = /filename\*?=(?:UTF-8'')?["']?([^"';]+)/i.exec(disp);
      if (m) name = decodeURIComponent(m[1].trim());
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      a.click();
      URL.revokeObjectURL(url);
      results.innerHTML = '<div class="batch-hint">ZIP 已开始下载。压缩包内包含 PDF 与「_批量下载清单.txt」。</div>';
    } catch (e) {
      results.innerHTML = `<div class="alert">下载失败：${escapeHtml(e.message)}</div>`;
    } finally {
      setBusy(false);
    }
  }

  function onModeEnter() {
    if (batchToolbar) batchToolbar.style.display = "block";
    if (searchPanel) searchPanel.style.display = "none";
    if (historyWrap) historyWrap.style.display = "none";
    if (statsToolbar) statsToolbar.style.display = "none";
    if (statsCharts) statsCharts.style.display = "none";
    window.StatsUI?.onModeLeave?.();
    parsedItems = [];
    previewMap = new Map();
    if (batchFile) batchFile.value = "";
    setMeta("支持 .xlsx / .csv，列名含「标准编号」或「标准名称」即可自动识别");
    renderTable();
    results.innerHTML = "";
    if (btnBatchPreview) btnBatchPreview.disabled = true;
    if (btnBatchDownload) btnBatchDownload.disabled = true;
  }

  function onModeLeave() {
    if (batchToolbar) batchToolbar.style.display = "none";
    if (searchPanel) searchPanel.style.display = "";
    if (historyWrap) historyWrap.style.display = "";
  }

  if (btnBatchParse) btnBatchParse.addEventListener("click", doParse);
  if (btnBatchPreview) btnBatchPreview.addEventListener("click", doPreview);
  if (btnBatchDownload) btnBatchDownload.addEventListener("click", doDownload);
  if (batchFile) {
    batchFile.addEventListener("change", () => {
      parsedItems = [];
      previewMap = new Map();
      renderTable();
      if (btnBatchPreview) btnBatchPreview.disabled = true;
      if (btnBatchDownload) btnBatchDownload.disabled = true;
    });
  }

  window.BatchUI = { onModeEnter, onModeLeave };
})();
