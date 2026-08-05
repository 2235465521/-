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

  // 新增控制元素
  const btnBatchCancelPreview = el("btnBatchCancelPreview");
  const btnSelectAllRows = el("btnSelectAllRows");
  const btnSelectNoneRows = el("btnSelectNoneRows");
  const btnSelectPdfOnlyRows = el("btnSelectPdfOnlyRows");

  let parsedItems = [];
  let parsedMeta = null;
  let previewMap = new Map();
  let selectedRows = new Set();
  let previewAbortController = null;
  let downloadAbortController = null;

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s || "";
    return d.innerHTML;
  }

  // 修改此处的 statusLabel 函数，将 not_found / no_pdf 显示得更精确
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

  // 清除已上传的文件与状态
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

  // 显示当前操作文件的名称
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
    if (btnBatchCancelPreview) {
      if (busy && previewAbortController) {
        btnBatchCancelPreview.textContent = "取消预览";
        btnBatchCancelPreview.style.display = "inline-block";
      } else if (busy && downloadAbortController) {
        btnBatchCancelPreview.textContent = "取消下载";
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

    const fd = new FormData();
    fd.append("file", file);
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
      
      const trunc = parsedMeta?.truncated ? `（已达上限 ${parsedMeta.max_rows} 条）` : "";
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

  async function doPreview() {
    if (!parsedItems.length) {
      setFeedback('<div class="alert">请先解析 Excel</div>');
      return;
    }
    // 如果已经有预览缓存，则直接展示结果并还原复选状态，避免重新请求和重新加载
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

    try {
      const res = await fetch("/api/batch/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: previewAbortController.signal,
        body: JSON.stringify({
          items: parsedItems,
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
      renderTable();
      setStep(3);
      const s = data.summary || {};
      setFeedback(
        `<div class="batch-hint">预览完成：共 ${s.total} 条，预计可下载 <strong>${s.success}</strong> 个 PDF，失败 ${s.failed} 条。</div>`
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
      setFeedback('<div class="alert">请先解析 Excel</div>');
      return;
    }
    const file = batchFile?.files?.[0];
    if (!file) {
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

    downloadAbortController = new AbortController();
    setBusy(true);
    setFeedback('<div class="loading"><div class="spinner"></div><div class="loading-msg">正在匹配标准并打包 ZIP，请稍候…</div></div>');
    
    const downloadTimeoutId = setTimeout(() => {
      const msgEl = batchFeedback?.querySelector(".loading-msg");
      if (msgEl) {
        msgEl.innerHTML = `正在匹配标准并打包 ZIP，请稍候…<br><span class="loading-warn-text">⚠️ 正在匹配并打包中，如果文件过大或系统繁忙请耐心等候...</span>`;
      }
    }, 5000);

    try {
      const scan = true;
      const fd = new FormData();
      fd.append("file", file);
      fd.append("items", JSON.stringify(downloadItems));
      fd.append("only_pdf", onlyPdf ? "1" : "0");
      
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
      setFeedback(
        '<div class="batch-hint">ZIP 已开始下载。内含 PDF、带「否」备注的 Excel 及下载清单。<br/>⚠️ <strong>重要提示：</strong>若下载被浏览器拦截，请在浏览器右上角下载列表或地址栏右侧选择<strong>「保留」</strong>或<strong>「允许下载」</strong>。</div>'
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

  if (btnBatchParse) btnBatchParse.addEventListener("click", doParse);
  if (btnBatchPreview) btnBatchPreview.addEventListener("click", doPreview);
  if (btnBatchDownload) btnBatchDownload.addEventListener("click", doDownload);

  setMeta("后端模式 · 自动读 E 盘 · 支持 .xlsx / .csv · 单次最多 400 条");
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
