/** 高级筛选 + 检索结果多项下载 */
(function () {
  const el = id => document.getElementById(id);
  const panel = el("advancedPanel");
  const btnToggle = el("btnAdvancedToggle");
  const btnBulk = el("btnBulkDownload");
  const btnGeo = el("btnGeoDownload");
  const chkPage = el("chkSelectPage");
  const searchTools = el("searchTools");

  const fields = {
    exState: el("advExState"),
    stdCategory: el("advStdCategory"),
    province: el("advProvince"),
    city: el("advCity"),
    county: el("advCounty"),
    product: el("advProduct"),
    company: el("advCompany"),
    unitRank: el("advUnitRank"),
    yearFrom: el("advYearFrom"),
    yearTo: el("advYearTo"),
  };

  const selected = new Map();
  let lastPageIds = [];
  let filtersLoaded = false;
  const CURRENT_YEAR = new Date().getFullYear();
  const YEAR_MIN = 1980;

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

  function fillStdCategorySelect(categories) {
    const select = fields.stdCategory;
    if (!select) return;
    const cur = select.value;
    fillSelect(select, categories || [], "标准大类（全部）");
    if (cur && [...select.options].some(o => o.value === cur)) {
      select.value = cur;
    }
  }

  /** AI/旧条件中的代号或口语 → 标准大类 */
  function inferStdCategory(raw) {
    const t = String(raw || "").trim();
    if (!t) return "";
    const cn = {
      国标: "国家标准",
      国家标准: "国家标准",
      行标: "行业标准",
      行业标准: "行业标准",
      地标: "地方标准",
      地方标准: "地方标准",
      团标: "团体标准",
      团体标准: "团体标准",
      企标: "行业标准",
      企业标准: "行业标准",
    };
    if (cn[t]) return cn[t];
    const u = t.toUpperCase().replace(/\s+/g, "");
    if (u.startsWith("GB")) return "国家标准";
    if (u.startsWith("DB")) return "地方标准";
    if (u === "T" || u.startsWith("T/")) return "团体标准";
    return "行业标准";
  }

  function initYearSelects() {
    const years = [];
    for (let y = CURRENT_YEAR; y >= YEAR_MIN; y -= 1) {
      years.push(String(y));
    }
    fillSelect(fields.yearFrom, years, "不限");
    fillSelect(fields.yearTo, years, "不限");
  }

  function applyYearPreset(spanYears) {
    const span = Number(spanYears);
    if (!span || span < 1) return;
    const to = CURRENT_YEAR;
    const from = Math.max(YEAR_MIN, to - span + 1);
    if (fields.yearFrom) fields.yearFrom.value = String(from);
    if (fields.yearTo) fields.yearTo.value = String(to);
    document.querySelectorAll(".year-preset").forEach(btn => {
      btn.classList.toggle("is-active", Number(btn.dataset.years) === span);
    });
  }

  function triggerAdvancedSearch() {
    if (!validateRankFilter()) return;
    if (typeof window.AppUI?.doSearch === "function") {
      window.AppUI.doSearch(1);
      return;
    }
    window.dispatchEvent(new CustomEvent("advanced-search"));
  }

  function syncYearRange() {
    const from = fields.yearFrom?.value;
    const to = fields.yearTo?.value;
    if (from && to && Number(from) > Number(to)) {
      fields.yearTo.value = from;
    }
  }

  let productSuggestItems = [];
  const productPanel = el("advProductPanel");
  let productComboOpen = false;
  let productActiveIdx = -1;

  function buildProductItems(products, suggestions) {
    const seen = new Set();
    const items = [];
    const add = (value, label, kind, cluster) => {
      const v = String(value || "").trim();
      if (!v || seen.has(v)) return;
      seen.add(v);
      items.push({
        value: v,
        label: label && label !== v ? label : "",
        kind: kind || "product",
        cluster: cluster || "",
      });
    };
    (products || []).forEach(p => {
      const name = String(p.name || "").trim();
      add(name, "产品大类", "category", name);
      (p.keywords || []).forEach(kw => add(kw, `${name} · ${kw}`, "product", name));
    });
    (suggestions || []).forEach(s => add(s, s, "product", ""));
    return items;
  }

  function setProductSuggestions(products, suggestions) {
    productSuggestItems = buildProductItems(products, suggestions);
    if (productComboOpen) renderProductPanel(fields.product?.value || "");
  }

  /** 展开某一产品大类：大类 + 其下全部小类 */
  function expandProductCluster(clusterName) {
    const name = String(clusterName || "").trim();
    if (!name) return [];
    const items = [];
    const cat = productSuggestItems.find(it => it.kind === "category" && it.value === name);
    if (cat) items.push(cat);
    productSuggestItems.forEach(it => {
      if (it.kind === "product" && it.cluster === name) items.push(it);
    });
    return items;
  }

  function filterProductItems(query) {
    const q = String(query || "").trim();
    // 空输入：只列产品大类，便于浏览完整目录
    if (!q) {
      return productSuggestItems.filter(it => it.kind === "category");
    }
    const qLower = q.toLowerCase();

    // 当前值正好是某大类 → 展示该大类及全部小类
    const exactCat = productSuggestItems.find(
      it => it.kind === "category" && it.value.toLowerCase() === qLower
    );
    if (exactCat) {
      return expandProductCluster(exactCat.value);
    }

    // 当前值正好是某小类 → 展示所属大类及同簇其余小类
    const exactProduct = productSuggestItems.find(
      it => it.kind === "product" && it.value.toLowerCase() === qLower
    );
    if (exactProduct?.cluster) {
      return expandProductCluster(exactProduct.cluster);
    }

    // 模糊匹配：若命中的小类同属一个大类，仍展开整簇便于切换
    const matchedProducts = productSuggestItems.filter(it => {
      if (it.kind !== "product") return false;
      return (
        it.value.toLowerCase().includes(qLower) ||
        (it.label && it.label.toLowerCase().includes(qLower))
      );
    });
    const clusters = [
      ...new Set(matchedProducts.map(it => it.cluster).filter(Boolean)),
    ];
    if (clusters.length === 1) {
      return expandProductCluster(clusters[0]);
    }

    const categories = [];
    const products = [];
    for (const it of productSuggestItems) {
      const hit =
        it.value.toLowerCase().includes(qLower) ||
        (it.label && it.label.toLowerCase().includes(qLower));
      if (!hit) continue;
      if (it.kind === "category") categories.push(it);
      else products.push(it);
    }
    return [...categories, ...products].slice(0, 100);
  }

  function highlightIndexForQuery(items, query) {
    const q = String(query || "").trim().toLowerCase();
    if (!q || !items.length) return -1;
    // 优先高亮当前小类，其次高亮同名大类
    let idx = items.findIndex(
      it => it.kind === "product" && it.value.toLowerCase() === q
    );
    if (idx >= 0) return idx;
    idx = items.findIndex(
      it => it.kind === "category" && it.value.toLowerCase() === q
    );
    if (idx >= 0) return idx;
    idx = items.findIndex(
      it => it.kind === "product" && it.value.toLowerCase().includes(q)
    );
    return idx;
  }

  function renderProductPanel(query) {
    if (!productPanel) return;
    const items = filterProductItems(query);
    if (!items.length) {
      hideProductPanel();
      return;
    }
    const q = String(query || "").trim();
    if (productActiveIdx < 0) {
      productActiveIdx = highlightIndexForQuery(items, q);
    } else if (productActiveIdx >= items.length) {
      productActiveIdx = highlightIndexForQuery(items, q);
    }
    const head = q
      ? ""
      : `<div class="adv-combo-group-title">产品大类（共 ${items.length} 类，输入可筛选具体产品）</div>`;
    productPanel.innerHTML =
      head +
      items
        .map((it, i) => {
          const hint = it.label
            ? `<span class="adv-combo-hint">${escapeHtml(it.label)}</span>`
            : "";
          const active = i === productActiveIdx ? " active" : "";
          const kindClass = it.kind === "category" ? " is-category" : "";
          const current =
            q && it.kind === "product" && it.value.toLowerCase() === q.toLowerCase()
              ? " is-current"
              : "";
          return `<button type="button" class="adv-combo-item${kindClass}${current}${active}" role="option" data-value="${escapeHtml(it.value)}">${escapeHtml(it.value)}${hint}</button>`;
        })
        .join("");
    productPanel.hidden = false;
    productComboOpen = true;
    if (productActiveIdx >= 0) {
      requestAnimationFrame(() => {
        productPanel
          .querySelectorAll(".adv-combo-item")
          [productActiveIdx]?.scrollIntoView({ block: "nearest" });
      });
    }
  }

  function hideProductPanel() {
    if (!productPanel) return;
    productPanel.hidden = true;
    productComboOpen = false;
    productActiveIdx = -1;
  }

  function pickProduct(value) {
    if (fields.product) fields.product.value = value;
    hideProductPanel();
  }

  function initProductCombo() {
    const input = fields.product;
    if (!input || !productPanel) return;

    input.addEventListener("focus", () => {
      productActiveIdx = -1;
      if (!productSuggestItems.length && !filtersLoaded) loadFilters();
      renderProductPanel(input.value);
    });

    input.addEventListener("input", () => {
      productActiveIdx = -1;
      renderProductPanel(input.value);
    });

    input.addEventListener("keydown", e => {
      if (!productComboOpen) return;
      const buttons = [...productPanel.querySelectorAll(".adv-combo-item")];
      if (e.key === "ArrowDown") {
        e.preventDefault();
        productActiveIdx = Math.min(productActiveIdx + 1, buttons.length - 1);
        renderProductPanel(input.value);
        productPanel.querySelectorAll(".adv-combo-item")[productActiveIdx]?.scrollIntoView({
          block: "nearest",
        });
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        productActiveIdx = Math.max(productActiveIdx - 1, 0);
        renderProductPanel(input.value);
        productPanel.querySelectorAll(".adv-combo-item")[productActiveIdx]?.scrollIntoView({
          block: "nearest",
        });
      } else if (e.key === "Enter" && productActiveIdx >= 0) {
        e.preventDefault();
        const btn = productPanel.querySelectorAll(".adv-combo-item")[productActiveIdx];
        if (btn) pickProduct(btn.dataset.value);
      } else if (e.key === "Escape") {
        hideProductPanel();
      }
    });

    productPanel.addEventListener("mousedown", e => {
      e.preventDefault();
      const btn = e.target.closest(".adv-combo-item");
      if (btn) pickProduct(btn.dataset.value);
    });

    input.addEventListener("blur", () => {
      setTimeout(hideProductPanel, 150);
    });
  }

  let companySuggestItems = [];
  const companyPanel = el("advCompanyPanel");
  let companyComboOpen = false;
  let companyActiveIdx = -1;
  let companySuggestTimer = null;
  let companySuggestLoading = false;
  let companySuggestSeq = 0;

  function companyInputActive() {
    return document.activeElement === fields.company;
  }

  function setCompanySuggestions(names) {
    companySuggestItems = (names || [])
      .map(n => String(n || "").trim())
      .filter(Boolean)
      .map(v => ({ value: v, label: "" }));
    companySuggestLoading = false;
    if (companyInputActive() || (fields.company?.value.trim().length >= 2)) {
      renderCompanyPanel(fields.company?.value || "");
    }
  }

  function rankCompanyItems(items, query) {
    const q = String(query || "").trim().toLowerCase();
    if (!q) return items;
    return [...items].sort((a, b) => {
      const av = a.value.toLowerCase();
      const bv = b.value.toLowerCase();
      const ap = av.startsWith(q) ? 0 : 1;
      const bp = bv.startsWith(q) ? 0 : 1;
      if (ap !== bp) return ap - bp;
      return av.length - bv.length || av.localeCompare(bv, "zh-CN");
    });
  }

  function filterCompanyItems(query) {
    const q = String(query || "").trim().toLowerCase();
    if (!q) return companySuggestItems.slice(0, 48);
    return rankCompanyItems(
      companySuggestItems.filter(it => it.value.toLowerCase().includes(q)),
      q
    ).slice(0, 48);
  }

  function renderCompanyPanel(query) {
    if (!companyPanel) return;
    const q = String(query || "").trim();
    const items = filterCompanyItems(query);
    if (q.length >= 2 && companySuggestLoading && !items.length) {
      companyPanel.innerHTML = `<div class="adv-combo-empty">加载中…</div>`;
      companyPanel.hidden = false;
      companyComboOpen = true;
      return;
    }
    if (!items.length) {
      if (q.length >= 2 && !companySuggestLoading) {
        companyPanel.innerHTML = `<div class="adv-combo-empty">无匹配单位</div>`;
        companyPanel.hidden = false;
        companyComboOpen = true;
        return;
      }
      hideCompanyPanel();
      return;
    }
    companyPanel.innerHTML = items
      .map((it, i) => {
        const active = i === companyActiveIdx ? " active" : "";
        return `<button type="button" class="adv-combo-item${active}" role="option" data-value="${escapeHtml(it.value)}">${escapeHtml(it.value)}</button>`;
      })
      .join("");
    companyPanel.hidden = false;
    companyComboOpen = true;
  }

  function hideCompanyPanel() {
    if (!companyPanel) return;
    companyPanel.hidden = true;
    companyComboOpen = false;
    companyActiveIdx = -1;
  }

  function pickCompany(value) {
    if (fields.company) fields.company.value = value;
    hideCompanyPanel();
  }

  async function fetchCompanySuggestions(query) {
    const q = String(query || "").trim();
    clearTimeout(companySuggestTimer);
    if (q.length < 2) {
      companySuggestLoading = false;
      companySuggestItems = [];
      hideCompanyPanel();
      return;
    }
    companySuggestLoading = true;
    renderCompanyPanel(q);
    companySuggestTimer = setTimeout(async () => {
      const seq = ++companySuggestSeq;
      try {
        const res = await fetch(
          "/api/search/filters?company_q=" + encodeURIComponent(q)
        );
        const data = await res.json();
        if (seq !== companySuggestSeq) return;
        if (data.ok) setCompanySuggestions(data.companies);
        else companySuggestLoading = false;
      } catch (_) {
        if (seq === companySuggestSeq) {
          companySuggestLoading = false;
          renderCompanyPanel(fields.company?.value || q);
        }
      }
    }, 200);
  }

  function initCompanyCombo() {
    const input = fields.company;
    if (!input || !companyPanel) return;

    input.addEventListener("focus", () => {
      companyActiveIdx = -1;
      fetchCompanySuggestions(input.value);
    });

    input.addEventListener("input", () => {
      companyActiveIdx = -1;
      fetchCompanySuggestions(input.value);
    });

    input.addEventListener("keydown", e => {
      if (!companyComboOpen) return;
      const buttons = [...companyPanel.querySelectorAll(".adv-combo-item")];
      if (e.key === "ArrowDown") {
        e.preventDefault();
        companyActiveIdx = Math.min(companyActiveIdx + 1, buttons.length - 1);
        renderCompanyPanel(input.value);
        companyPanel.querySelectorAll(".adv-combo-item")[companyActiveIdx]?.scrollIntoView({
          block: "nearest",
        });
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        companyActiveIdx = Math.max(companyActiveIdx - 1, 0);
        renderCompanyPanel(input.value);
        companyPanel.querySelectorAll(".adv-combo-item")[companyActiveIdx]?.scrollIntoView({
          block: "nearest",
        });
      } else if (e.key === "Enter" && companyActiveIdx >= 0) {
        e.preventDefault();
        const btn = companyPanel.querySelectorAll(".adv-combo-item")[companyActiveIdx];
        if (btn) pickCompany(btn.dataset.value);
      } else if (e.key === "Escape") {
        hideCompanyPanel();
      }
    });

    companyPanel.addEventListener("mousedown", e => {
      e.preventDefault();
      const btn = e.target.closest(".adv-combo-item");
      if (btn) pickCompany(btn.dataset.value);
    });

    input.addEventListener("blur", () => {
      setTimeout(hideCompanyPanel, 150);
    });
  }

  function appendFilterParams(p) {
    if (fields.exState?.value) p.set("ex_state", fields.exState.value);
    if (fields.stdCategory?.value) p.set("std_category", fields.stdCategory.value);
    if (fields.province?.value) p.set("province", fields.province.value);
    if (fields.city?.value) p.set("city", fields.city.value);
    if (fields.county?.value) p.set("county", fields.county.value);
    if (fields.product?.value.trim()) p.set("product", fields.product.value.trim());
    if (fields.company?.value.trim()) p.set("company", fields.company.value.trim());
    if (fields.unitRank?.value) p.set("unit_rank", fields.unitRank.value);
    if (fields.yearFrom?.value) p.set("year_from", fields.yearFrom.value);
    if (fields.yearTo?.value) p.set("year_to", fields.yearTo.value);
  }

  async function loadFilters(opts = {}) {
    const params = new URLSearchParams();
    if (opts.province) params.set("province", opts.province);
    if (opts.city) params.set("city", opts.city);
    if (opts.company_q) params.set("company_q", opts.company_q);
    if (opts.product_q) params.set("product_q", opts.product_q);
    try {
      const res = await fetch("/api/search/filters?" + params.toString());
      const data = await res.json();
      if (!data.ok) return;
      if (data.provinces && !opts.province && !opts.company_q && !opts.product_q) {
        fillSelect(fields.province, data.provinces, "省（全部）");
        fillStdCategorySelect(data.std_categories);
        setProductSuggestions(data.products, null);
        if (fields.exState && fields.exState.options.length <= 1) {
          fillSelect(fields.exState, data.ex_states, "状态（全部）", "value", "label");
        }
        filtersLoaded = true;
      }
      if (opts.province) fillSelect(fields.city, data.cities, "市（全部）");
      if (opts.province && opts.city) fillSelect(fields.county, data.counties, "县/区（全部）");
      if (opts.product_q) {
        setProductSuggestions(data.products, data.product_suggestions);
      }
      if (opts.company_q) {
        setCompanySuggestions(data.companies);
        if (companyComboOpen) renderCompanyPanel(fields.company?.value || "");
      }
    } catch (_) {}
  }

  function hasActiveFilters() {
    return Object.entries(fields).some(([key, f]) => {
      if (!f) return false;
      if (key === "unitRank") {
        return Boolean(fields.company?.value.trim() && String(f.value || "").trim());
      }
      return Boolean(String(f.value || "").trim());
    });
  }

  function validateRankFilter() {
    if (fields.unitRank?.value && !fields.company?.value.trim()) {
      alert("「起草顺位」必须同时填写「公司/起草单位」，否则会按「任一顺位」匹配。");
      fields.unitRank.value = "";
      return false;
    }
    return true;
  }

  function filterSummary() {
    const parts = [];
    if (fields.province?.value) parts.push(fields.province.value);
    if (fields.city?.value) parts.push(fields.city.value);
    if (fields.county?.value) parts.push(fields.county.value);
    if (fields.company?.value.trim()) {
      parts.push(`起草单位含「${fields.company.value.trim()}」`);
    }
    if (fields.unitRank?.value && fields.company?.value.trim()) {
      parts.push(
        fields.unitRank.value === "gt3"
          ? "顺位大于三"
          : `仅第 ${fields.unitRank.value} 位`
      );
    }
    if (fields.product?.value.trim()) parts.push(`产品「${fields.product.value.trim()}」`);
    return parts.join(" · ");
  }

  function filterQuery() {
    const p = new URLSearchParams();
    p.set("advanced", "1");
    appendFilterParams(p);
    return p.toString();
  }

  function updateGeoBtn() {
    if (!btnGeo) return;
    const hasProvince = Boolean(fields.province?.value);
    btnGeo.disabled = !hasProvince;
    btnGeo.title = hasProvince
      ? "下载所选省/市条件下全部标准 PDF"
      : "需先选择省份";
  }

  function geoFilterParams() {
    const p = new URLSearchParams();
    appendFilterParams(p);
    p.set("pdf_only", "1");
    const q = el("query")?.value?.trim();
    if (q) p.set("q", q);
    return p;
  }

  function geoFilterBody() {
    const body = {};
    if (fields.exState?.value) body.ex_state = fields.exState.value;
    if (fields.stdCategory?.value) body.std_category = fields.stdCategory.value;
    if (fields.province?.value) body.province = fields.province.value;
    if (fields.city?.value) body.city = fields.city.value;
    if (fields.county?.value) body.county = fields.county.value;
    if (fields.product?.value.trim()) body.product = fields.product.value.trim();
    if (fields.company?.value.trim()) body.company = fields.company.value.trim();
    if (fields.unitRank?.value) body.unit_rank = fields.unitRank.value;
    if (fields.yearFrom?.value) body.year_from = fields.yearFrom.value;
    if (fields.yearTo?.value) body.year_to = fields.yearTo.value;
    body.pdf_only = true;
    const q = el("query")?.value?.trim();
    if (q) body.q = q;
    return body;
  }

  async function doGeoDownload() {
    if (!fields.province?.value) {
      alert("请先选择省份");
      return;
    }
    if (btnGeo) {
      btnGeo.disabled = true;
      btnGeo.textContent = "统计中…";
    }
    try {
      const previewRes = await fetch("/api/download/geo/preview?" + geoFilterParams().toString());
      const preview = await previewRes.json();
      if (!preview.ok) {
        alert(preview.error || "无法统计匹配数量");
        return;
      }
      const region = [fields.province?.value, fields.city?.value, fields.county?.value]
        .filter(Boolean)
        .join(" · ");
      let msg = `将下载「${region}」范围内共 ${preview.total} 条标准中的 PDF`;
      if (preview.capped) {
        msg += `\n（单次最多 ${preview.limit} 条，将下载前 ${preview.download_count} 条）`;
      }
      msg += "。\n打包可能需要较长时间，是否继续？";
      if (!window.confirm(msg)) return;

      if (btnGeo) btnGeo.textContent = "打包中…";
      const res = await fetch("/api/download/geo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(geoFilterBody()),
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
      let name = "地区批量下载.zip";
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
      updateGeoBtn();
      if (btnGeo) btnGeo.textContent = "地区批量下载";
    }
  }

  function updateBulkBtn() {
    const n = selected.size;
    const countEl = document.getElementById("bulkCount");
    if (countEl) countEl.textContent = String(n);
    if (btnBulk) btnBulk.disabled = n < 1;
  }

  function pageSelectableIds() {
    return lastPageIds.filter(id => {
      const row = document.querySelector(`.result-row[data-id="${id}"]`);
      const cb = row?.querySelector(".bulk-item-check");
      return cb && !cb.disabled;
    });
  }

  function syncPageCheckbox() {
    if (!chkPage) return;
    const ids = pageSelectableIds();
    if (!ids.length) {
      chkPage.checked = false;
      chkPage.indeterminate = false;
      return;
    }
    const checked = ids.filter(id => selected.has(Number(id))).length;
    chkPage.checked = checked === ids.length;
    chkPage.indeterminate = checked > 0 && checked < ids.length;
  }

  function toggleSelect(id, stdId, hasPdf, checked, syncMaster = true) {
    id = Number(id);
    if (checked) selected.set(id, { id, std_id: stdId, has_pdf: hasPdf });
    else selected.delete(id);
    updateBulkBtn();
    if (syncMaster) syncPageCheckbox();
  }

  function onResultsRendered(data, searchMode) {
    if (searchMode === "batch") return;
    if (searchMode !== "search") {
      return;
    }

    lastPageIds = (data.items || []).map(item => item.id);
    document.querySelectorAll(".bulk-item-check").forEach(cb => {
      if (cb.dataset.bound === "1") return;
      cb.dataset.bound = "1";
      cb.addEventListener("change", () => {
        const id = Number(cb.dataset.id);
        toggleSelect(id, cb.dataset.stdId || "", !cb.disabled, cb.checked);
      });
    });
    syncPageCheckbox();
    updateBulkBtn();
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
    if (btnBulk) {
      btnBulk.disabled = true;
      btnBulk.textContent = "打包中…";
    }
    try {
      const body = { ids: [...selected.keys()] };
      const res = await fetch("/api/download/bulk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
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
      if (btnBulk) {
        btnBulk.disabled = selected.size < 1;
        btnBulk.textContent = "";
        btnBulk.append("多项下载 (");
        const span = document.createElement("span");
        span.id = "bulkCount";
        span.textContent = String(selected.size);
        btnBulk.append(span, ")");
      }
    }
  }

  function resetFilters() {
    Object.values(fields).forEach(f => {
      if (f) f.value = "";
    });
    fillSelect(fields.city, [], "市（全部）");
    fillSelect(fields.county, [], "县/区（全部）");
    hideProductPanel();
    hideCompanyPanel();
    updateGeoBtn();
    if (!(el("query")?.value || "").trim()) {
      window.WorkflowUI?.resetPath?.();
    }
  }

  if (btnToggle && panel) {
    btnToggle.addEventListener("click", () => {
      const open = panel.hidden;
      panel.hidden = !open;
      btnToggle.classList.toggle("active", open);
      if (open && !filtersLoaded) loadFilters();
    });
  }

  fields.province?.addEventListener("change", () => {
    if (fields.city) fields.city.value = "";
    if (fields.county) fields.county.value = "";
    loadFilters({ province: fields.province.value });
    updateGeoBtn();
  });
  fields.city?.addEventListener("change", () => {
    if (fields.county) fields.county.value = "";
    loadFilters({ province: fields.province?.value, city: fields.city.value });
    updateGeoBtn();
  });
  fields.county?.addEventListener("change", updateGeoBtn);
  if (fields.product) {
    let pt = null;
    fields.product.addEventListener("input", () => {
      clearTimeout(pt);
      const v = fields.product.value.trim();
      if (v.length < 1) return;
      pt = setTimeout(() => loadFilters({ product_q: v }), 280);
    });
  }

  el("btnAdvancedApply")?.addEventListener("click", () => {
    triggerAdvancedSearch();
  });
  el("btnAdvancedReset")?.addEventListener("click", () => {
    resetFilters();
    document.querySelectorAll(".year-preset").forEach(btn => {
      btn.classList.remove("is-active");
    });
  });

  fields.unitRank?.addEventListener("change", () => {
    if (!fields.company?.value.trim()) return;
    if (!validateRankFilter()) return;
    triggerAdvancedSearch();
  });

  initYearSelects();
  initProductCombo();
  initCompanyCombo();
  fields.yearFrom?.addEventListener("change", syncYearRange);
  fields.yearTo?.addEventListener("change", syncYearRange);
  document.querySelectorAll(".year-preset").forEach(btn => {
    btn.addEventListener("click", () => applyYearPreset(btn.dataset.years));
  });

  chkPage?.addEventListener("change", e => {
    const want = e.target.checked;
    pageSelectableIds().forEach(id => {
      const row = document.querySelector(`.result-row[data-id="${id}"]`);
      const cb = row?.querySelector(".bulk-item-check");
      if (!cb) return;
      cb.checked = want;
      toggleSelect(id, cb.dataset.stdId || "", true, want, false);
    });
    updateBulkBtn();
    syncPageCheckbox();
  });

  btnBulk?.addEventListener("click", doBulkDownload);
  btnGeo?.addEventListener("click", doGeoDownload);

  updateGeoBtn();

  async function applyAiFilters(filters) {
    const f = filters || {};
    resetFilters();
    document.querySelectorAll(".year-preset.is-active").forEach(b => b.classList.remove("is-active"));

    const qInput = document.getElementById("query");
    if (qInput) qInput.value = f.q || "";

    // 先加载省列表，再按省刷市/县
    await loadFilters({});
    if (f.province && fields.province) {
      // 模糊匹配省名
      const provOpts = [...(fields.province.options || [])];
      const hitProv =
        provOpts.find(o => o.value === f.province) ||
        provOpts.find(o => o.value && (o.value.includes(f.province) || f.province.includes(o.value)));
      if (hitProv) fields.province.value = hitProv.value;
      else fields.province.value = f.province;
      await loadFilters({ province: fields.province.value });
    }
    if (f.city && fields.city) {
      const cityOpts = [...(fields.city.options || [])];
      const hitCity =
        cityOpts.find(o => o.value === f.city) ||
        cityOpts.find(o => o.value && (o.value.includes(f.city) || f.city.includes(o.value)));
      if (hitCity) fields.city.value = hitCity.value;
      if (fields.city.value) {
        await loadFilters({
          province: fields.province?.value || f.province,
          city: fields.city.value,
        });
      }
    }
    if (f.county && fields.county) {
      const countyOpts = [...(fields.county.options || [])];
      const hit =
        countyOpts.find(o => o.value === f.county) ||
        countyOpts.find(o => o.value && (o.value.includes(f.county) || f.county.includes(o.value)));
      if (hit) fields.county.value = hit.value;
    }

    if (f.ex_state != null && fields.exState) fields.exState.value = String(f.ex_state);
    if (fields.stdCategory) {
      const cat = f.std_category || (f.std_type ? inferStdCategory(f.std_type) : "");
      if (cat && [...fields.stdCategory.options].some(o => o.value === cat)) {
        fields.stdCategory.value = cat;
      }
    }
    if (f.product && fields.product) fields.product.value = f.product;
    if (f.company && fields.company) fields.company.value = f.company;
    if (f.unit_rank && fields.unitRank) fields.unitRank.value = String(f.unit_rank);
    if (f.year_from && fields.yearFrom) fields.yearFrom.value = String(f.year_from);
    if (f.year_to && fields.yearTo) fields.yearTo.value = String(f.year_to);

    if (hasActiveFilters() && panel) {
      panel.hidden = false;
      btnToggle?.classList.add("active");
    }
    updateGeoBtn();
  }

  window.AdvancedUI = {
    filterQuery,
    filterSummary,
    hasActiveFilters,
    validateRankFilter,
    onResultsRendered,
    clearSelection,
    resetFilters,
    applyAiFilters,
    isSelected: id => selected.has(Number(id)),
  };
})();