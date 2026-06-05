/** 高级筛选 + 检索结果多项下载 */
(function () {
  const el = id => document.getElementById(id);
  const panel = el("advancedPanel");
  const btnToggle = el("btnAdvancedToggle");
  const btnBulk = el("btnBulkDownload");
  const bulkCount = el("bulkCount");
  const chkPage = el("chkSelectPage");
  const searchTools = el("searchTools");

  const fields = {
    exState: el("advExState"),
    stdType: el("advStdType"),
    province: el("advProvince"),
    city: el("advCity"),
    county: el("advCounty"),
    product: el("advProduct"),
    company: el("advCompany"),
    yearFrom: el("advYearFrom"),
    yearTo: el("advYearTo"),
  };

  const selected = new Map();
  let lastPageIds = [];
  let filtersLoaded = false;

  function apiUrl(path) {
    const base = (window.APP_CONFIG && window.APP_CONFIG.API_BASE) || "";
    return base + path;
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s || "";
    return d.innerHTML;
  }

  function fillSelect(select, items, placeholder, valueKey, labelKey) {
    if (!select) return;
    const cur = select.value;
    select.innerHTML = `<option value="">${escapeHtml(placeholder)}</option>`;
    (items || []).forEach(it => {
      const opt = document.createElement("option");
      if (typeof it === "string") {
        opt.value = it;
        opt.textContent = it;
      } else {
        opt.value = String(it[valueKey] ?? "");
        opt.textContent = String(it[labelKey] ?? it[valueKey] ?? "");
      }
      select.appendChild(opt);
    });
    if (cur && [...select.options].some(o => o.value === cur)) {
      select.value = cur;
    }
  }

  async function loadFilters(opts = {}) {
    const params = new URLSearchParams();
    if (opts.province) params.set("province", opts.province);
    if (opts.city) params.set("city", opts.city);
    if (opts.company_q) params.set("company_q", opts.company_q);
    try {
      const res = await fetch(apiUrl("/api/search/filters?" + params.toString()));
      const data = await res.json();
      if (!data.ok) return;
      if (!opts.province) {
        fillSelect(fields.province, data.provinces, "省（全部）");
        fillSelect(fields.stdType, data.std_types, "标准类型（全部）");
        fillSelect(
          fields.product,
          (data.products || []).map(p => ({
            value: p.id || p.name,
            label: p.name ? `${p.name}${p.sample ? " · " + p.sample : ""}` : p.id,
          })),
          "产品（全部）",
          "value",
          "label"
        );
        if (fields.exState && !fields.exState.options.length) {
          fillSelect(fields.exState, data.ex_states, "状态（全部）", "value", "label");
        }
        filtersLoaded = true;
      }
      if (opts.province) fillSelect(fields.city, data.cities, "市（全部）");
      if (opts.province && opts.city) fillSelect(fields.county, data.counties, "县/区（全部）");
      if (opts.company_q && fields.company) {
        const list = data.companies || [];
        const dl = el("advCompanyList");
        if (dl) {
          dl.innerHTML = list.map(n => `<option value="${escapeHtml(n)}">`).join("");
        }
      }
    } catch (_) {}
  }

  function hasActiveFilters() {
    return Object.values(fields).some(f => f && String(f.value || "").trim());
  }

  function filterQuery() {
    const p = new URLSearchParams();
    p.set("advanced", "1");
    if (fields.exState && fields.exState.value) p.set("ex_state", fields.exState.value);
    if (fields.stdType && fields.stdType.value) p.set("std_type", fields.stdType.value);
    if (fields.province && fields.province.value) p.set("province", fields.province.value);
    if (fields.city && fields.city.value) p.set("city", fields.city.value);
    if (fields.county && fields.county.value) p.set("county", fields.county.value);
    if (fields.product && fields.product.value) p.set("product", fields.product.value);
    if (fields.company && fields.company.value.trim()) p.set("company", fields.company.value.trim());
    if (fields.yearFrom && fields.yearFrom.value) p.set("year_from", fields.yearFrom.value);
    if (fields.yearTo && fields.yearTo.value) p.set("year_to", fields.yearTo.value);
    return p.toString();
  }

  function updateBulkBtn() {
    const n = selected.size;
    if (bulkCount) bulkCount.textContent = String(n);
    if (btnBulk) btnBulk.disabled = n < 1;
  }

  function syncPageCheckbox() {
    if (!chkPage) return;
    if (!lastPageIds.length) {
      chkPage.checked = false;
      chkPage.indeterminate = false;
      return;
    }
    const checked = lastPageIds.filter(id => selected.has(id)).length;
    chkPage.checked = checked === lastPageIds.length;
    chkPage.indeterminate = checked > 0 && checked < lastPageIds.length;
  }

  function toggleSelect(id, stdId, hasPdf, checked) {
    if (checked) selected.set(id, { id, std_id: stdId, has_pdf: hasPdf });
    else selected.delete(id);
    updateBulkBtn();
    syncPageCheckbox();
  }

  function onResultsRendered(data, searchMode) {
    if (searchMode === "batch" || searchMode === "stats") return;
    if (searchMode !== "db" && searchMode !== "product") {
      if (searchTools) searchTools.hidden = true;
      return;
    }
    if (searchTools) searchTools.hidden = false;

    lastPageIds = [];
    const items = data.items || [];
    items.forEach(item => {
      lastPageIds.push(item.id);
      const row = document.querySelector(`.result-row[data-id="${item.id}"]`);
      if (!row || row.querySelector(".row-check")) return;
      const wrap = document.createElement("label");
      wrap.className = "row-check";
      wrap.title = "加入多项下载";
      wrap.addEventListener("click", e => e.stopPropagation());
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.className = "bulk-item-check";
      cb.dataset.id = String(item.id);
      cb.dataset.stdId = item.std_id || "";
      cb.checked = selected.has(item.id);
      cb.addEventListener("change", () => {
        toggleSelect(item.id, item.std_id, item.has_pdf, cb.checked);
      });
      wrap.appendChild(cb);
      row.insertBefore(wrap, row.firstChild);
    });
    syncPageCheckbox();
  }

  function clearSelection() {
    selected.clear();
    updateBulkBtn();
    document.querySelectorAll(".bulk-item-check").forEach(cb => {
      cb.checked = false;
    });
    syncPageCheckbox();
  }

  async function doBulkDownload() {
    if (!selected.size) return;
    const scan = el("advScanDisk")?.checked === true;
    btnBulk.disabled = true;
    btnBulk.textContent = "打包中…";
    try {
      const res = await fetch(apiUrl("/api/download/bulk"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ids: [...selected.keys()],
          scan_disk: scan,
        }),
      });
      if (!res.ok) {
        let err = "下载失败";
        try {
          const j = await res.json();
          err = j.error || err;
        } catch (_) {}
        alert(err);
        return;
      }
      const blob = await res.blob();
      const disp = res.headers.get("content-disposition") || "";
      let name = "标准PDF多项下载.zip";
      const m = /filename\*?=(?:UTF-8'')?["']?([^"';]+)/i.exec(disp);
      if (m) name = decodeURIComponent(m[1].trim());
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      alert(e.message || "网络错误");
    } finally {
      btnBulk.innerHTML = `多项下载 (<span id="bulkCount">${selected.size}</span>)`;
      updateBulkBtn();
    }
  }

  function resetFilters() {
    Object.values(fields).forEach(f => {
      if (f) f.value = "";
    });
    fillSelect(fields.city, [], "市（全部）");
    fillSelect(fields.county, [], "县/区（全部）");
  }

  if (btnToggle && panel) {
    btnToggle.addEventListener("click", () => {
      const open = panel.hidden;
      panel.hidden = !open;
      btnToggle.classList.toggle("active", open);
      if (open && !filtersLoaded) loadFilters();
    });
  }

  if (fields.province) {
    fields.province.addEventListener("change", () => {
      if (fields.city) fields.city.value = "";
      if (fields.county) fields.county.value = "";
      loadFilters({ province: fields.province.value });
    });
  }
  if (fields.city) {
    fields.city.addEventListener("change", () => {
      if (fields.county) fields.county.value = "";
      loadFilters({ province: fields.province?.value, city: fields.city.value });
    });
  }
  if (fields.company) {
    let t = null;
    fields.company.addEventListener("input", () => {
      clearTimeout(t);
      const v = fields.company.value.trim();
      if (v.length < 2) return;
      t = setTimeout(() => loadFilters({ company_q: v }), 300);
    });
  }

  el("btnAdvancedApply")?.addEventListener("click", () => {
    window.dispatchEvent(new CustomEvent("advanced-search"));
  });
  el("btnAdvancedReset")?.addEventListener("click", () => {
    resetFilters();
  });

  if (chkPage) {
    chkPage.addEventListener("change", () => {
      document.querySelectorAll(".result-row").forEach(row => {
        const id = +row.dataset.id;
        const cb = row.querySelector(".bulk-item-check");
        if (!cb || !lastPageIds.includes(id)) return;
        cb.checked = chkPage.checked;
        toggleSelect(id, cb.dataset.stdId, true, chkPage.checked);
      });
    });
  }

  btnBulk?.addEventListener("click", doBulkDownload);

  window.AdvancedUI = {
    filterQuery,
    hasActiveFilters,
    onResultsRendered,
    clearSelection,
    resetFilters,
  };
})();
