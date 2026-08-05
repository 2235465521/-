/** 标准检索主界面（批量下载由右下角浮窗打开） */
(function () {
  const mainArea = document.getElementById("mainArea");
  const searchPanel = document.getElementById("searchPanel");
  const searchTools = document.getElementById("searchTools");
  const advancedPanel = document.getElementById("advancedPanel");
  const form = document.getElementById("searchForm");
  const input = document.getElementById("query");
  const results = document.getElementById("results");
  const btnSearch = document.getElementById("btnSearch");
  const pageTitle = document.getElementById("pageTitle");
  const pageSubtitle = document.getElementById("pageSubtitle");
  const headerDbStatus = document.getElementById("headerDbStatus");

  const PAGE_COPY = {
    search: {
      title: "标准检索",
      subtitle: "支持标准编号、名称检索与多维度高级筛选，一键下载 PDF。",
    },
  };

  const PER_PAGE = 10;
  let searchController = null;
  let currentMode = "search";
  let currentPage = 1;
  const modeQueries = {
    search: "",
  };

  function persistModeQuery() {
    if (input) modeQueries[currentMode] = input.value || "";
  }

  function restoreModeQuery(mode) {
    if (input) input.value = modeQueries[mode] || "";
  }

  function isCatalogMode(mode) {
    return false;
  }

  function isSearchLikeMode(mode) {
    return mode === "search" || isCatalogMode(mode);
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

  function setMode(_mode) {
    currentMode = "search";
    if (!mainArea) return;
    mainArea.classList.remove("mode-batch", "mode-product");
    mainArea.classList.add("mode-search");
    applyModeUi("search");
    restoreModeQuery("search");
  }

  function applyModeUi(mode) {
    const btnAdvanced = document.getElementById("btnAdvancedToggle");
    if (searchPanel) searchPanel.hidden = false;
    if (results) results.hidden = false;
    if (searchTools) {
      searchTools.hidden = false;
      searchTools.style.removeProperty("display");
      const bulkBar = searchTools.querySelector(".bulk-bar");
      if (bulkBar) bulkBar.hidden = false;
    }
    window.WorkflowUI?.updateWorkflowUi?.();
    if (btnAdvanced) btnAdvanced.style.display = "";
    if (window.AiSearchUI?.setVisible) window.AiSearchUI.setVisible(true);
    else {
      const aiPanel = document.getElementById("aiSearchPanel");
      if (aiPanel) aiPanel.hidden = false;
    }
    if (input) {
      input.placeholder = "标准编号或名称关键词，如 GB/T 1002-2024、煤矿";
    }
    if (btnSearch && !btnSearch.classList.contains("is-cancel")) {
      btnSearch.textContent = "检索";
    }
    updatePageHead(mode);
  }

  function updatePageHead(mode) {
    const copy = PAGE_COPY[mode] || PAGE_COPY.search;
    if (pageTitle) pageTitle.textContent = copy.title;
    if (pageSubtitle) pageSubtitle.textContent = copy.subtitle;
    const pageHead = document.getElementById("pageHead");
    if (pageHead) pageHead.hidden = false;
  }

  function statusPillClass(label) {
    if (label === "现行") return "live";
    if (label === "即将实施") return "soon";
    return "old";
  }

  function firstDownloadHref(item) {
    const files = (item.files || []).filter(f => f.exists);
    if (!files.length) return null;
    const f = files[0];
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
    const from = data.total ? (data.page - 1) * data.per_page + 1 : 0;
    const to = Math.min(data.page * data.per_page, data.total);
    return `<div class="pager">
      <span class="pager-info">显示 ${from} 至 ${to} 项，共 ${data.total} 项</span>
      <div class="pager-pages">
        <button type="button" id="pgPrev" ${data.page <= 1 ? "disabled" : ""} aria-label="上一页">‹</button>
        ${pages.join("")}
        <button type="button" id="pgNext" ${data.page >= data.total_pages ? "disabled" : ""} aria-label="下一页">›</button>
      </div>
    </div>`;
  }
  function fileExtIcon(ext) {
    const e = (ext || "").toLowerCase();
    if (e === ".pdf") return "PDF";
    if (e === ".doc" || e === ".docx") return "DOC";
    return "文件";
  }

  function fileStdIdentityKey(filename) {
    const stem = (filename || "").replace(/\.pdf$/i, "");
    let token = stem
      .split(/_[FTZX]_/i)[0]
      .split(/[\u4e00-\u9fff]/)[0]
      .replace(/\s+/g, "")
      .replace(/[\/_]/g, "")
      .replace(/[—－]/g, "-")
      .toUpperCase()
      .replace(/[.\-\s]+$/g, "");
    let m =
      token.match(/^([A-Z]{1,6})([TZX])([\d]+(?:\.\d+)*)(?:-(\d{2,4}))?$/i) ||
      token.match(/^([A-Z]{1,6})([\d]+(?:\.\d+)*)(?:-(\d{2,4}))?$/i);
    if (!m) return null;
    let prefix;
    let num;
    let year;
    if (m[2] && /^[TZX]$/i.test(m[2])) {
      prefix = (m[1] + m[2]).toUpperCase();
      num = m[3];
      year = m[4] || "";
    } else {
      prefix = m[1].toUpperCase();
      num = m[2];
      year = m[3] || "";
    }
    if (year && year.length === 2) year = `20${year}`;
    return year ? `${prefix}${num}-${year}` : `${prefix}${num}`;
  }

  function dedupeFilesPreferSmaller(list) {
    const best = new Map();
    for (const f of list || []) {
      const name = f.file_name || "";
      const identity = fileStdIdentityKey(name);
      const key =
        identity ||
        [
          (f.resolved_path || f.file_path || "").toLowerCase(),
          name.toLowerCase(),
        ].join("|");
      const size = Number(f.file_size) || 0;
      const prev = best.get(key);
      if (!prev) {
        best.set(key, f);
        continue;
      }
      const prevSize = Number(prev.file_size) || 0;
      const better =
        (f.exists ? 1 : 0) - (prev.exists ? 1 : 0) ||
        (size > 0 ? 1 : 0) - (prevSize > 0 ? 1 : 0) ||
        (size > 0 && prevSize > 0 ? prevSize - size : 0) ||
        ((f.id != null ? 1 : 0) - (prev.id != null ? 1 : 0));
      if (better > 0) best.set(key, f);
    }
    return Array.from(best.values());
  }

  function renderDetailHtml(item) {
    const files = dedupeFilesPreferSmaller(item.files || [])
      .map(f => {
        const href = f.id ? `/api/download/${f.id}` : "#";
        const icon = "PDF";
        const meta = [
          f.file_size ? fmtSize(f.file_size) : "",
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
            ${
              f.exists
                ? `<a class="btn-dl" href="${href}" download>下载</a>`
                : `<span class="btn-dl disabled">无文件</span>`
            }
          </div>`;
      })
      .join("");
    const blockTitle = isCatalogMode(currentMode) ? "文件" : "PDF 文件";
    return `
      <div class="pdf-block">
        <h3>${blockTitle}</h3>
        ${files || '<div class="file-meta">暂无匹配该版本的 PDF 文件</div>'}
      </div>`;
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
    cell.innerHTML = '<div class="loading"><div class="spinner"></div>正在加载 PDF 详情…</div>';
    try {
      const res = await fetch(`/api/std/${id}`);
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
        dl.outerHTML = `<a class="btn-row-dl" href="${href}" download title="下载" onclick="event.stopPropagation()">下载</a>`;
      }
    } catch (e) {
      cell.innerHTML = `<div class="alert">${escapeHtml(e.message || "加载失败")}</div>`;
    }
  }

  function renderItems(data) {
    const items = data.items || [];


    if (!items.length) {
      results.innerHTML =
        '<div class="empty">未找到匹配结果，可换关键词或调整高级筛选</div>';
      return;
    }

    const canBulk =
      currentMode === "search" ||
      isCatalogMode(currentMode);
    const from = data.total ? (data.page - 1) * data.per_page + 1 : 0;
    const to = Math.min(data.page * data.per_page, data.total);
    const advHint =
      currentMode === "search" && window.AdvancedUI?.filterSummary?.();
    let html = `<section class="results-card">`;
    if (advHint) {
      html += `<div class="adv-filter-banner">当前筛选：${escapeHtml(advHint)}</div>`;
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
              ${
                dlHref
                  ? `<a class="btn-row-dl" href="${dlHref}" download title="下载" onclick="event.stopPropagation()">下载</a>`
                  : `<span class="btn-row-dl disabled">下载</span>`
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

    document.getElementById("pgPrev")?.addEventListener("click", () => doSearch(data.page - 1));
    document.getElementById("pgNext")?.addEventListener("click", () => doSearch(data.page + 1));
    results.querySelectorAll(".pager-num").forEach(btn => {
      btn.addEventListener("click", () => doSearch(Number(btn.dataset.page)));
    });

    window.AdvancedUI?.onResultsRendered?.(data, currentMode);
  }

  function isAbortError(err) {
    return err?.name === "AbortError" || err?.code === 20;
  }

  function searchButtonLabel() {
    return "检索";
  }

  function cancelSearch() {
    if (searchController) {
      searchController.abort();
      searchController = null;
    }
  }

  function setSearching(on) {
    if (!btnSearch) return;
    if (on) {
      btnSearch.disabled = false;
      btnSearch.type = "button";
      btnSearch.textContent = "取消";
      btnSearch.classList.add("is-cancel");
      btnSearch.title = "取消当前检索（Esc）";
      btnSearch.setAttribute("aria-label", "取消检索");
    } else {
      btnSearch.classList.remove("is-cancel");
      btnSearch.type = "submit";
      btnSearch.textContent = searchButtonLabel();
      btnSearch.title = "";
      btnSearch.removeAttribute("aria-label");
      btnSearch.disabled = false;
    }
  }

  async function doSearch(page) {
    const q = (input?.value || "").trim();
    const advActive = currentMode === "search" && window.AdvancedUI?.hasActiveFilters?.();
    const workflow =
      currentMode === "search"
        ? window.WorkflowUI?.resolveWorkflow?.({ q, hasFilters: advActive }) || "combined"
        : "combined";

    if (!q && !advActive) {
      results.innerHTML = `<div class="alert">${escapeHtml("请输入关键词或设置高级筛选条件")}</div>`;
      return;
    }
    currentPage = page || 1;

    cancelSearch();
    searchController = new AbortController();
    const { signal } = searchController;

    setSearching(true);
    results.innerHTML = `
      <div class="loading searching">
        <div class="loading-head">
          <p class="loading-text">正在检索…</p>
          <button type="button" class="btn-cancel-search" id="btnCancelSearch">取消检索</button>
        </div>
        <div class="skeleton-table" aria-hidden="true">
          <div class="skeleton-row is-head">
            <div class="skeleton-bar w-md"></div>
            <div class="skeleton-bar w-lg"></div>
            <div class="skeleton-bar w-sm"></div>
            <div class="skeleton-bar w-sm"></div>
            <div class="skeleton-bar w-sm"></div>
          </div>
          <div class="skeleton-row">
            <div class="skeleton-bar w-lg"></div>
            <div class="skeleton-bar w-full"></div>
            <div class="skeleton-bar w-md"></div>
            <div class="skeleton-bar w-sm"></div>
            <div class="skeleton-bar w-sm"></div>
          </div>
          <div class="skeleton-row">
            <div class="skeleton-bar w-md"></div>
            <div class="skeleton-bar w-lg"></div>
            <div class="skeleton-bar w-sm"></div>
            <div class="skeleton-bar w-md"></div>
            <div class="skeleton-bar w-sm"></div>
          </div>
          <div class="skeleton-row">
            <div class="skeleton-bar w-full"></div>
            <div class="skeleton-bar w-md"></div>
            <div class="skeleton-bar w-sm"></div>
            <div class="skeleton-bar w-sm"></div>
            <div class="skeleton-bar w-sm"></div>
          </div>
          <div class="skeleton-row">
            <div class="skeleton-bar w-md"></div>
            <div class="skeleton-bar w-full"></div>
            <div class="skeleton-bar w-md"></div>
            <div class="skeleton-bar w-sm"></div>
            <div class="skeleton-bar w-sm"></div>
          </div>
          <div class="skeleton-row">
            <div class="skeleton-bar w-lg"></div>
            <div class="skeleton-bar w-lg"></div>
            <div class="skeleton-bar w-sm"></div>
            <div class="skeleton-bar w-md"></div>
            <div class="skeleton-bar w-sm"></div>
          </div>
        </div>
      </div>`;
    document.getElementById("btnCancelSearch")?.addEventListener("click", cancelSearch);

    const params = new URLSearchParams();
    params.set("q", q);
    params.set("page", String(currentPage));
    params.set("per_page", String(PER_PAGE));
    params.set("enrich", "0");
    if (isCatalogMode(currentMode)) {
      params.set("source", currentMode);
    } else if (advActive && window.AdvancedUI?.filterQuery) {
      if (window.AdvancedUI.validateRankFilter && !window.AdvancedUI.validateRankFilter()) {
        setSearching(false);
        searchController = null;
        return;
      }
      const extra = new URLSearchParams(window.AdvancedUI.filterQuery());
      extra.forEach((v, k) => params.set(k, v));
    }
    if (currentMode === "search") params.set("workflow", workflow);

    try {
      const res = await fetch(`/api/search?${params.toString()}`, { signal });
      const ct = res.headers.get("content-type") || "";
      let data;
      if (ct.includes("application/json")) {
        data = await res.json();
      } else {
        throw new Error(
          res.status === 0
            ? "无法连接服务器，请确认已启动 启动.bat"
            : `服务器响应异常（HTTP ${res.status}），请重启服务后重试`
        );
      }
      if (signal.aborted) return;
      if (!data.ok) {
        results.innerHTML = `<div class="alert">${escapeHtml(data.error || "检索失败")}</div>`;
        return;
      }
      renderItems(data);
    } catch (e) {
      if (isAbortError(e)) {
        results.innerHTML = '<div class="alert alert-cancel">已取消检索</div>';
        return;
      }
      results.innerHTML = `<div class="alert">检索失败：${escapeHtml(e.message || "网络错误")}</div>`;
    } finally {
      if (searchController?.signal === signal) searchController = null;
      setSearching(false);
    }
  }


  if (form) {
    form.addEventListener("submit", e => {
      e.preventDefault();
      if (btnSearch?.classList.contains("is-cancel")) {
        cancelSearch();
        return;
      }
      doSearch(1);
    });
  }

  btnSearch?.addEventListener("click", e => {
    if (!btnSearch.classList.contains("is-cancel")) return;
    e.preventDefault();
    cancelSearch();
  });

  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && btnSearch?.classList.contains("is-cancel")) {
      e.preventDefault();
      cancelSearch();
    }
  });

  window.addEventListener("advanced-search", () => doSearch(1));

  async function loadHealth() {
    if (!headerDbStatus) return;
    try {
      const res = await fetch("/api/meta/health");
      const data = await res.json();
      if (!data.ok) return;
      headerDbStatus.textContent = `数据库: ${data.db_backend || "—"} · ${data.db_ready ? "就绪" : "未就绪"}`;
    } catch (_) {
      headerDbStatus.textContent = "服务连接中…";
    }
  }

  loadHealth();
  setMode("search");

  window.AppUI = { setMode, doSearch, getMode: () => currentMode };
})();
