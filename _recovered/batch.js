/** 批量 Excel → 本地 PDF 文件夹匹配 → ZIP 下载（纯前端） */
(function () {
  const el = id => document.getElementById(id);
  const batchFile = el("batchFile");
  const pdfFolder = el("pdfFolder");
  const btnBatchParse = el("btnBatchParse");
  const btnBatchPreview = el("btnBatchPreview");
  const btnBatchDownload = el("btnBatchDownload");
  const batchMeta = el("batchMeta");
  const batchTableWrap = el("batchTableWrap");
  const batchTableSection = el("batchTableSection");
  const batchFileName = el("batchFileName");
  const pdfFolderName = el("pdfFolderName");
  const batchDropzone = el("batchDropzone");
  const pdfFolderDropzone = el("pdfFolderDropzone");
  const btnBatchTemplate = el("btnBatchTemplate");
  const batchFeedback = el("batchFeedback");
  const batchStage = el("batchStage");

  let parsedItems = [];
  let parsedMeta = null;
  let previewResults = [];
  let excelBuffer = null;
  let excelFilename = "";
  let pdfFiles = [];

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s || "";
    return d.innerHTML;
  }

  function statusLabel(status) {
    const map = { ok: "可下载", not_found: "未找到", empty: "空行", error: "错误" };
    return map[status] || status || "—";
  }

  function statusClass(status) {
    if (status === "ok") return "batch-ok";
    if (status === "not_found") return "batch-warn";
    return "batch-fail";
  }

  function setFileName(name) {
    if (!batchFileName) return;
    batchFileName.textContent = name || "未选择文件";
    batchFileName.classList.toggle("has-file", !!name);
  }

  function setFolderName(name, count) {
    if (!pdfFolderName) return;
    if (!name) {
      pdfFolderName.textContent = "未选择";
      pdfFolderName.classList.remove("has-file");
      return;
    }
    pdfFolderName.textContent = count ? `${name}（${count} 个 PDF）` : name;
    pdfFolderName.classList.add("has-file");
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
    [btnBatchParse, btnBatchPreview, btnBatchDownload].forEach(b => {
      if (b) b.disabled = busy;
    });
  }

  function renderTable(rows) {
    if (!batchTableWrap) return;
    if (!rows.length) {
      batchTableWrap.innerHTML = "";
      showTableSection(false);
      return;
    }
    showTableSection(true);
    let html = `<table class="batch-table"><thead><tr>
      <th>行</th><th>标准号</th><th>标准名</th><th>匹配文件</th><th>状态</th>
    </tr></thead><tbody>`;
    rows.forEach(r => {
      html += `<tr>
        <td>${r.row}</td>
        <td>${escapeHtml(r.query)}</td>
        <td class="batch-name">${escapeHtml(r.std_chinesename || r.name_hint || "—")}</td>
        <td>${escapeHtml(r.pdf_name || "—")}</td>
        <td><span class="batch-status ${statusClass(r.status)}">${escapeHtml(statusLabel(r.status))}</span></td>
      </tr>`;
    });
    html += "</tbody></table>";
    batchTableWrap.innerHTML = html;
  }

  function ensurePdfFolder() {
    if (!pdfFiles.length) {
      setFeedback('<div class="alert">请先选择 PDF 所在文件夹</div>');
      return false;
    }
    return true;
  }

  async function doParse() {
    const file = batchFile?.files?.[0];
    if (!file) {
      setFeedback('<div class="alert">请先选择 Excel 或 CSV 文件</div>');
      return;
    }
    setFileName(file.name);
    setBusy(true);
    previewResults = [];
    setFeedback('<div class="loading"><div class="spinner"></div>正在解析 Excel…</div>');
    try {
      excelBuffer = await file.arrayBuffer();
      excelFilename = file.name;
      const data = window.BatchParse.parseFile(file.name, excelBuffer);
      if (!data.ok) {
        setFeedback(`<div class="alert">${escapeHtml(data.error || "解析失败")}</div>`);
        parsedItems = [];
        renderTable([]);
        return;
      }
      parsedItems = data.items || [];
      parsedMeta = data.meta || null;
      const trunc = parsedMeta?.truncated ? `（已达上限 ${parsedMeta.max_rows} 条）` : "";
      setMeta(`已识别 ${parsedItems.length} 条标准号${trunc}`);
      renderTable(parsedItems.map(it => ({ ...it, status: "—", std_chinesename: it.name_hint })));
      setFeedback('<div class="batch-hint">解析完成。请先确认已选 PDF 文件夹，再点「预览匹配」或「下载 ZIP」。</div>');
      if (btnBatchPreview) btnBatchPreview.disabled = false;
      if (btnBatchDownload) btnBatchDownload.disabled = false;
    } catch (e) {
      setFeedback(`<div class="alert">解析失败：${escapeHtml(e.message || "未知错误")}</div>`);
    } finally {
      setBusy(false);
    }
  }

  function doPreview() {
    if (!parsedItems.length) {
      setFeedback('<div class="alert">请先解析 Excel</div>');
      return;
    }
    if (!ensurePdfFolder()) return;
    setBusy(true);
    setFeedback('<div class="loading"><div class="spinner"></div>正在匹配 PDF 文件名…</div>');
    try {
      previewResults = window.BatchParse.matchItems(parsedItems, pdfFiles);
      renderTable(previewResults);
      const ok = previewResults.filter(r => r.status === "ok").length;
      setFeedback(
        `<div class="batch-hint">预览完成：共 ${previewResults.length} 条，可打包 <strong>${ok}</strong> 个 PDF，未找到 ${previewResults.length - ok} 条。</div>`
      );
    } finally {
      setBusy(false);
    }
  }

  async function doDownload() {
    if (!parsedItems.length) {
      setFeedback('<div class="alert">请先解析 Excel</div>');
      return;
    }
    if (!ensurePdfFolder()) return;
    if (typeof JSZip === "undefined") {
      setFeedback('<div class="alert">ZIP 组件未加载，请检查网络后刷新</div>');
      return;
    }
    setBusy(true);
    setFeedback(`<div class="loading"><div class="spinner"></div>正在打包 ${parsedItems.length} 条…</div>`);
    try {
      const results = previewResults.length
        ? previewResults
        : window.BatchParse.matchItems(parsedItems, pdfFiles);
      previewResults = results;
      renderTable(results);
      const zip = new JSZip();
      const folder = zip.folder("PDF");
      let ok = 0;
      const used = new Set();
      for (const r of results) {
        if (r.status !== "ok" || !r.file) continue;
        let name = r.file.name;
        let n = 1;
        while (used.has(name)) {
          const dot = r.file.name.lastIndexOf(".");
          const base = dot > 0 ? r.file.name.slice(0, dot) : r.file.name;
          const ext = dot > 0 ? r.file.name.slice(dot) : "";
          name = `${base}_${n}${ext}`;
          n++;
        }
        used.add(name);
        const buf = await r.file.arrayBuffer();
        folder.file(`${String(r.row).padStart(3, "0")}_${name}`, buf);
        ok++;
      }
      if (ok < 1) {
        setFeedback('<div class="alert">未找到任何可打包的 PDF，请检查文件夹或标准号是否正确</div>');
        return;
      }
      const lines = [
        "标准 PDF 批量下载清单（纯前端）",
        `生成时间：${new Date().toLocaleString()}`,
        `共 ${results.length} 条，成功 ${ok} 条`,
        "",
      ];
      results.forEach(r => {
        lines.push(`${r.status === "ok" ? "✓" : "✗"} 第${r.row}行 | ${r.query} | ${r.pdf_name || "—"}`);
      });
      zip.file("_下载清单.txt", lines.join("\n"));
      if (excelBuffer && excelFilename) {
        const annotated = window.BatchParse.annotateWorkbook(excelBuffer, excelFilename, results);
        if (annotated) {
          zip.file(excelFilename.replace(/\.(xlsx|xlsm)$/i, "") + "_下载结果.xlsx", annotated);
        }
      }
      const blob = await zip.generateAsync({ type: "blob", compression: "DEFLATE" });
      const stamp = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, "").slice(0, 14);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `标准PDF批量下载_${stamp}.zip`;
      a.click();
      URL.revokeObjectURL(a.href);
      setFeedback(`<div class="batch-hint">ZIP 已开始下载（${ok} 个 PDF）。未匹配项已在清单与 Excel 备注中标「否」。</div>`);
    } catch (e) {
      setFeedback(`<div class="alert">打包失败：${escapeHtml(e.message || "未知错误")}</div>`);
    } finally {
      setBusy(false);
    }
  }

  function downloadTemplate() {
    if (typeof XLSX === "undefined") {
      alert("Excel 组件未加载，请检查网络后刷新");
      return;
    }
    const buf = window.BatchParse.buildTemplateWorkbook();
    const blob = new Blob([buf], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "标准批量下载模板.xlsx";
    a.click();
    URL.revokeObjectURL(a.href);
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

  if (pdfFolder) {
    pdfFolder.addEventListener("change", () => {
      pdfFiles = [...(pdfFolder.files || [])];
      const pdfs = pdfFiles.filter(f => /\.pdf$/i.test(f.name));
      pdfFiles = pdfs;
      const path = pdfs[0]?.webkitRelativePath || "";
      const folder = path.includes("/") ? path.split("/")[0] : pdfs.length ? "已选文件夹" : "";
      setFolderName(folder, pdfs.length);
      previewResults = [];
      if (parsedItems.length) renderTable(parsedItems.map(it => ({ ...it, status: "—", std_chinesename: it.name_hint })));
    });
  }

  if (batchFile) {
    batchFile.addEventListener("change", () => {
      const f = batchFile.files?.[0];
      setFileName(f ? f.name : "");
      parsedItems = [];
      previewResults = [];
      excelBuffer = null;
      renderTable([]);
      if (btnBatchPreview) btnBatchPreview.disabled = true;
      if (btnBatchDownload) btnBatchDownload.disabled = true;
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

  if (btnBatchTemplate) btnBatchTemplate.addEventListener("click", downloadTemplate);
  if (btnBatchParse) btnBatchParse.addEventListener("click", doParse);
  if (btnBatchPreview) btnBatchPreview.addEventListener("click", doPreview);
  if (btnBatchDownload) btnBatchDownload.addEventListener("click", doDownload);

  if (batchStage) batchStage.style.display = "flex";
  setMeta("纯前端运行 · 支持 .xlsx / .csv · 单次最多 400 条");
})();
