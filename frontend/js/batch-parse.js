/** 浏览器端 Excel/CSV 解析（不依赖后端） */
window.BatchParse = (function () {
  const MAX_ROWS = 400;

  const STD_HEADER_KEYS = [
    "标准编号", "标准号", "编号", "std_id", "stdid", "标准代码", "标准代号", "标准文号",
  ];
  const NAME_HEADER_KEYS = ["标准名称", "名称", "标准名", "title", "中文名称", "标准中文名称"];
  const STD_NUMBER_RE =
    /^(?:GB\/?T?|GB\/Z|GB|GJB\/?T?|DL\/?T?|DL|JB\/?T?|JB|JJF|JJG|HG\/?T?|NY\/?T?|SH\/?T?|SY\/?T?|ISO|IEC|ASTM|EN|Q(?:\/|[\s/]))/i;

  function normHeader(v) {
    return String(v || "")
      .trim()
      .toLowerCase()
      .replace(/\s+/g, "");
  }

  function cellText(v) {
    if (v == null) return "";
    if (typeof v === "number" && Number.isFinite(v)) {
      return Number.isInteger(v) ? String(v) : String(v);
    }
    return String(v).trim();
  }

  function looksLikeStdNumber(text) {
    const s = (text || "").trim();
    if (s.length < 3) return false;
    if (STD_NUMBER_RE.test(s)) return true;
    if (/^GB/i.test(s) && /\d/.test(s)) return true;
    if (s.startsWith("国网") || s.startsWith("Q/")) return true;
    if (/[\(（][^)）]+[\)）]/.test(s) && /\d/.test(s)) return true;
    const compact = s.replace(/\s+/g, "");
    return /\d{2,}/.test(compact) && /[A-Za-z/（）()\-—／]/.test(compact);
  }

  function detectColumns(headers) {
    let stdCol = null;
    let nameCol = null;
    for (let i = 0; i < headers.length; i++) {
      const nh = normHeader(headers[i]);
      if (STD_HEADER_KEYS.some(k => normHeader(k) === nh || nh.includes("标准号") || nh.includes("编号"))) {
        stdCol = i;
      }
      if (NAME_HEADER_KEYS.some(k => normHeader(k) === nh || nh.includes("名称"))) {
        nameCol = i;
      }
    }
    return { std_col: stdCol, name_col: nameCol };
  }

  function findHeaderRow(rawRows) {
    for (let i = 0; i < Math.min(rawRows.length, 25); i++) {
      const cols = detectColumns(rawRows[i]);
      if (cols.std_col != null) return { idx: i, cols };
    }
    return null;
  }

  function shouldSkipRow(query, cells, cols) {
    const q = (query || "").trim();
    if (!q) return true;
    if (/^\d{1,4}$/.test(q)) return true;
    if (q.includes("明细表") || q.includes("标准清单")) return true;
    if (!looksLikeStdNumber(q)) return true;
    return false;
  }

  function rowsFromMatrix(rawRows, source) {
    if (!rawRows.length) {
      return { ok: false, error: "文件为空", items: [], meta: {} };
    }
    let headerIdx = -1;
    let cols = { std_col: null, name_col: null };
    const found = findHeaderRow(rawRows);
    if (found) {
      headerIdx = found.idx;
      cols = found.cols;
    } else {
      for (let i = 0; i < Math.min(rawRows.length, 40); i++) {
        for (let j = 0; j < rawRows[i].length; j++) {
          if (looksLikeStdNumber(rawRows[i][j])) {
            cols = { std_col: j, name_col: null };
            headerIdx = i > 0 ? i - 1 : -1;
            break;
          }
        }
        if (cols.std_col != null) break;
      }
    }
    const items = [];
    const start = headerIdx >= 0 ? headerIdx + 1 : 0;
    for (let i = start; i < rawRows.length; i++) {
      const cells = rawRows[i];
      const stdCol = cols.std_col;
      const query = stdCol != null && stdCol < cells.length ? cellText(cells[stdCol]) : "";
      if (shouldSkipRow(query, cells, cols)) continue;
      items.push({
        row: i + 1,
        query,
        name_hint: cols.name_col != null && cols.name_col < cells.length ? cellText(cells[cols.name_col]) : "",
      });
      if (items.length >= MAX_ROWS) break;
    }
    if (!items.length) {
      return {
        ok: false,
        error: "未识别到有效标准号，请确认含有「标准号/标准编号」列",
        items: [],
        meta: { source, header_row: headerIdx + 1 },
      };
    }
    return {
      ok: true,
      items,
      meta: {
        source,
        header_row: headerIdx >= 0 ? headerIdx + 1 : null,
        total_rows: items.length,
        truncated: items.length >= MAX_ROWS,
        max_rows: MAX_ROWS,
      },
    };
  }

  function parseCsv(data) {
    const text = new TextDecoder("utf-8").decode(data);
    const lines = text.replace(/^\uFEFF/, "").split(/\r?\n/);
    const rawRows = lines
      .map(line => {
        const cells = [];
        let cur = "";
        let inQ = false;
        for (let i = 0; i < line.length; i++) {
          const ch = line[i];
          if (ch === '"') {
            inQ = !inQ;
            continue;
          }
          if (ch === "," && !inQ) {
            cells.push(cur);
            cur = "";
            continue;
          }
          cur += ch;
        }
        cells.push(cur);
        return cells.map(c => cellText(c));
      })
      .filter(r => r.some(c => c));
    return rowsFromMatrix(rawRows, "csv");
  }

  function parseXlsx(data) {
    if (typeof XLSX === "undefined") {
      return { ok: false, error: "Excel 组件未加载", items: [], meta: {} };
    }
    const wb = XLSX.read(data, { type: "array" });
    const ws = wb.Sheets[wb.SheetNames[0]];
    const rows = XLSX.utils.sheet_to_json(ws, { header: 1, defval: "" });
    const rawRows = rows.map(r => (Array.isArray(r) ? r.map(cellText) : [])).filter(r => r.some(c => c));
    return rowsFromMatrix(rawRows, "xlsx");
  }

  function parseFile(filename, arrayBuffer) {
    const ext = (filename || "").split(".").pop().toLowerCase();
    if (ext === "csv") return parseCsv(arrayBuffer);
    if (ext === "xlsx" || ext === "xlsm") return parseXlsx(arrayBuffer);
    return { ok: false, error: "仅支持 .xlsx、.xlsm 或 .csv", items: [], meta: {} };
  }

  function normalizeStdId(s) {
    return String(s || "")
      .trim()
      .replace(/\s+/g, "")
      .replace(/／/g, "/")
      .replace(/—/g, "-")
      .toUpperCase();
  }

  function buildPdfIndex(files) {
    const list = [];
    const byNorm = new Map();
    for (const f of files) {
      if (!/\.pdf$/i.test(f.name)) continue;
      const normName = normalizeStdId(f.name.replace(/\.pdf$/i, ""));
      list.push({ file: f, normName, name: f.name });
      if (!byNorm.has(normName)) byNorm.set(normName, f);
    }
    return { list, byNorm };
  }

  function findPdfFile(query, index) {
    const nq = normalizeStdId(query);
    if (!nq) return null;
    if (index.byNorm.has(nq)) return index.byNorm.get(nq);
    for (const entry of index.list) {
      if (entry.normName.includes(nq) || nq.includes(entry.normName)) return entry.file;
    }
    const core = nq.replace(/[^A-Z0-9/\-]/g, "");
    if (core.length >= 4) {
      for (const entry of index.list) {
        if (entry.normName.replace(/[^A-Z0-9/\-]/g, "").includes(core)) return entry.file;
      }
    }
    return null;
  }

  function matchItems(items, pdfFiles) {
    const index = buildPdfIndex(pdfFiles);
    return items.map(it => {
      const pdf = findPdfFile(it.query, index);
      if (pdf) {
        return {
          row: it.row,
          query: it.query,
          status: "ok",
          std_id: it.query,
          std_chinesename: it.name_hint || "",
          pdf_name: pdf.name,
          file: pdf,
        };
      }
      return {
        row: it.row,
        query: it.query,
        status: "not_found",
        std_id: "—",
        std_chinesename: it.name_hint || "—",
        message: "文件夹中未找到匹配 PDF",
      };
    });
  }

  function buildTemplateWorkbook() {
    const data = [
      ["标准号", "标准名", "备注"],
      ["GB/T 1002-2024", "单相插头插座", ""],
      ["GB 5749-2022", "生活饮用水卫生标准", ""],
    ];
    const ws = XLSX.utils.aoa_to_sheet(data);
    ws["!cols"] = [{ wch: 22 }, { wch: 36 }, { wch: 10 }];
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "标准清单");
    return XLSX.write(wb, { bookType: "xlsx", type: "array" });
  }

  function annotateWorkbook(arrayBuffer, filename, results) {
    if (typeof XLSX === "undefined") return null;
    const ext = (filename || "").split(".").pop().toLowerCase();
    if (ext !== "xlsx" && ext !== "xlsm") return null;
    const wb = XLSX.read(arrayBuffer, { type: "array" });
    const ws = wb.Sheets[wb.SheetNames[0]];
    const rows = XLSX.utils.sheet_to_json(ws, { header: 1, defval: "" });
    const found = findHeaderRow(rows.map(r => (Array.isArray(r) ? r.map(cellText) : [])));
    if (!found) return null;
    const { idx, cols } = found;
    let remarkCol = rows[idx].length;
    rows[idx][remarkCol] = rows[idx][remarkCol] || "备注";
    const resultByRow = new Map(results.map(r => [r.row, r]));
    for (let i = idx + 1; i < rows.length; i++) {
      const cells = Array.isArray(rows[i]) ? rows[i] : [];
      while (cells.length <= remarkCol) cells.push("");
      const stdCol = cols.std_col;
      const q = stdCol != null && stdCol < cells.length ? cellText(cells[stdCol]) : "";
      if (!looksLikeStdNumber(q)) continue;
      const hit = resultByRow.get(i + 1);
      cells[remarkCol] = hit && hit.status === "ok" ? "" : "否";
      rows[i] = cells;
    }
    const newWs = XLSX.utils.aoa_to_sheet(rows);
    wb.Sheets[wb.SheetNames[0]] = newWs;
    return XLSX.write(wb, { bookType: "xlsx", type: "array" });
  }

  return {
    parseFile,
    matchItems,
    buildTemplateWorkbook,
    annotateWorkbook,
    MAX_ROWS,
  };
})();
