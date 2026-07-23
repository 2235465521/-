/** 登录会话：credentials 透传、401 跳转、页面门禁 */
(function (global) {
  const LOGIN_PATH = "/login";

  const _fetch = global.fetch.bind(global);
  global.fetch = function (input, init) {
    const opts = Object.assign({}, init || {});
    if (opts.credentials == null) opts.credentials = "same-origin";
    return _fetch(input, opts).then(async (res) => {
      if (res.status === 401) {
        const path = global.location.pathname || "";
        if (!path.startsWith("/login")) {
          let code = "";
          try {
            const data = await res.clone().json();
            code = data && data.code;
          } catch (_) { /* ignore */ }
          if (code === "auth_required" || !code) {
            const next = encodeURIComponent(path + (global.location.search || ""));
            global.location.href = LOGIN_PATH + "?next=" + next;
          }
        }
      }
      return res;
    });
  };

  async function me() {
    const res = await _fetch("/api/auth/me", { credentials: "same-origin" });
    return res.json();
  }

  async function login(username, password) {
    const res = await _fetch("/api/auth/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    return { status: res.status, data: await res.json() };
  }

  async function register(username, password, displayName) {
    const res = await _fetch("/api/auth/register", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username,
        password,
        display_name: displayName || "",
      }),
    });
    return { status: res.status, data: await res.json() };
  }

  async function logout() {
    await _fetch("/api/auth/logout", {
      method: "POST",
      credentials: "same-origin",
    });
    global.location.href = LOGIN_PATH;
  }

  async function requireAuth(opts) {
    const options = opts || {};
    const data = await me();
    if (!data.authenticated || !data.user) {
      const next = encodeURIComponent(
        global.location.pathname + (global.location.search || "")
      );
      global.location.href = LOGIN_PATH + "?next=" + next;
      return null;
    }
    if (options.admin && !data.user.is_admin) {
      global.location.href = "/";
      return null;
    }
    return data.user;
  }

  function paintHeaderUser(user) {
    const nameEl = document.getElementById("headerUserName");
    const roleEl = document.getElementById("headerUserRole");
    const roleTag = document.getElementById("headerUserRoleTag");
    const avatarEl = document.getElementById("headerAvatar");
    const enterConsole = document.getElementById("menuEnterConsole");
    const sidebarEntry = document.getElementById("sidebarAdminEntry");
    const roleText = user.is_admin ? "系统管理员" : "普通用户";
    if (nameEl) nameEl.textContent = user.display_name || user.username;
    if (roleEl) roleEl.textContent = roleText;
    if (roleTag) roleTag.textContent = roleText;
    if (avatarEl) {
      const label = (user.display_name || user.username || "?").trim();
      avatarEl.textContent = label.slice(0, 1).toUpperCase();
      avatarEl.title = user.username;
    }
    if (enterConsole) enterConsole.hidden = false;
    if (sidebarEntry) sidebarEntry.hidden = false;
  }

  function bindUserMenu(opts) {
    const options = opts || {};
    const root = document.getElementById(options.menuRootId || "headerUserMenu");
    const trigger = document.getElementById(options.triggerId || "headerUserTrigger");
    const panel = document.getElementById(options.panelId || "headerUserPanel");
    const logoutBtn = document.getElementById(options.logoutId || "btnLogout");
    if (!root || !trigger || !panel) return;

    function close() {
      panel.hidden = true;
      trigger.setAttribute("aria-expanded", "false");
    }

    function toggle(e) {
      e.stopPropagation();
      const open = panel.hidden;
      panel.hidden = !open;
      trigger.setAttribute("aria-expanded", open ? "true" : "false");
    }

    trigger.addEventListener("click", toggle);
    document.addEventListener("click", (e) => {
      if (!root.contains(e.target)) close();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") close();
    });
    if (logoutBtn) {
      logoutBtn.addEventListener("click", () => {
        logout();
      });
    }
  }

  function bindSidebarCollapse(opts) {
    const options = opts || {};
    const shell = document.getElementById(options.shellId || "appLayout");
    const btn = document.getElementById(options.buttonId || "btnToggleSidebar");
    const label = document.getElementById(options.labelId || "sidebarCollapseText");
    const key = options.storageKey || "zkbz_sidebar_collapsed";
    if (!shell || !btn) return;

    function apply(collapsed) {
      shell.classList.toggle("sidebar-collapsed", collapsed);
      btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
      btn.title = collapsed ? "展开侧边栏" : "收起侧边栏";
      if (label) label.textContent = collapsed ? "展开侧边栏" : "收起侧边栏";
      try {
        localStorage.setItem(key, collapsed ? "1" : "0");
      } catch (_) { /* ignore */ }
    }

    let collapsed = false;
    try {
      collapsed = localStorage.getItem(key) === "1";
    } catch (_) { /* ignore */ }
    apply(collapsed);

    btn.addEventListener("click", () => {
      apply(!shell.classList.contains("sidebar-collapsed"));
    });
  }

  global.Auth = {
    me,
    login,
    register,
    logout,
    requireAuth,
    paintHeaderUser,
    bindUserMenu,
    bindSidebarCollapse,
  };
})(window);
