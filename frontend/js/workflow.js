/** 隐式双工作流：不外显切换，按用户实际操作顺序自动判定。 */
(function () {
  /** @type {null | "search" | "filter"} 本会话中先发生的有效路径 */
  let primaryPath = null;

  function resetPath() {
    primaryPath = null;
  }

  function resolveWorkflow({ q, hasFilters }) {
    const hasQ = Boolean((q || "").trim());
    const filtersOn = Boolean(hasFilters);

    if (!hasQ && !filtersOn) return "combined";

    if (!primaryPath) {
      if (filtersOn && !hasQ) primaryPath = "filter";
      else if (hasQ && !filtersOn) primaryPath = "search";
      // 同时带上关键词与筛选：无法区分先后，保持未锁定，走 combined
    }

    if (hasQ && filtersOn) {
      if (primaryPath === "filter") return "filter_first";
      if (primaryPath === "search") return "search_first";
      return "combined";
    }
    if (filtersOn) return "filter_first";
    return "search_first";
  }

  function updateWorkflowUi() {
    const appMode = window.AppUI?.getMode?.() || "search";
    const query = document.getElementById("query");
    const btnApply = document.getElementById("btnAdvancedApply");
    if (appMode !== "search") return;
    if (query) {
      query.placeholder = "标准编号或名称关键词，如 GB/T 1002-2024、煤矿";
    }
    if (btnApply) btnApply.textContent = "应用筛选";
  }

  updateWorkflowUi();

  window.WorkflowUI = {
    resolveWorkflow,
    resetPath,
    updateWorkflowUi,
    getWorkflow: () => "combined",
    setWorkflow: () => {},
    loadWorkflow: updateWorkflowUi,
  };
})();
