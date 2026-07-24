/** AI 自然语言检索：解析意图 → 填入高级筛选 → 触发检索 */
(function () {
  const panel = document.getElementById("aiSearchPanel");
  const input = document.getElementById("aiPrompt");
  const btn = document.getElementById("btnAiSearch");
  const hint = document.getElementById("aiSearchHint");
  const suggestions = document.getElementById("aiSuggestions");

  if (!panel || !input || !btn) return;

  function setHint(text, isError) {
    if (!hint) return;
    if (!text) {
      hint.hidden = true;
      hint.textContent = "";
      hint.classList.remove("is-error");
      return;
    }
    hint.hidden = false;
    hint.textContent = text;
    hint.classList.toggle("is-error", !!isError);
  }

  function setBusy(busy) {
    btn.disabled = busy;
    input.disabled = busy;
    btn.textContent = busy ? "解析中…" : "AI检索";
  }

  async function runAiSearch(promptText) {
    const prompt = (promptText || input.value || "").trim();
    if (!prompt) {
      setHint("请输入自然语言检索需求", true);
      return;
    }
    input.value = prompt;
    setBusy(true);
    setHint("正在理解检索意图…");
    try {
      const res = await fetch("/api/ai/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
      });
      const data = await res.json();
      if (!data.ok) {
        setHint(data.error || "AI 解析失败", true);
        return;
      }
      const filters = data.filters || {};
      if (typeof window.AdvancedUI?.applyAiFilters === "function") {
        await window.AdvancedUI.applyAiFilters(filters);
      } else if (filters.q) {
        const q = document.getElementById("query");
        if (q) q.value = filters.q;
      }
      const summary = filters.summary || "已应用 AI 解析的筛选条件";
      setHint("✓ " + summary);
      if (typeof window.AppUI?.setMode === "function") {
        window.AppUI.setMode("search");
      }
      if (typeof window.AppUI?.doSearch === "function") {
        window.AppUI.doSearch(1);
      }
    } catch (e) {
      setHint("网络错误：" + (e.message || "请稍后重试"), true);
    } finally {
      setBusy(false);
    }
  }

  btn.addEventListener("click", () => runAiSearch());
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      runAiSearch();
    }
  });
  suggestions?.addEventListener("click", (e) => {
    const chip = e.target.closest(".ai-sug");
    if (!chip) return;
    runAiSearch(chip.getAttribute("data-prompt") || chip.textContent);
  });

  window.AiSearchUI = {
    setVisible(show) {
      panel.hidden = !show;
    },
    run: runAiSearch,
  };
})();
