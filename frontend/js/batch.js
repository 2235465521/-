/** 批量 Excel → 后端检索 PDF → ZIP 下载（含 Excel 备注回写） */
(function () {
  const el = id => document.getElementById(id);
  const batchFile = el("batchFile");
  const btnBatchParse = el("btnBatchParse");
  const btnBatchPreview = el("btnBatchPreview");
  const btnBatchDownload = el("btnBatchDownload");
  const batchScanDisk = el("batchScanDisk");
  const batchMeta = el("batchMeta");
  const batchTableWrap = el("batchTableWrap");
  const batchTableSection = el("batchTableSection");
  const batchFileName = el("batchFileName");
  const batchDropzone = el("batchDropzone");
  const btnBatchTemplate = el("btnBatchTemplate");
  const batchFeedback = el("batchFeedback");
  const batchStage = el("batchStage");
  const batchSteps = el("batchSteps");
  const btnBatchBack = el("btnBatchBack");

  const btnBatchCancelPreview = el("btnBatchCancelPreview");
  const btnSelectAllRows = el("btnSelectAllRows");
  const btnSelectNoneRows = el("btnSelectNoneRows");
  const btnSelectPdfOnlyRows = el("btnSelectPdfOnlyRows");

  // 自定义上限相关元素
  const batchMaxRowsInput = el("batchMaxRowsInput");
  const batchLimitChips = el("batchLimitChips");
  const batchCardTitle = el("batchCardTitle");
  const batchCardDesc = el("batchCardDesc");

  // 模式切换与元素
  const tabBatchExcel = el("tabBatchExcel");
  const tabBatchText = el("tabBatchText");
  const tabCardExcel = el("tabCardExcel");
  const tabCardText = el("tabCardText");
  const batchGuideExcel = el("batchGuideExcel");
  const batchGuideText = el("batchGuideText");
  const batchTextWrap = el("batchTextWrap");
  const btnFillTextExample = el("btnFillTextExample");
  const btnClearTextInput = el("btnClearTextInput");
  const batchTextInput = el("batchTextInput");

  let currentInputMode = "excel"; // "excel" | "text"
  let parsedItems = [];
  let parsedMeta = null;
  let previewMap = new Map();
  let selectedRows = new Set();
  let previewAbortController = null;
  let downloadAbortController = null;

  function getMaxRowsSetting() {
    const val = batchMaxRowsInput ? batchMaxRowsInput.value.trim() : "";
    if (val === "" || val === "0" || val.toLowerCase() === "all") {
      return 0; // 0 代表不限制
    }
    const num = parseInt(val, 10);
    return isNaN(num) || num < 0 ? 0 : num;
  }

  function syncLimitUI(limitVal) {
    const num = limitVal !== undefined && limitVal !== null ? Number(limitVal) : getMaxRowsSetting();
    const strVal = num === 0 ? "" : String(num);

    if (batchMaxRowsInput) batchMaxRowsInput.value = strVal;

    if (batchLimitChips) {
      batchLimitChips.querySelectorAll(".btn-limit-chip").forEach(btn => {
        const d = Number(btn.dataset.limit);
        if ((num === 0 && d === 0) || (num > 0 && d === num)) {
          btn.classList.add("active");
        } else {
          btn.classList.remove("active");
        }
      });
    }

    if (batchCardDesc) {
      if (currentInputMode === "excel") {
        batchCardDesc.textContent = num === 0 ? "支持 .xlsx、.xlsm、.csv，当前：全量解析（不限条数）" : `支持 .xlsx、.xlsm、.csv，当前上限：${num} 条`;
      } else {
        const text = batchTextInput ? batchTextInput.value : "";
        const lines = text.split("\n").map(l => l.trim()).filter(Boolean);
        const count = lines.length;
        batchCardDesc.innerHTML = count > 0
          ? `每行一条，已检测 <span style="font-weight:700;color:var(--accent);">${count}</span> 条待解析标准（${num === 0 ? "全量不限" : `上限 ${num} 条`}）`
          : `每行一条标准号，支持直接从网页或文档复制粘贴（${num === 0 ? "全量不限" : `上限 ${num} 条`}）`;
      }
    }
    setMeta(`后端模式 · 自动读 E 盘 · ${currentInputMode === "excel" ? "Excel表格" : "文本模式"} · ${num === 0 ? "全量不限" : `上限 ${num} 条`}`);
  }

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

  function setStep(step) {
    if (!batchSteps) return;
    batchSteps.querySelectorAll("li[data-step]").forEach(li => {
      const n = Number(li.dataset.step);
      li.classList.toggle("is-active", n === step);
      li.classList.toggle("is-done", n < step);
    });
  }

  function clearUploadedFile() {
    if (batchFile) batchFile.value = "";
    parsedItems = [];
    parsedMeta = null;
    previewMap = new Map();
    selectedRows.clear();
    renderTable();
    setStep(1);
    setFeedback("");
    if (btnBatchPreview) btnBatchPreview.disabled = true;
    if (btnBatchDownload) btnBatchDownload.disabled = true;
    setFileName("");
  }

  function switchInputMode(mode) {
    currentInputMode = mode;
    [tabBatchExcel, tabCardExcel].forEach(btn => {
      if (btn) btn.classList.toggle("is-active", mode === "excel");
    });
    [tabBatchText, tabCardText].forEach(btn => {
      if (btn) btn.classList.toggle("is-active", mode === "text");
    });

    if (batchGuideExcel) batchGuideExcel.hidden = (mode !== "excel");
    if (batchGuideText) batchGuideText.hidden = (mode !== "text");

    if (batchDropzone) batchDropzone.hidden = (mode !== "excel");
    if (batchTextWrap) batchTextWrap.hidden = (mode !== "text");

    if (batchCardTitle) {
      batchCardTitle.textContent = mode === "excel" ? "上传已填写的表格" : "粘贴标准清单文本";
    }
    if (btnBatchParse) {
      btnBatchParse.textContent = mode === "excel" ? "解析文件" : "解析文本";
    }

    const limit = getMaxRowsSetting();
    syncLimitUI(limit);
    setBusy(false);
  }

  function updateTextLineCount() {
    if (currentInputMode === "text") {
      const limit = getMaxRowsSetting();
      syncLimitUI(limit);
    }
  }

  function setFileName(name) {
    if (!batchFileName) return;
    if (name) {
      batchFileName.innerHTML = `${escapeHtml(name)} <button type="button" class="btn-clear-file" id="btnClearFile" title="删除已上传文件" onclick="event.stopPropagation(); event.preventDefault();">&times;</button>`;
      batchFileName.classList.add("has-file");
      
      const btn = el("btnClearFile");
      if (btn) {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          e.preventDefault();
          clearUploadedFile();
        });
      }
    } else {
      batchFileName.textContent = "未选择文件";
      batchFileName.classList.remove("has-file");
    }
  }

  function showTableSection(show) {
    if (batchTableSection) batchTableSection.hidden = !show;
    if (show) batchStage?.classList.add("has-table");
    else batchStage?.classList.remove("has-table");
  }

  function setFeedback(html) {
    if (!batchFeedback) return;
    if (html) {
      batchFeedback.innerHTML = html;
      batchFeedback.hidden = false;
      batchStage?.classList.add("has-feedback");
    } else {
      batchFeedback.innerHTML = "";
      batchFeedback.hidden = true;
      batchStage?.classList.remove("has-feedback");
    }
  }

  function setMeta(text) {
    if (batchMeta) batchMeta.textContent = text || "";
  }

  function setBusy(busy) {
    if (btnBatchParse) btnBatchParse.disabled = busy;
    if (btnBatchPreview) btnBatchPreview.disabled = busy || !parsedItems.length;
    if (btnBatchDownload) btnBatchDownload.disabled = busy || !parsedItems.length;

    const cancelText = busy && previewAbortController ? "取消预览" : (busy && downloadAbortController ? "取消下载" : "");
    const showCancel = Boolean(cancelText);

    if (btnBatchCancelPreview) {
      if (showCancel) {
        btnBatchCancelPreview.textContent = cancelText;
        btnBatchCancelPreview.style.display = "inline-block";
      } else {
        btnBatchCancelPreview.style.display = "none";
      }
    }
  }

  function updateDownloadCounters() {
    const cntDlAll = el("cntDlAll");
    const cntDlPdf = el("cntDlPdf");
    const cntDlSelected = el("cntDlSelected");
    if (cntDlAll) cntDlAll.textContent = parsedItems.length;
    let pdfCount = 0;
    parsedItems.forEach(it => {
      const prev = previewMap.get(it.row);
      if (prev && prev.status === "ok") pdfCount++;
    });
    if (cntDlPdf) cntDlPdf.textContent = pdfCount;
    if (cntDlSelected) cntDlSelected.textContent = selectedRows.size;
  }

  function renderTable() {
    if (!batchTableWrap) return;
    if (!parsedItems.length || previewMap.size === 0) {
      batchTableWrap.innerHTML = "";
      showTableSection(false);
      return;
    }
    showTableSection(true);
    let html = `<table class="batch-table"><thead><tr>
      <th style="width:40px;text-align:center;"><input type="checkbox" id="chkBatchSelectAll" checked title="全选 / 全不选"></th>
      <th>行</th><th>标准号</th><th>标准名</th><th>PDF</th><th>状态</th>
    </tr></thead><tbody>`;
    parsedItems.forEach(it => {
      const prev = previewMap.get(it.row);
      const st = prev?.status || "—";
      const checked = selectedRows.has(it.row) ? "checked" : "";
      html += `<tr>
        <td style="text-align:center;"><input type="checkbox" class="batch-row-chk" data-row="${it.row}" ${checked}></td>
        <td>${it.row}</td>
        <td>${escapeHtml(it.query)}</td>
        <td class="batch-name">${escapeHtml(prev?.std_chinesename || it.name_hint || "—")}</td>
        <td>${escapeHtml(prev?.file_name || prev?.pdf_name || "—")}</td>
        <td><span class="batch-status ${statusClass(st)}">${escapeHtml(statusLabel(st))}</span></td>
      </tr>`;
    });
    html += "</tbody></table>";
    batchTableWrap.innerHTML = html;

    const chkAll = el("chkBatchSelectAll");
    if (chkAll) {
      const allSelected = parsedItems.length > 0 && parsedItems.every(it => selectedRows.has(it.row));
      chkAll.checked = allSelected;
      chkAll.addEventListener("change", (e) => {
        const isChecked = e.target.checked;
        parsedItems.forEach(it => {
          if (isChecked) selectedRows.add(it.row);
          else selectedRows.delete(it.row);
        });
        document.querySelectorAll(".batch-row-chk").forEach(chk => {
          chk.checked = isChecked;
        });
        updateDownloadCounters();
      });
    }

    document.querySelectorAll(".batch-row-chk").forEach(chk => {
      chk.addEventListener("change", (e) => {
        const row = Number(e.target.dataset.row);
        if (e.target.checked) {
          selectedRows.add(row);
        } else {
          selectedRows.delete(row);
        }
        if (chkAll) {
          chkAll.checked = parsedItems.every(it => selectedRows.has(it.row));
        }
        updateDownloadCounters();
      });
    });

    updateDownloadCounters();
  }

  async function doParse() {
    const file = batchFile?.files?.[0];
    if (!file) {
      setFeedback('<div class="alert">请先选择 Excel 或 CSV 文件</div>');
      return;
    }
    setFileName(file.name);
    setBusy(true);
    previewMap = new Map();
    selectedRows.clear();
    setFeedback('<div class="loading"><div class="spinner"></div><div class="loading-msg">正在解析 Excel…</div></div>');
    
    const parseTimeoutId = setTimeout(() => {
      const msgEl = batchFeedback?.querySelector(".loading-msg");
      if (msgEl) {
        msgEl.innerHTML = `正在解析 Excel…<br><span class="loading-warn-text">⚠️ 响应较慢，可能由于文件较多或系统繁忙，请耐心等候...</span>`;
      }
    }, 5000);

    const maxRows = getMaxRowsSetting();
    const fd = new FormData();
    fd.append("file", file);
    if (maxRows > 0) {
      fd.append("max_rows", String(maxRows));
    } else {
      fd.append("max_rows", "0");
    }

    try {
      const res = await fetch("/api/batch/parse", { method: "POST", body: fd });
      const data = await res.json();
      if (!data.ok) {
        setFeedback(`<div class="alert">${escapeHtml(data.error || "解析失败")}</div>`);
        parsedItems = [];
        parsedMeta = null;
        renderTable();
        return;
      }
      parsedItems = data.items || [];
      parsedMeta = data.meta || null;
      selectedRows = new Set(parsedItems.map(it => it.row));
      
      const trunc = parsedMeta?.truncated ? `（已达当前上限 ${parsedMeta.max_rows} 条，可在上方调整上限）` : "";
      setMeta(`已识别 ${parsedItems.length} 条标准号${trunc}`);
      renderTable();
      setStep(2);
      setFeedback(
        `<div class="batch-hint">✅ 文件解析成功，共识别出 <strong>${parsedItems.length}</strong> 条数据${trunc}。<br/>👉 请点击上方的「<strong>预览匹配</strong>」按钮查看检索匹配结果，或直接点击「<strong>下载 ZIP</strong>」。</div>`
      );
      if (btnBatchPreview) btnBatchPreview.disabled = false;
      if (btnBatchDownload) btnBatchDownload.disabled = false;
    } catch (e) {
      setFeedback(`<div class="alert">解析失败：${escapeHtml(e.message || "未知错误")}</div>`);
    } finally {
      clearTimeout(parseTimeoutId);
      setBusy(false);
    }
  }

  async function doParseText() {
    const text = batchTextInput ? batchTextInput.value.trim() : "";
    if (!text) {
      setFeedback('<div class="alert">请先输入或粘贴待下载的标准文本</div>');
      return;
    }
    previewMap = new Map();
    selectedRows.clear();
    setBusy(true);
    setFeedback('<div class="loading"><div class="spinner"></div><div class="loading-msg">正在解析标准文本…</div></div>');

    const maxRows = getMaxRowsSetting();
    try {
      const res = await fetch("/api/batch/parse_text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: text,
          max_rows: maxRows,
        }),
      });
      const data = await res.json();
      if (!data.ok) {
        setFeedback(`<div class="alert">${escapeHtml(data.error || "解析文本失败")}</div>`);
        parsedItems = [];
        parsedMeta = null;
        renderTable();
        return;
      }
      parsedItems = data.items || [];
      parsedMeta = data.meta || null;
      selectedRows = new Set(parsedItems.map(it => it.row));

      const trunc = parsedMeta?.truncated ? `（已达当前上限 ${parsedMeta.max_rows} 条，可在上方调整上限）` : "";
      setMeta(`后端模式 · 自动读 E 盘 · 文本模式已识别 ${parsedItems.length} 条标准号${trunc}`);
      renderTable();
      setStep(2);
      setFeedback(
        `<div class="batch-hint">✅ 文本解析成功，共识别出 <strong>${parsedItems.length}</strong> 条标准${trunc}。<br/>👉 请点击「<strong>预览匹配</strong>」查看检索匹配结果，或直接点击「<strong>下载 ZIP</strong>」。</div>`
      );
      if (btnBatchPreview) btnBatchPreview.disabled = false;
      if (btnBatchDownload) btnBatchDownload.disabled = false;
    } catch (e) {
      setFeedback(`<div class="alert">解析失败：${escapeHtml(e.message || "未知错误")}</div>`);
    } finally {
      setBusy(false);
    }
  }

  async function doPreview() {
    if (!parsedItems.length) {
      setFeedback(`<div class="alert">请先解析${currentInputMode === "text" ? "文本" : "Excel"}</div>`);
      return;
    }
    if (previewMap.size > 0) {
      showTableSection(true);
      renderTable();
      setStep(3);
      const total = parsedItems.length;
      let success = 0;
      previewMap.forEach(v => {
        if (v.status === "ok") success++;
      });
      const failed = total - success;
      setFeedback(
        `<div class="batch-hint">预览完成：共 ${total} 条，预计可下载 <strong>${success}</strong> 个 PDF，失败 ${failed} 条。</div>`
      );
      return;
    }
    previewAbortController = new AbortController();
    setBusy(true);
    setFeedback('<div class="loading"><div class="spinner"></div><div class="loading-msg">正在匹配标准（预览）…</div></div>');
    
    const previewTimeoutId = setTimeout(() => {
      const msgEl = batchFeedback?.querySelector(".loading-msg");
      if (msgEl) {
        msgEl.innerHTML = `正在匹配标准（预览）…<br><span class="loading-warn-text">⚠️ 响应较慢，可能由于文件过大或系统繁忙，请耐心等候...</span>`;
      }
    }, 5000);

    const maxRows = getMaxRowsSetting();
    try {
      const res = await fetch("/api/batch/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: previewAbortController.signal,
        body: JSON.stringify({
          items: parsedItems,
          max_rows: maxRows,
          scan_disk: true,
        }),
      });
      const data = await res.json();
      if (!data.ok) {
        setFeedback(`<div class="alert">${escapeHtml(data.error || "预览失败")}</div>`);
        return;
      }
      previewMap = new Map();
      (data.items || []).forEach((r, i) => {
        const row = parsedItems[i]?.row ?? r.row ?? i + 1;
        previewMap.set(row, r);
      });
      showTableSection(true);
      renderTable();
      setStep(3);
      const s = data.summary || {};
      const failedCount = s.failed !== undefined ? s.failed : (s.total - (s.success || 0));
      setFeedback(
        `<div class="batch-hint">预览完成：共 ${s.total} 条，预计可下载 <strong>${s.success}</strong> 个 PDF，失败 ${failedCount} 条。</div>`
      );
    } catch (e) {
      if (e.name === "AbortError") {
        setFeedback('<div class="batch-hint">已取消匹配预览。已解析项依然保留，可重新发起或直接打包下载。</div>');
      } else {
        setFeedback(`<div class="alert">预览失败：${escapeHtml(e.message || "未知错误")}</div>`);
      }
    } finally {
      previewAbortController = null;
      clearTimeout(previewTimeoutId);
      setBusy(false);
    }
  }

  async function doDownload() {
    if (!parsedItems.length) {
      setFeedback(`<div class="alert">请先解析${currentInputMode === "text" ? "文本" : "Excel"}</div>`);
      return;
    }
    const file = batchFile?.files?.[0];
    if (currentInputMode === "excel" && !file) {
      setFeedback('<div class="alert">请重新选择 Excel 文件后再下载</div>');
      return;
    }

    const scope = document.querySelector('input[name="batchDlScope"]:checked')?.value || "all";
    let downloadItems = parsedItems;
    let onlyPdf = false;

    if (scope === "only_pdf") {
      onlyPdf = true;
      if (previewMap.size > 0) {
        downloadItems = parsedItems.filter(it => previewMap.get(it.row)?.status === "ok");
      }
      if (downloadItems.length === 0) {
        setFeedback('<div class="alert">未检索到任何包含有效 PDF 的标准，无法打包下载</div>');
        return;
      }
    } else if (scope === "selected") {
      downloadItems = parsedItems.filter(it => selectedRows.has(it.row));
      if (downloadItems.length === 0) {
        setFeedback('<div class="alert">请先在预览表格中勾选要下载的行</div>');
        return;
      }
    }

    // 复用预览匹配结果：如果已执行过预览，将有效文件的路径与状态随请求一并发送，实现后端 0 毫秒跳过重复检索
    const enrichedItems = downloadItems.map(it => {
      const prev = previewMap.get(it.row);
      if (prev && prev.status === "ok") {
        return {
          ...it,
          pdf_path: prev.pdf_path,
          zip_name: prev.zip_name,
          std_id: prev.std_id || it.query,
          std_chinesename: prev.std_chinesename || it.name_hint || "",
          file_name: prev.file_name,
          status: "ok",
        };
      }
      return it;
    });

    downloadAbortController = new AbortController();
    setBusy(true);
    setFeedback('<div class="loading"><div class="spinner"></div><div class="loading-msg">正在快速组装 ZIP 包，准备传输…</div></div>');

    try {
      const scan = true;
      const fd = new FormData();
      if (currentInputMode === "excel" && file) {
        fd.append("file", file);
      }
      fd.append("items", JSON.stringify(enrichedItems));
      fd.append("only_pdf", onlyPdf ? "1" : "0");
      const maxRows = getMaxRowsSetting();
      if (maxRows > 0) {
        fd.append("max_rows", String(maxRows));
      } else {
        fd.append("max_rows", "0");
      }

      const res = await fetch(`/api/batch/download?scan_disk=${scan ? "1" : "0"}&only_pdf=${onlyPdf ? "1" : "0"}`, {
        method: "POST",
        body: fd,
        signal: downloadAbortController.signal,
      });
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
        setFeedback(`<div class="alert">${escapeHtml(err)}</div>`);
        return;
      }

      // 流式读取分块并实时计算传输字节与进度
      const contentLength = res.headers.get("content-length");
      const totalBytes = contentLength ? parseInt(contentLength, 10) : 0;
      let loadedBytes = 0;
      const reader = res.body ? res.body.getReader() : null;
      let blob;

      if (reader) {
        const chunks = [];
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          chunks.push(value);
          loadedBytes += value.length;

          const mb = (loadedBytes / 1048576).toFixed(1);
          if (totalBytes > 0) {
            const totalMb = (totalBytes / 1048576).toFixed(1);
            const percent = Math.min(100, Math.round((loadedBytes / totalBytes) * 100));
            setFeedback(
              `<div class="loading"><div class="spinner"></div><div class="loading-msg">正在传输 ZIP 文件…<br/><strong>${mb} MB / ${totalMb} MB (${percent}%)</strong>，请勿关闭页面</div></div>`
            );
          } else {
            setFeedback(
              `<div class="loading"><div class="spinner"></div><div class="loading-msg">正在传输 ZIP 文件…<br/>已接收 <strong>${mb} MB</strong>，持续传输中…</div></div>`
            );
          }
        }
        blob = new Blob(chunks, { type: "application/zip" });
      } else {
        blob = await res.blob();
      }

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
      setFeedback(
        '<div class="batch-hint">✅ ZIP 已生成并开始下载。内含 PDF、带「否」备注的 Excel 及下载清单。<br/>⚠️ <strong>提示：</strong>若下载被浏览器拦截，请在浏览器右上角下载列表或地址栏右侧选择<strong>「保留」</strong>或<strong>「允许下载」</strong>。</div>'
      );
      setStep(3);
    } catch (e) {
      if (e.name === "AbortError") {
        setFeedback('<div class="batch-hint">已取消打包下载。</div>');
      } else {
        setFeedback(`<div class="alert">下载失败：${escapeHtml(e.message || "未知错误")}</div>`);
      }
    } finally {
      downloadAbortController = null;
      clearTimeout(downloadTimeoutId);
      setBusy(false);
    }
  }

  function bindDropzone(zone, input, onFiles) {
    if (!zone || !input) return;
    ["dragenter", "dragover"].forEach(ev => {
      zone.addEventListener(ev, e => {
        e.preventDefault();
        zone.classList.add("is-dragover");
      });
    });
    ["dragleave", "drop"].forEach(ev => {
      zone.addEventListener(ev, e => {
        e.preventDefault();
        zone.classList.remove("is-dragover");
      });
    });
    zone.addEventListener("drop", e => {
      const files = e.dataTransfer?.files;
      if (!files?.length) return;
      onFiles(files);
    });
  }

  if (batchFile) {
    batchFile.addEventListener("change", () => {
      const f = batchFile.files?.[0];
      setFileName(f ? f.name : "");
      parsedItems = [];
      parsedMeta = null;
      previewMap = new Map();
      selectedRows.clear();
      renderTable();
      setStep(1);
      if (btnBatchPreview) btnBatchPreview.disabled = true;
      if (btnBatchDownload) btnBatchDownload.disabled = true;
    });
  }

  if (btnBatchBack) {
    btnBatchBack.addEventListener("click", () => {
      showTableSection(false);
      setStep(parsedItems.length ? 2 : 1);
    });
  }

  bindDropzone(batchDropzone, batchFile, files => {
    const file = files[0];
    if (!file) return;
    const dt = new DataTransfer();
    dt.items.add(file);
    batchFile.files = dt.files;
    batchFile.dispatchEvent(new Event("change"));
  });

  if (btnBatchTemplate) {
    btnBatchTemplate.addEventListener("click", e => {
      e.preventDefault();
      setStep(1);
      window.location.href = "/api/batch/template";
    });
  }

  if (btnBatchCancelPreview) {
    btnBatchCancelPreview.addEventListener("click", () => {
      if (previewAbortController) {
        previewAbortController.abort();
      }
      if (downloadAbortController) {
        downloadAbortController.abort();
      }
    });
  }

  if (btnSelectAllRows) {
    btnSelectAllRows.addEventListener("click", () => {
      parsedItems.forEach(it => selectedRows.add(it.row));
      renderTable();
    });
  }

  if (btnSelectNoneRows) {
    btnSelectNoneRows.addEventListener("click", () => {
      selectedRows.clear();
      renderTable();
    });
  }

  if (btnSelectPdfOnlyRows) {
    btnSelectPdfOnlyRows.addEventListener("click", () => {
      selectedRows.clear();
      parsedItems.forEach(it => {
        const prev = previewMap.get(it.row);
        if (prev && prev.status === "ok") {
          selectedRows.add(it.row);
        }
      });
      renderTable();
      const radioSelected = document.querySelector('input[name="batchDlScope"][value="selected"]');
      if (radioSelected) radioSelected.checked = true;
    });
  }

  // Radio button change listener to render updates
  document.querySelectorAll('input[name="batchDlScope"]').forEach(radio => {
    radio.addEventListener("change", () => {
      updateDownloadCounters();
    });
  });

  // 上限配置快捷按钮绑定与输入框监听
  if (batchLimitChips) {
    batchLimitChips.querySelectorAll(".btn-limit-chip").forEach(btn => {
      btn.addEventListener("click", () => {
        const limit = Number(btn.dataset.limit || 0);
        try {
          localStorage.setItem("batch_max_rows", String(limit));
        } catch (e) {}
        syncLimitUI(limit);
        if (batchFile?.files?.[0]) {
          setFeedback('<div class="batch-hint">已更新解析上限设置，请点击「<strong>解析文件</strong>」以应用新上限。</div>');
        }
      });
    });
  }

  if (batchMaxRowsInput) {
    batchMaxRowsInput.addEventListener("input", () => {
      const val = getMaxRowsSetting();
      try {
        localStorage.setItem("batch_max_rows", String(val));
      } catch (e) {}
      syncLimitUI(val);
      if (batchFile?.files?.[0]) {
        setFeedback('<div class="batch-hint">已更新解析上限设置，请点击「<strong>解析文件</strong>」以应用新上限。</div>');
      }
    });
  }

  // 读取本地存储的历史上限偏好（默认 2000）
  let savedLimit = 2000;
  try {
    const raw = localStorage.getItem("batch_max_rows");
    if (raw !== null && raw !== "") {
      savedLimit = Number(raw);
    }
  } catch (e) {}
  syncLimitUI(savedLimit);

  if (btnBatchParse) {
    btnBatchParse.addEventListener("click", () => {
      if (currentInputMode === "text") {
        doParseText();
      } else {
        doParse();
      }
    });
  }
  if (btnBatchPreview) btnBatchPreview.addEventListener("click", doPreview);
  if (btnBatchDownload) btnBatchDownload.addEventListener("click", doDownload);

  // 模式切换监听（顶部 Tabs 与 卡片内 Sub-tabs 联动）
  [tabBatchExcel, tabCardExcel].forEach(btn => {
    if (btn) btn.addEventListener("click", () => switchInputMode("excel"));
  });
  [tabBatchText, tabCardText].forEach(btn => {
    if (btn) btn.addEventListener("click", () => switchInputMode("text"));
  });

  // 文本模式操作监听
  if (batchTextInput) {
    batchTextInput.addEventListener("input", updateTextLineCount);
  }

  if (btnFillTextExample) {
    btnFillTextExample.addEventListener("click", () => {
      if (batchTextInput) {
        batchTextInput.value = [
          "GB/T 19001-2016 质量管理体系 要求",
          "GB 50016-2014 建筑设计防火规范",
          "GB/T 1002-2024 家用和类似用途单相插头插座",
          "GB 5749-2022 生活饮用水卫生标准",
          "DL/T 5161.1-2018 电气装置安装工程质量检验及评定规程"
        ].join("\n");
        updateTextLineCount();
        setFeedback('<div class="batch-hint">已填入示例标准清单，可点击「<strong>解析文本</strong>」体验解析。</div>');
      }
    });
  }

  if (btnClearTextInput) {
    btnClearTextInput.addEventListener("click", () => {
      if (batchTextInput) {
        batchTextInput.value = "";
        updateTextLineCount();
      }
      if (currentInputMode === "text") {
        clearUploadedFile();
      }
    });
  }

  setStep(1);

  fetch("/api/meta/health")
    .then(r => r.json())
    .then(info => {
      if (!info.db_ready) {
        setFeedback(
          '<div class="alert">标准库未就绪。请先运行 <code>python scripts/build_index.py</code> 构建索引；或勾选「扫描磁盘」仅按文件名查找 PDF。</div>'
        );
      } else if (!info.pdf_root_exists) {
        setFeedback(
          `<div class="alert">PDF 根目录不存在（${escapeHtml(info.pdf_root)}）。请检查 paths.py 或 .env 中的 PDF_ROOT。</div>`
        );
      }
    })
    .catch(() => {});
})();
