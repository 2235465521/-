/** 标准检索双工作流：先查询后筛选 / 先筛选后查询 */
(function () {
  const WORKFLOW_KEY = "pdf_search_workflow_v2";

  function getWorkflow() {
    const active = document.querySelector(".workflow-tab.active");
    return active?.dataset.workflow || "search_first";
  }

  function setWorkflow(mode) {
    document.querySelectorAll(".workflow-tab").forEach(btn => {
      const on = btn.dataset.workflow === mode;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });
    localStorage.setItem(WORKFLOW_KEY, mode);
    updateWorkflowUi();
  }

  function loadWorkflow() {
    const saved = localStorage.getItem(WORKFLOW_KEY);
    if (saved === "filter_first" || saved === "search_first") setWorkflow(saved);
    else updateWorkflowUi();
  }

  function updateWorkflowUi() {
    const mode = getWorkflow();
    const appMode = window.AppUI?.getMode?.() || "search";
    const segment = document.getElementById("workflowSegment");
    const guide = document.getElementById("workflowGuide");
    const steps = document.getElementById("workflowSteps");
    const tip = document.getElementById("workflowGuideTip");
    const query = document.getElementById("query");
    const btnApply = document.getElementById("btnAdvancedApply");
    const advHint = document.getElementById("advancedPanelHint");

    const isSearch = appMode === "search";
    if (segment) segment.hidden = !isSearch;
    if (guide) guide.hidden = !isSearch;
    if (!isSearch) return;

    if (mode === "filter_first") {
      if (steps) {
        steps.innerHTML = `
          <span class="wf-step active" data-step="1"><em>1</em><span class="wf-step-text">设置高级筛选</span></span>
          <span class="wf-arrow">→</span>
          <span class="wf-step" data-step="2"><em>2</em><span class="wf-step-text">范围内关键词检索</span></span>`;
      }
      if (tip) {
        tip.textContent =
          "先打开「高级选项」设置省/市/单位等条件并应用，再在搜索框输入关键词缩小范围。";
      }
      if (query) query.placeholder = "在已筛选范围内输入关键词（可选）";
      if (btnApply) btnApply.textContent = "应用筛选（第 1 步）";
      if (advHint) {
        advHint.textContent = "先筛选后查询：设置条件后点击「应用筛选」建立范围";
      }
    } else {
      if (steps) {
        steps.innerHTML = `
          <span class="wf-step active" data-step="1"><em>1</em><span class="wf-step-text">输入关键词检索</span></span>
          <span class="wf-arrow">→</span>
          <span class="wf-step" data-step="2"><em>2</em><span class="wf-step-text">叠加高级筛选</span></span>`;
      }
      if (tip) {
        tip.textContent =
          "先在搜索框输入标准编号或名称检索，再打开「高级选项」叠加筛选条件。";
      }
      if (query) query.placeholder = "标准编号或名称关键词，如 GB/T 1002-2024、煤矿";
      if (btnApply) btnApply.textContent = "在此基础上筛选（第 2 步）";
      if (advHint) {
        advHint.textContent = "先查询后筛选：完成检索后可叠加省/市/单位等条件";
      }
    }
  }

  document.querySelectorAll(".workflow-tab").forEach(btn => {
    btn.addEventListener("click", () => {
      setWorkflow(btn.dataset.workflow || "search_first");
    });
  });

  loadWorkflow();

  window.WorkflowUI = {
    getWorkflow,
    setWorkflow,
    updateWorkflowUi,
    loadWorkflow,
  };
})();
