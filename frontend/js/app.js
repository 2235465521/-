/** 标准检索 / 同类产品 / 模块切换 */
(function () {
  const mainArea = document.getElementById("mainArea");
  const searchPanel = document.getElementById("searchPanel");
  const batchStage = document.getElementById("batchStage");
  const searchTools = document.getElementById("searchTools");
  const advancedPanel = document.getElementById("advancedPanel");
  const form = document.getElementById("searchForm");
  const input = document.getElementById("query");
  const results = document.getElementById("results");
  const btnSearch = document.getElementById("btnSearch");
  const historyWrap = document.getElementById("historyWrap");
  const historyChips = document.getElementById("historyChips");
  const historyMoreBtn = document.getElementById("historyMoreBtn");
  const historyDropdownPanel = document.getElementById("historyDropdownPanel");
  const historyMoreChips = document.getElementById("historyMoreChips");
  const productBanner = document.getElementById("productBanner");
  const productClusterList = document.getElementById("productClusterList");
  const pageTitle = document.getElementById("pageTitle");
  const pageSubtitle = document.getElementById("pageSubtitle");
  const headerDbStatus = document.getElementById("headerDbStatus");
  const btnSearchClear = document.getElementById("btnSearchClear");
  const searchHint = document.getElementById("searchHint");
  const serverStatusText = document.getElementById("serverStatusText");
  const sidebarFoot = document.querySelector(".sidebar-foot");
  const appShell = document.getElementById("appLayout");
  const btnSidebarCollapse = document.getElementById("btnSidebarCollapse");
  const SIDEBAR_COLLAPSED_KEY = "pdf_sidebar_collapsed_v1";

  const PAGE_COPY = {
    search: {
      title: "标准PDF下载",
      subtitle: "支持标准编号、名称检索与多维度高级筛选，一键下载 PDF。",
    },
    product: {
      title: "同类产品标准检索",
      subtitle: "输入产品名称，自动扩展同类关键词并检索相关标准。",
    },
    tuangbiao: {
      title: "团标、征求意见稿",
      subtitle: "按协会名、标准名称检索团标 PDF 文件。",
    },
    batch: {
      title: "Excel 批量下载",
      subtitle: "上传标准清单，自动匹配并打包 ZIP 下载。",
    },
  };

  const PER_PAGE = 10;
  const HISTORY_KEY = "pdf_search_history_v1";
  let currentMode = "search";
  let currentPage = 1;
  const modeQueries = {
    search: "",
    product: "",
    tuangbiao: "",
    batch: "",
  };

  const searchPageCache = new Map();
  const MAX_CACHE_ENTRIES = 100;

  function getPageCacheKey(mode, page, query, extraParams = "") {
    return `${mode}:${page}:${query}:${extraParams}`;
  }

  function setPageCache(key, data) {
    if (searchPageCache.size >= MAX_CACHE_ENTRIES) {
      const firstKey = searchPageCache.keys().next().value;
      searchPageCache.delete(firstKey);
    }
    searchPageCache.set(key, data);
  }

  function syncClearBtn() {
    if (!btnSearchClear || !input) return;
    btnSearchClear.hidden = !input.value.trim();
  }

  function clearSearchInput() {
    if (!input) return;
    input.value = "";
    modeQueries[currentMode] = "";
    if (currentMode in modeResults) {
      modeResults[currentMode] = null;
    }
    syncClearBtn();
    if (currentMode === "search" || currentMode === "tuangbiao") loadDefaultResults();
    else if (results) results.innerHTML = "";
    input.focus();
  }

  function persistModeQuery() {
    if (input) modeQueries[currentMode] = input.value || "";
  }

  function restoreModeQuery(mode) {
    if (input) input.value = modeQueries[mode] || "";
  }

  function isCatalogMode(mode) {
    return mode === "tuangbiao";
  }

  function isSearchLikeMode(mode) {
    return mode === "search" || mode === "product" || isCatalogMode(mode);
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s || "";
    return d.innerHTML;
  }

  function formatReleaseDate(raw) {
    if (!raw) return "—";
    const s = String(raw).trim();
    if (/^\d{4}-\d{2}-\d{2}/.test(s)) return s.slice(0, 10);
    const rfc = s.match(/(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})/);
    if (rfc) {
      const months = {
        Jan: "01", Feb: "02", Mar: "03", Apr: "04", May: "05", Jun: "06",
        Jul: "07", Aug: "08", Sep: "09", Oct: "10", Nov: "11", Dec: "12",
      };
      const mon = months[rfc[2]];
      if (mon) {
        return `${rfc[3]}-${mon}-${String(rfc[1]).padStart(2, "0")}`;
      }
    }
    const d = new Date(s);
    if (!Number.isNaN(d.getTime())) {
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, "0");
      const day = String(d.getDate()).padStart(2, "0");
      return `${y}-${m}-${day}`;
    }
    return s.length > 10 ? s.slice(0, 10) : s;
  }

  function fmtSize(n) {
    if (!n) return "";
    const u = ["B", "KB", "MB", "GB"];
    let v = Number(n);
    let i = 0;
    while (v >= 1024 && i < u.length - 1) {
      v /= 1024;
      i++;
    }
    return `${v.toFixed(i ? 1 : 0)} ${u[i]}`;
  }

  function getHistoryKey(mode) {
    if (mode === "tuangbiao") return "pdf_tuangbiao_history_v1";
    if (mode === "product") return "pdf_product_history_v1";
    return "pdf_search_history_v1";
  }

  function loadHistory() {
    try {
      const key = getHistoryKey(currentMode);
      return JSON.parse(localStorage.getItem(key) || "[]");
    } catch {
      return [];
    }
  }

  const VISIBLE_CHIPS_LIMIT = 5;

  function saveHistory(q) {
    const text = (q || "").trim();
    if (!text) return;
    const key = getHistoryKey(currentMode);
    let list = loadHistory().filter(x => x !== text);
    list.unshift(text);
    localStorage.setItem(key, JSON.stringify(list.slice(0, 30)));
    renderHistory();
  }

  function deleteHistory(q) {
    const text = (q || "").trim();
    if (!text) return;
    const key = getHistoryKey(currentMode);
    let list = loadHistory().filter(x => x !== text);
    localStorage.setItem(key, JSON.stringify(list));
    renderHistory();
  }

  function renderHistory() {
    if (!historyWrap || !historyChips) return;
    if (currentMode !== "search" && currentMode !== "tuangbiao" && currentMode !== "product") {
      historyWrap.classList.add("empty");
      historyWrap.hidden = true;
      if (historyDropdownPanel) historyDropdownPanel.hidden = true;
      if (historyMoreBtn) historyMoreBtn.classList.remove("open");
      return;
    }
    const list = loadHistory();
    if (!list.length) {
      historyWrap.classList.add("empty");
      historyWrap.hidden = true;
      historyChips.innerHTML = "";
      if (historyMoreChips) historyMoreChips.innerHTML = "";
      if (historyMoreBtn) historyMoreBtn.hidden = true;
      if (historyDropdownPanel) historyDropdownPanel.hidden = true;
      if (historyMoreBtn) historyMoreBtn.classList.remove("open");
      return;
    }
    historyWrap.hidden = false;
    historyWrap.classList.remove("empty");

    const mainList = list.slice(0, VISIBLE_CHIPS_LIMIT);
    const extraList = list.slice(VISIBLE_CHIPS_LIMIT);

    const renderChipHtml = (q) => `
      <div class="chip" data-q="${escapeHtml(q)}">
        <span class="chip-text" title="检索 ${escapeHtml(q)}">${escapeHtml(q)}</span>
        <button type="button" class="chip-del" data-q="${escapeHtml(q)}" title="删除此记录" aria-label="删除记录">×</button>
      </div>`;

    historyChips.innerHTML = mainList.map(renderChipHtml).join("");

    if (historyMoreChips && historyMoreBtn) {
      if (extraList.length > 0) {
        historyMoreChips.innerHTML = extraList.map(renderChipHtml).join("");
        historyMoreBtn.hidden = false;
      } else {
        historyMoreChips.innerHTML = "";
        historyMoreBtn.hidden = true;
        if (historyDropdownPanel) historyDropdownPanel.hidden = true;
        historyMoreBtn.classList.remove("open");
      }
    }

    const bindChipEvents = (container) => {
      if (!container) return;
      container.querySelectorAll(".chip").forEach(chip => {
        chip.querySelector(".chip-text")?.addEventListener("click", () => {
          if (input) input.value = chip.dataset.q || "";
          syncClearBtn();
          if (historyDropdownPanel) historyDropdownPanel.hidden = true;
          if (historyMoreBtn) historyMoreBtn.classList.remove("open");
          doSearch(1);
        });
        chip.querySelector(".chip-del")?.addEventListener("click", (e) => {
          e.stopPropagation();
          deleteHistory(chip.dataset.q || "");
        });
      });
    };

    bindChipEvents(historyChips);
    if (historyMoreChips) bindChipEvents(historyMoreChips);
  }

  if (historyMoreBtn && historyDropdownPanel) {
    historyMoreBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const isOpen = !historyDropdownPanel.hidden;
      historyDropdownPanel.hidden = isOpen;
      historyMoreBtn.classList.toggle("open", !isOpen);
    });

    document.addEventListener("click", (e) => {
      if (historyWrap && !historyWrap.contains(e.target)) {
        if (historyDropdownPanel) historyDropdownPanel.hidden = true;
        if (historyMoreBtn) historyMoreBtn.classList.remove("open");
      }
    });
  }

  const modeResults = {
    search: null,
    product: null,
    tuangbiao: null,
  };

  function setMode(mode) {
    if (mode !== currentMode) {
      persistModeQuery();
    }
    currentMode = mode;
    restoreModeQuery(mode);

    if (!mainArea) return;
    mainArea.classList.remove(
      "mode-search",
      "mode-batch",
      "mode-product",
      "mode-tuangbiao"
    );
    if (mode === "batch") mainArea.classList.add("mode-batch");
    else if (mode === "product") mainArea.classList.add("mode-product");
    else if (mode === "tuangbiao") mainArea.classList.add("mode-tuangbiao");
    else mainArea.classList.add("mode-search");

    document.querySelectorAll(".nav-group[data-mode]").forEach(g => {
      const active = g.dataset.mode === mode;
      g.classList.toggle("active-mode", active);
      if (g.dataset.mode === "product") {
        g.classList.toggle("open", active);
      } else {
        g.classList.remove("open");
      }
    });

    applyModeUi(mode);
    syncClearBtn();
  }

  function updateCatalogBanner(mode) {
    if (!productBanner) return;
    if (mode !== "product") {
      productBanner.hidden = true;
    }
  }

  function applyModeUi(mode) {
    const searchLike = isSearchLikeMode(mode);
    const btnAdvanced = document.getElementById("btnAdvancedToggle");
    if (searchPanel) searchPanel.hidden = !searchLike && mode !== "batch";
    if (searchPanel && searchLike) searchPanel.hidden = false;
    if (historyWrap) historyWrap.hidden = mode !== "search" && mode !== "tuangbiao" && mode !== "product";
    if (results) results.hidden = mode === "batch";
    if (batchStage) batchStage.hidden = mode !== "batch";
    if (searchTools) {
      const showBulk =
        mode === "search" ||
        mode === "product" ||
        mode === "tuangbiao";
      searchTools.hidden = !showBulk;
      searchTools.style.removeProperty("display");
    }
    const bulkScan = document.querySelector(".bulk-scan");
    if (bulkScan) {
      bulkScan.hidden = mode === "tuangbiao";
    }
    if (searchHint) searchHint.hidden = mode !== "search";
    if (btnAdvanced) {
      btnAdvanced.style.display = mode === "search" ? "" : "none";
    }
    if (advancedPanel) {
      if (mode !== "search") {
        advancedPanel.hidden = true;
        btnAdvanced?.classList.remove("active");
      } else if (!btnAdvanced?.classList.contains("active")) {
        advancedPanel.hidden = true;
      }
    }

    if (input) {
      const placeholders = {
        product: "输入产品名，如：牙膏、牛奶、化妆品",
        tuangbiao: "输入团标名称或协会名，如：餐饮、安徽省安全生产协会",
      };
      input.placeholder =
        placeholders[mode] || "输入标准编号或名称，回车检索";
    }
    const btnLabels = {
      product: "同类检索",
      tuangbiao: "检索团标",
    };
    if (btnSearch) btnSearch.textContent = btnLabels[mode] || "检索";

    updateCatalogBanner(mode);
    updatePageHead(mode);

    if (mode === "batch" && batchStage) batchStage.style.display = "flex";
    window.AdvancedUI?.clearSelection?.();
    renderHistory();

    // Restore results specifically for the active mode
    if (mode in modeResults) {
      if (modeResults[mode]) {
        renderItems(modeResults[mode]);
      } else if (mode === "search" || mode === "tuangbiao") {
        const q = (input?.value || "").trim();
        if (!q && mode === "search" && !window.AdvancedUI?.hasActiveFilters?.()) {
          loadDefaultResults();
        } else if (!q && mode === "tuangbiao") {
          loadDefaultResults();
        } else {
          doSearch(1);
        }
      } else {
        const hints = {
          product: "输入产品名查看同类标准",
        };
        if (results && mode !== "batch") {
          results.innerHTML = `<div class="empty-state">
            <div class="empty-icon" aria-hidden="true">✏️</div>
            <p class="empty-title">${escapeHtml(hints[mode] || "请输入关键词")}</p>
            <p class="empty-desc">在上方搜索框输入内容后按回车或点击检索</p>
          </div>`;
        }
      }
    }
  }

  function triggerRandomProductGroup() {
    if (!productClusterList) return;
    const items = Array.from(productClusterList.querySelectorAll(".cat-item"));
    if (!items.length) return;
    const randomItem = items[Math.floor(Math.random() * items.length)];
    if (randomItem) {
      if (input) {
        input.value = randomItem.dataset.kw || "";
        modeQueries.product = input.value;
      }
      doSearch(1);
    }
  }

  document.querySelectorAll("[data-mode-switch]").forEach(btn => {
    btn.addEventListener("click", () => {
      const mode = btn.dataset.modeSwitch || "search";
      if (mode === "product") {
        document
          .querySelector('.nav-group[data-mode="product"]')
          ?.classList.add("open");
        setMode(mode);
        triggerRandomProductGroup();
        return;
      }
      setMode(mode);
    });
  });

  function updatePageHead(mode) {
    const copy = PAGE_COPY[mode] || PAGE_COPY.search;
    if (pageTitle) pageTitle.textContent = copy.title;
    if (pageSubtitle) pageSubtitle.textContent = copy.subtitle;
    const pageHead = document.getElementById("pageHead");
    if (pageHead) pageHead.hidden = mode === "batch";
  }

  function statusPillClass(label) {
    if (label === "现行") return "live";
    if (label === "即将实施") return "soon";
    return "old";
  }

  function firstDownloadHref(item) {
    if (currentMode === "tuangbiao") {
      return item.has_pdf || item.has_file ? `/api/tuangbiao/${item.id}/download` : null;
    }
    const files = (item.files || []).filter(f => f.exists);
    if (!files.length) return null;
    const f = files[0];
    if (f.source === "disk") return `/api/download-std/${item.id}/${f.disk_index ?? 0}`;
    if (f.id) return `/api/download/${f.id}`;
    return null;
  }

  function renderPager(data) {
    if (data.total_pages <= 1) return "";
    const pages = [];
    const maxShow = 7;
    let start = Math.max(1, data.page - 3);
    let end = Math.min(data.total_pages, start + maxShow - 1);
    start = Math.max(1, end - maxShow + 1);
    for (let p = start; p <= end; p += 1) {
      pages.push(
        `<button type="button" class="pager-num${p === data.page ? " active" : ""}" data-page="${p}">${p}</button>`
      );
    }
    return `<div class="pager">
      <div class="pager-pages">
        <button type="button" id="pgFirst" ${data.page <= 1 ? "disabled" : ""} title="首页（最头页）" aria-label="首页">«</button>
        <button type="button" id="pgPrev" ${data.page <= 1 ? "disabled" : ""} title="上一页" aria-label="上一页">‹</button>
        ${pages.join("")}
        <button type="button" id="pgNext" ${data.page >= data.total_pages ? "disabled" : ""} title="下一页" aria-label="下一页">›</button>
        <button type="button" id="pgLast" ${data.page >= data.total_pages ? "disabled" : ""} title="尾页（最底页）" aria-label="尾页">»</button>
        <div class="pager-jump">
          <span>跳至</span>
          <input type="number" id="pgJumpInput" class="pg-jump-input" min="1" max="${data.total_pages}" value="${data.page}" />
          <span>/ ${data.total_pages} 页</span>
          <button type="button" id="pgJumpBtn" class="pg-jump-btn">跳转</button>
        </div>
      </div>
    </div>`;
  }
  function fileExtIcon(ext) {
    const e = (ext || "").toLowerCase();
    if (e === ".pdf") return "PDF";
    if (e === ".doc" || e === ".docx") return "DOC";
    return "文件";
  }

  function renderDetailHtml(item) {
    const catalogHref =
      currentMode === "tuangbiao" ? `/api/tuangbiao/${item.id}/download` : null;
    const seen = new Set();
    const files = (item.files || [])
      .filter(f => {
        const key = [
          (f.resolved_path || f.file_path || "").toLowerCase(),
          (f.file_name || "").toLowerCase(),
        ].join("|");
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .map(f => {
        const href =
          catalogHref ||
          (f.source === "disk"
            ? `/api/download-std/${item.id}/${f.disk_index ?? 0}`
            : f.id
              ? `/api/download/${f.id}`
              : "#");
        const previewHref = href && href !== "#" ? href + (href.includes("?") ? "&preview=1" : "?preview=1") : "";
        const icon = catalogHref ? fileExtIcon(f.file_ext) : "PDF";
        const meta = [
          f.file_size ? fmtSize(f.file_size) : "",
          f.source === "disk" ? "磁盘扫描" : f.source === "catalog" ? "目录索引" : "",
          !f.exists ? "磁盘未找到" : "",
        ]
          .filter(Boolean)
          .join(" · ");
        return `
          <div class="file-row">
            <div class="file-icon">${icon}</div>
            <div class="file-info ${f.exists ? "" : "missing"}">
              <div class="file-name">${escapeHtml(f.file_name || "—")}</div>
              <div class="file-meta">${escapeHtml(meta || "—")}</div>
            </div>
            <div class="file-actions">
              ${f.exists
            ? `<button type="button" class="btn-preview" data-preview-url="${previewHref}" data-filename="${escapeHtml(f.file_name || item.std_id || 'PDF 预览')}" data-download-url="${href}">
                       <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:2px;vertical-align:-2px;"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                       预览
                     </button>
                     <a class="btn-dl" href="${href}" download>下载</a>`
            : `<span class="btn-dl disabled">无文件</span>`
          }
            </div>
          </div>`;
      })
      .join("");
    const blockTitle = isCatalogMode(currentMode) ? "文件" : "PDF 文件";
    return `
      <div class="pdf-block">
        <h3>${blockTitle}</h3>
        ${files || '<div class="file-meta">暂无文件记录</div>'}
      </div>`;
  }

  function scanDiskEnabled() {
    return true;
  }

  async function loadRowDetail(id, detailRow) {
    if (!detailRow || detailRow.dataset.loaded === "1") return;
    const cell = detailRow.querySelector("td");
    if (!cell) return;
    if (isCatalogMode(currentMode)) {
      cell.innerHTML = `<div class="pdf-block"><p class="file-meta">团标文件请使用右侧下载按钮</p></div>`;
      detailRow.dataset.loaded = "1";
      return;
    }
    cell.innerHTML = '<div class="loading"><div class="spinner"></div><div class="loading-msg">正在加载 PDF 详情…</div></div>';
    const detailTimeoutId = setTimeout(() => {
      const msgEl = cell.querySelector(".loading-msg");
      if (msgEl) {
        msgEl.innerHTML = `正在加载 PDF 详情…<br><span class="loading-warn-text">响应较慢，可能由于网络延迟或系统繁忙，正在努力读取，请耐心等候...</span>`;
      }
    }, 5000);

    try {
      const scan = scanDiskEnabled();
      const res = await fetch(`/api/std/${id}?scan_disk=${scan ? "1" : "0"}`);
      const ct = res.headers.get("content-type") || "";
      if (!ct.includes("application/json")) {
        throw new Error(`详情加载失败（HTTP ${res.status}）`);
      }
      const data = await res.json();
      if (!data.ok || !data.item) {
        cell.innerHTML = `<div class="alert">${escapeHtml(data.error || "加载失败")}</div>`;
        return;
      }
      cell.innerHTML = renderDetailHtml(data.item);
      detailRow.dataset.loaded = "1";
      const row = results.querySelector(`tr.result-row[data-id="${id}"]`);
      const dl = row?.querySelector(".btn-row-dl");
      const href = firstDownloadHref(data.item);
      if (dl && href) {
        dl.classList.remove("disabled");
        dl.outerHTML = `<a class="btn-row-dl" href="${href}" download title="下载" onclick="event.stopPropagation()">↓</a>`;
      }
    } catch (e) {
      cell.innerHTML = `<div class="alert">${escapeHtml(e.message || "加载失败")}</div>`;
    } finally {
      clearTimeout(detailTimeoutId);
    }
  }

  function renderItems(data) {
    if (currentMode in modeResults) {
      modeResults[currentMode] = data;
    }
    const items = data.items || [];

    if (data.resolved && productBanner && currentMode === "product") {
      const r = data.resolved;
      const kws = (r.keywords || []).slice(0, 12).join("、");
      const groups = (r.cluster_names || []).join("、") || "—";
      productBanner.innerHTML = `<strong>同类产品扩展检索</strong>
        <span class="resolve-sub">命中产品组：${escapeHtml(groups)}</span>
        <span class="resolve-sub">扩展词：${escapeHtml(kws)}${(r.keywords || []).length > 12 ? "…" : ""}</span>`;
      productBanner.hidden = false;
    } else if (productBanner) {
      productBanner.hidden = currentMode !== "product";
    }

    if (!items.length) {
      results.innerHTML = `<div class="empty-state">
        <div class="empty-icon" aria-hidden="true">🔍</div>
        <p class="empty-title">未找到匹配结果</p>
        <p class="empty-desc">请重新输入有效检索词</p>
      </div>`;
      return;
    }

    const canBulk =
      currentMode === "search" ||
      currentMode === "product" ||
      isCatalogMode(currentMode);
    const from = data.total ? (data.page - 1) * data.per_page + 1 : 0;
    const to = Math.min(data.page * data.per_page, data.total);
    const advHint =
      currentMode === "search" && window.AdvancedUI?.filterSummary?.();
    let html = `<section class="results-card">`;
    if (advHint) {
      html += `<div class="adv-filter-banner">当前筛选：${escapeHtml(advHint)}</div>`;
    } else if (data.browse) {
      html += `<div class="adv-filter-banner browse-banner">最新标准预览（有 PDF，输入关键词可精确检索）</div>`;
    }
    html += `<div class="results-table-meta">显示 ${from} 至 ${to} 项，共 ${data.total} 项</div>`;
    html += `<div class="table-wrap"><table class="results-table"><thead><tr>`;
    if (canBulk) html += `<th class="col-check"><input type="checkbox" id="tblSelectPageHint" disabled aria-hidden="true" style="visibility:hidden" /></th>`;
    html += `<th class="col-code">标准编号</th><th class="col-name">标准名称</th><th class="col-date">发布日期</th><th class="col-status">状态</th><th class="col-action">操作</th></tr></thead><tbody>`;

    html += items
      .map(item => {
        const hasFile = item.has_pdf || item.has_file || isCatalogMode(currentMode);
        const bulkChecked = window.AdvancedUI?.isSelected?.(item.id) ? " checked" : "";
        const bulkDisabled = hasFile ? "" : " disabled";
        const statusLabel = item.ex_state_label || item.std_status || "—";
        const dlHref = firstDownloadHref(item);
        const checkCell = canBulk
          ? `<td class="col-check"><input type="checkbox" class="bulk-item-check" data-id="${item.id}" data-std-id="${escapeHtml(item.std_id || "")}"${bulkChecked}${bulkDisabled} onclick="event.stopPropagation()" /></td>`
          : "";
        return `
          <tr class="result-row" data-id="${item.id}">
            ${checkCell}
            <td class="col-code"><span class="cell-code">${escapeHtml(item.std_id || "—")}</span></td>
            <td class="col-name"><span class="cell-name">${escapeHtml(item.std_chinesename || "（无名称）")}</span></td>
            <td class="col-date">${escapeHtml(formatReleaseDate(item.release_date))}</td>
            <td class="col-status">
              <span class="status-pill ${statusPillClass(statusLabel)}">${escapeHtml(statusLabel)}</span>
              <span class="status-pill ${hasFile ? "pdf-yes" : "pdf-no"}" style="margin-left:0.25rem">${hasFile ? (isCatalogMode(currentMode) ? "有文件" : "PDF") : "无PDF"}</span>
            </td>
            <td class="col-action">
              ${dlHref
            ? `<a class="btn-row-dl" href="${dlHref}" download title="下载" onclick="event.stopPropagation()">↓</a>`
            : `<span class="btn-row-dl disabled">↓</span>`
          }
            </td>
          </tr>
          <tr class="result-detail-row" data-for="${item.id}" style="display:none">
            <td colspan="${canBulk ? 6 : 5}"><div class="detail-placeholder">展开此行加载 PDF 文件列表</div></td>
          </tr>`;
      })
      .join("");
    html += `</tbody></table></div>`;
    html += renderPager(data);
    html += `</section>`;
    results.innerHTML = html;

    results.querySelectorAll("tr.result-row").forEach(row => {
      row.addEventListener("click", e => {
        if (e.target.closest(".bulk-item-check, .btn-row-dl")) return;
        const id = row.dataset.id;
        const detail = results.querySelector(`.result-detail-row[data-for="${id}"]`);
        const open = !row.classList.contains("expanded");
        row.classList.toggle("expanded", open);
        if (detail) {
          detail.style.display = open ? "table-row" : "none";
          if (open) loadRowDetail(id, detail);
        }
      });
    });

    document.getElementById("pgFirst")?.addEventListener("click", () => doSearch(1));
    document.getElementById("pgPrev")?.addEventListener("click", () => doSearch(data.page - 1));
    document.getElementById("pgNext")?.addEventListener("click", () => doSearch(data.page + 1));
    document.getElementById("pgLast")?.addEventListener("click", () => doSearch(data.total_pages));
    results.querySelectorAll(".pager-num").forEach(btn => {
      btn.addEventListener("click", () => doSearch(Number(btn.dataset.page)));
    });

    const handleJump = () => {
      const inputEl = document.getElementById("pgJumpInput");
      if (!inputEl) return;
      let targetPage = parseInt(inputEl.value, 10);
      if (isNaN(targetPage)) return;
      targetPage = Math.max(1, Math.min(data.total_pages, targetPage));
      doSearch(targetPage);
    };

    document.getElementById("pgJumpBtn")?.addEventListener("click", handleJump);
    document.getElementById("pgJumpInput")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        handleJump();
      }
    });

    // Batch check PDFs on disk in the background (extremely responsive)
    if (!isCatalogMode(currentMode) && items.length > 0) {
      const ids = items.map(it => it.id).join(",");
      const scan = scanDiskEnabled() ? "1" : "0";
      fetch(`/api/std/batch_check?ids=${ids}&scan_disk=${scan}`)
        .then(res => res.json())
        .then(resData => {
          if (resData.ok && resData.results) {
            Object.keys(resData.results).forEach(id => {
              const hasPdf = resData.results[id];
              const tr = results.querySelector(`tr.result-row[data-id="${id}"]`);
              if (tr) {
                // Update status pill
                const pill = tr.querySelector(".col-status .status-pill:last-child");
                if (pill) {
                  pill.className = `status-pill ${hasPdf ? "pdf-yes" : "pdf-no"}`;
                  pill.textContent = hasPdf ? "PDF" : "无PDF";
                }
                // Update bulk download check box disabled state
                const chk = tr.querySelector(".bulk-item-check");
                if (chk) {
                  if (hasPdf) {
                    chk.removeAttribute("disabled");
                  } else {
                    chk.setAttribute("disabled", "true");
                    chk.checked = false;
                  }
                }
              }
            });
          }
        })
        .catch(err => console.error("Error batch checking PDFs:", err));
    }

    window.AdvancedUI?.onResultsRendered?.(data, currentMode);
  }

  async function loadDefaultResults(page = 1, isPreload = false) {
    if (currentMode !== "search" && currentMode !== "tuangbiao") return;
    if ((input?.value || "").trim()) return;
    if (currentMode === "search" && window.AdvancedUI?.hasActiveFilters?.()) return;

    const cacheKey = getPageCacheKey(currentMode, page, "", "browse=1");
    if (searchPageCache.has(cacheKey)) {
      const cachedData = searchPageCache.get(cacheKey);
      if (!isPreload) {
        renderItems(cachedData);
        if (cachedData.page < cachedData.total_pages) {
          loadDefaultResults(cachedData.page + 1, true);
        }
      }
      return;
    }

    if (!isPreload) {
      results.innerHTML =
        '<div class="loading"><div class="spinner"></div><div class="loading-msg">正在加载…</div></div>';
    }

    const defaultTimeoutId = !isPreload ? setTimeout(() => {
      const msgEl = results.querySelector(".loading-msg");
      if (msgEl) {
        msgEl.innerHTML = `正在加载…<br><span class="loading-warn-text">⚠️ 响应时间较长，系统繁忙或网络不佳，正在努力为您读取中，请稍候...</span>`;
      }
    }, 5000) : null;

    const params = new URLSearchParams();
    params.set("browse", "1");
    params.set("page", String(page || 1));
    params.set("per_page", String(PER_PAGE));
    params.set("enrich", "0");
    params.set("scan_disk", scanDiskEnabled() ? "1" : "0");
    if (currentMode === "tuangbiao") {
      params.set("source", "tuangbiao");
    }

    try {
      const res = await fetch(`/api/search?${params.toString()}`);
      const data = await res.json();
      if (!data.ok) {
        if (!isPreload) results.innerHTML = "";
        return;
      }
      setPageCache(cacheKey, data);
      if (!isPreload) {
        renderItems(data);
        if (data.page < data.total_pages) {
          loadDefaultResults(data.page + 1, true);
        }
      }
    } catch (_) {
      if (!isPreload) results.innerHTML = "";
    } finally {
      if (defaultTimeoutId) clearTimeout(defaultTimeoutId);
    }
  }

  function normalizeQuery(text) {
    return (text || "").trim().replace(/\s+/g, " ");
  }

  function isMeaningless(q) {
    if (!q) return true;
    const clean = q.replace(/[\s!"#$%&'()*+,\-./:;<=>?@[\\\]^_`{|}~，。！？；：（）［］｛｝【】《》〈〉“”‘’“”‘’、｀～……—]/g, "");
    return clean.length === 0;
  }

  async function doSearch(page, isPreload = false) {
    const q = normalizeQuery(input?.value || "");
    if (input && input.value !== q) input.value = q;
    const advActive = currentMode === "search" && window.AdvancedUI?.hasActiveFilters?.();

    if (!q && !advActive) {
      if (!isPreload && (!page || page === 1)) {
        const hints = {
          search: "请输入标准编号或名称关键词",
          tuangbiao: "请输入团标名称或协会名关键词",
          product: "请输入同类产品名称或关键词",
        };
        results.innerHTML = `<div class="empty-state">
          <div class="empty-icon" aria-hidden="true">✏️</div>
          <p class="empty-title">请输入关键词</p>
          <p class="empty-desc">${escapeHtml(hints[currentMode] || "在上方搜索框输入内容后按回车或点击检索")}</p>
        </div>`;
        if (btnSearch) btnSearch.disabled = false;
        return;
      }
      if (currentMode === "search" || currentMode === "tuangbiao") {
        loadDefaultResults(page || 1, isPreload);
        return;
      }
      return;
    }

    if (isMeaningless(q) && !advActive) {
      if (!isPreload) {
        results.innerHTML = `<div class="empty-state">
          <div class="empty-icon" aria-hidden="true">🔍</div>
          <p class="empty-title">无意义检索词</p>
          <p class="empty-desc">请重新输入有效检索词</p>
        </div>`;
        if (btnSearch) btnSearch.disabled = false;
      }
      return;
    }

    const extraKey = advActive && window.AdvancedUI?.filterQuery ? window.AdvancedUI.filterQuery() : "";
    const cacheKey = getPageCacheKey(currentMode, page || 1, q, extraKey);

    if (searchPageCache.has(cacheKey)) {
      const cachedData = searchPageCache.get(cacheKey);
      if (!isPreload) {
        currentPage = page || 1;
        if ((currentMode === "search" || currentMode === "tuangbiao" || currentMode === "product") && q) saveHistory(q);
        syncClearBtn();
        renderItems(cachedData);
        if (cachedData.page < cachedData.total_pages) {
          doSearch(cachedData.page + 1, true);
        }
      }
      return;
    }

    if (!isPreload) {
      currentPage = page || 1;
      if (btnSearch) btnSearch.disabled = true;
      results.innerHTML =
        '<div class="loading"><div class="spinner"></div><div class="loading-msg">正在检索…</div></div>';
    }

    const searchTimeoutId = !isPreload ? setTimeout(() => {
      const msgEl = results.querySelector(".loading-msg");
      if (msgEl) {
        msgEl.innerHTML = `正在检索…<br><span class="loading-warn-text">⚠️ 检索用时较长，系统繁忙或网络不佳，正在努力获取结果，请稍候...</span>`;
      }
    }, 5000) : null;

    const params = new URLSearchParams();
    params.set("q", q);
    params.set("page", String(page || 1));
    params.set("per_page", String(PER_PAGE));
    params.set("enrich", "0");
    params.set("scan_disk", scanDiskEnabled() ? "1" : "0");
    if (currentMode === "product") {
      params.set("source", "product");
    } else if (isCatalogMode(currentMode)) {
      params.set("source", currentMode);
    } else if (advActive && window.AdvancedUI?.filterQuery) {
      if (window.AdvancedUI.validateRankFilter && !window.AdvancedUI.validateRankFilter()) {
        if (!isPreload && btnSearch) btnSearch.disabled = false;
        return;
      }
      const extra = new URLSearchParams(window.AdvancedUI.filterQuery());
      extra.forEach((v, k) => params.set(k, v));
    }

    try {
      const res = await fetch(`/api/search?${params.toString()}`);
      const ct = res.headers.get("content-type") || "";
      let data;
      if (ct.includes("application/json")) {
        data = await res.json();
      } else {
        const text = await res.text();
        throw new Error(
          res.status === 0
            ? "无法连接服务器，请确认已启动 启动.bat"
            : `服务器响应异常（HTTP ${res.status}），请重启服务后重试`
        );
      }
      if (!data.ok) {
        if (!isPreload) results.innerHTML = `<div class="alert">${escapeHtml(data.error || "检索失败")}</div>`;
        return;
      }
      setPageCache(cacheKey, data);
      if (!isPreload) {
        if ((currentMode === "search" || currentMode === "tuangbiao" || currentMode === "product") && q) saveHistory(q);
        syncClearBtn();
        renderItems(data);
        if (data.page < data.total_pages) {
          doSearch(data.page + 1, true);
        }
      }
    } catch (e) {
      if (!isPreload) results.innerHTML = `<div class="alert">检索失败：${escapeHtml(e.message || "网络错误")}</div>`;
    } finally {
      if (searchTimeoutId) clearTimeout(searchTimeoutId);
      if (!isPreload && btnSearch) btnSearch.disabled = false;
    }
  }

  async function loadProductClusters() {
    if (!productClusterList) return;
    try {
      const res = await fetch("/api/product/clusters");
      const data = await res.json();
      if (!data.ok) return;
      productClusterList.innerHTML = (data.clusters || [])
        .map(
          c => `<li><button type="button" class="cat-item" data-kw="${escapeHtml((c.keywords || [])[0] || c.name)}">${escapeHtml(c.name || c.id)}</button></li>`
        )
        .join("");
      productClusterList.querySelectorAll(".cat-item").forEach(btn => {
        btn.addEventListener("click", () => {
          setMode("product");
          if (input) {
            input.value = btn.dataset.kw || "";
            modeQueries.product = input.value;
          }
          doSearch(1);
        });
      });
      if (currentMode === "product" && (!input || !input.value.trim())) {
        triggerRandomProductGroup();
      }
    } catch (_) { }
  }

  function isSidebarCollapseAllowed() {
    return window.matchMedia("(min-width: 901px)").matches;
  }

  function setSidebarCollapsed(collapsed, persist = true) {
    if (!appShell) return;
    if (collapsed && !isSidebarCollapseAllowed()) {
      appShell.classList.remove("sidebar-collapsed");
      return;
    }
    appShell.classList.toggle("sidebar-collapsed", collapsed);
    const label = collapsed ? "展开侧栏" : "收起侧栏";
    const labelEl = btnSidebarCollapse?.querySelector(".sidebar-collapse-label");
    if (labelEl) labelEl.textContent = label;
    if (btnSidebarCollapse) {
      btnSidebarCollapse.setAttribute("aria-label", label);
      btnSidebarCollapse.title = label;
    }
    if (persist) {
      localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed ? "1" : "0");
    }
    if (collapsed) {
      document.querySelector('.nav-group[data-mode="product"]')?.classList.remove("open");
    }
  }

  function initSidebarCollapse() {
    if (!appShell || !btnSidebarCollapse) return;
    const collapsed =
      isSidebarCollapseAllowed() &&
      localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1";
    setSidebarCollapsed(collapsed, false);
    btnSidebarCollapse.addEventListener("click", () => {
      setSidebarCollapsed(!appShell.classList.contains("sidebar-collapsed"));
    });
    window.addEventListener("resize", () => {
      if (!isSidebarCollapseAllowed()) {
        appShell.classList.remove("sidebar-collapsed");
        return;
      }
      if (localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1") {
        appShell.classList.add("sidebar-collapsed");
      }
    });
  }

  if (form) {
    form.addEventListener("submit", e => {
      e.preventDefault();
      doSearch(1);
    });
  }

  input?.addEventListener("input", syncClearBtn);
  btnSearchClear?.addEventListener("click", clearSearchInput);
  input?.addEventListener("keydown", e => {
    if (e.key === "Escape" && input.value) {
      e.preventDefault();
      clearSearchInput();
    }
  });

  window.addEventListener("advanced-search", () => doSearch(1));

  async function loadHealth() {
    try {
      const res = await fetch("/api/meta/health");
      const data = await res.json();
      if (!data.ok) {
        if (serverStatusText) serverStatusText.textContent = "服务异常";
        sidebarFoot?.classList.add("status-error");
        return;
      }
      if (headerDbStatus) {
        headerDbStatus.textContent = data.db_ready
          ? `数据源 ${data.db_backend || "—"} · 已就绪`
          : "数据源未就绪";
      }
      if (serverStatusText) {
        serverStatusText.textContent = data.db_ready ? "服务运行中" : "数据库未就绪";
      }
      sidebarFoot?.classList.toggle("status-error", !data.db_ready);
    } catch (_) {
      if (headerDbStatus) headerDbStatus.textContent = "连接中…";
      if (serverStatusText) serverStatusText.textContent = "连接中…";
    }
  }

  function initPdfPreviewModal() {
    const modal = document.getElementById("pdfModal");
    const iframe = document.getElementById("pdfFrame");
    const titleEl = document.getElementById("pdfModalTitle");
    const newTabBtn = document.getElementById("pdfModalNewTab");
    const downloadBtn = document.getElementById("pdfModalDownload");
    const closeBtn = document.getElementById("pdfModalClose");

    function openPreview(previewUrl, filename, downloadUrl) {
      if (!modal || !iframe) return;
      if (titleEl) titleEl.textContent = filename || "PDF 在线预览";
      if (newTabBtn) newTabBtn.href = previewUrl;
      if (downloadBtn) downloadBtn.href = downloadUrl || previewUrl.replace(/[?&]preview=1/, "");
      iframe.src = previewUrl;
      modal.removeAttribute("hidden");
      document.body.style.overflow = "hidden";
    }

    function closePreview() {
      if (!modal || !iframe) return;
      modal.setAttribute("hidden", "true");
      iframe.src = "about:blank";
      document.body.style.overflow = "";
    }

    if (closeBtn) closeBtn.addEventListener("click", closePreview);
    if (modal) {
      modal.addEventListener("click", (e) => {
        if (e.target === modal) closePreview();
      });
    }

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && modal && !modal.hasAttribute("hidden")) {
        closePreview();
      }
    });

    document.addEventListener("click", (e) => {
      const btn = e.target.closest(".btn-preview");
      if (!btn) return;
      e.preventDefault();
      e.stopPropagation();
      const previewUrl = btn.dataset.previewUrl;
      const filename = btn.dataset.filename;
      const downloadUrl = btn.dataset.downloadUrl;
      if (previewUrl) {
        openPreview(previewUrl, filename, downloadUrl);
      }
    });
  }

  renderHistory();
  initSidebarCollapse();
  initPdfPreviewModal();
  loadProductClusters();
  loadHealth();
  setMode("search");
  syncClearBtn();
  input?.focus({ preventScroll: true });

  window.AppUI = { setMode, doSearch, loadDefaultResults, getMode: () => currentMode };
})();
