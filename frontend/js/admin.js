/** 系统后台：个人中心（全员）+ 用户管理（仅管理员） */
(function () {
  let page = 1;
  let mode = "create";
  let currentUser = null;
  let usersLoaded = false;

  const tbody = document.getElementById("userTableBody");
  const pager = document.getElementById("userPager");
  const dialog = document.getElementById("userDialog");
  const form = document.getElementById("userForm");
  const dialogError = document.getElementById("dialogError");
  const panelProfile = document.getElementById("panelProfile");
  const panelUsers = document.getElementById("panelUsers");
  const pageTitle = document.getElementById("pageTitle");
  const navProfile = document.getElementById("navProfile");
  const navUsers = document.getElementById("navUsers");

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s || "";
    return d.innerHTML;
  }

  function showDialogError(msg) {
    dialogError.hidden = !msg;
    dialogError.textContent = msg || "";
  }

  function fillProfile(user) {
    const roleText = user.is_admin ? "管理员" : "普通用户";
    document.getElementById("pfUsername").textContent = user.username || "—";
    document.getElementById("pfDisplay").textContent = user.display_name || "—";
    document.getElementById("pfRole").textContent = roleText;
    document.getElementById("pfStatus").textContent = user.is_active ? "启用" : "停用";
    document.getElementById("pfCreated").textContent = user.created_at || "—";
    document.getElementById("pfLastLogin").textContent = user.last_login_at || "—";
  }

  function switchPanel(name) {
    const isUsers = name === "users" && currentUser && currentUser.is_admin;
    panelProfile.hidden = isUsers;
    panelUsers.hidden = !isUsers;
    navProfile.classList.toggle("active", !isUsers);
    navUsers.classList.toggle("active", isUsers);
    pageTitle.textContent = isUsers ? "用户管理" : "个人中心";
    if (isUsers && !usersLoaded) {
      usersLoaded = true;
      loadUsers();
    }
  }

  async function loadUsers() {
    if (!currentUser || !currentUser.is_admin) return;
    const q = document.getElementById("userQuery").value.trim();
    const params = new URLSearchParams({ page: String(page), per_page: "20" });
    if (q) params.set("q", q);
    tbody.innerHTML = '<tr><td colspan="7" class="admin-empty">加载中…</td></tr>';
    const res = await fetch("/api/admin/users?" + params.toString());
    const data = await res.json();
    if (!data.ok) {
      tbody.innerHTML =
        '<tr><td colspan="7" class="admin-empty">' +
        escapeHtml(data.error || "加载失败") +
        "</td></tr>";
      return;
    }
    if (!data.items || !data.items.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="admin-empty">暂无用户</td></tr>';
      pager.innerHTML = "";
      return;
    }
    tbody.innerHTML = data.items
      .map((u) => {
        const roleCls = u.is_admin ? "admin" : "user";
        const roleText = u.is_admin ? "管理员" : "普通用户";
        const statusCls = u.is_active ? "on" : "off";
        const statusText = u.is_active ? "启用" : "停用";
        const payload = encodeURIComponent(JSON.stringify(u));
        return (
          "<tr>" +
          "<td>" +
          u.id +
          "</td>" +
          "<td>" +
          escapeHtml(u.username) +
          "</td>" +
          "<td>" +
          escapeHtml(u.display_name) +
          "</td>" +
          '<td><span class="admin-role ' +
          roleCls +
          '">' +
          roleText +
          "</span></td>" +
          '<td><span class="admin-status ' +
          statusCls +
          '">' +
          statusText +
          "</span></td>" +
          "<td>" +
          escapeHtml(u.last_login_at || "—") +
          "</td>" +
          '<td class="admin-actions">' +
          '<button type="button" class="admin-btn" data-edit-user="' +
          payload +
          '">编辑</button>' +
          '<button type="button" class="admin-btn danger" data-toggle="' +
          u.id +
          '" data-active="' +
          (u.is_active ? "1" : "0") +
          '">' +
          (u.is_active ? "停用" : "启用") +
          "</button>" +
          "</td>" +
          "</tr>"
        );
      })
      .join("");

    const totalPages = data.total_pages || 1;
    pager.innerHTML =
      "<span>共 " +
      data.total +
      " 人 · 第 " +
      data.page +
      " / " +
      totalPages +
      " 页</span>" +
      '<button type="button" class="admin-btn" id="btnPrevPage"' +
      (page <= 1 ? " disabled" : "") +
      ">上一页</button>" +
      '<button type="button" class="admin-btn" id="btnNextPage"' +
      (page >= totalPages ? " disabled" : "") +
      ">下一页</button>";

    const prev = document.getElementById("btnPrevPage");
    const next = document.getElementById("btnNextPage");
    if (prev)
      prev.onclick = () => {
        page = Math.max(1, page - 1);
        loadUsers();
      };
    if (next)
      next.onclick = () => {
        page += 1;
        loadUsers();
      };
  }

  function openCreate() {
    mode = "create";
    document.getElementById("dialogTitle").textContent = "新建用户";
    document.getElementById("editUserId").value = "";
    document.getElementById("formUsername").value = "";
    document.getElementById("formUsername").disabled = false;
    document.getElementById("formDisplay").value = "";
    document.getElementById("formPassword").value = "";
    document.getElementById("formPassword").required = true;
    document.getElementById("pwdLabel").textContent = "密码";
    document.getElementById("formRole").value = "user";
    document.getElementById("activeRow").hidden = true;
    showDialogError("");
    dialog.showModal();
  }

  function openEdit(user) {
    mode = "edit";
    document.getElementById("dialogTitle").textContent = "编辑用户";
    document.getElementById("editUserId").value = String(user.id);
    document.getElementById("formUsername").value = user.username;
    document.getElementById("formUsername").disabled = true;
    document.getElementById("formDisplay").value = user.display_name || "";
    document.getElementById("formPassword").value = "";
    document.getElementById("formPassword").required = false;
    document.getElementById("pwdLabel").textContent = "新密码（留空不改）";
    document.getElementById("formRole").value = user.role || "user";
    document.getElementById("formActive").checked = !!user.is_active;
    document.getElementById("activeRow").hidden = false;
    showDialogError("");
    dialog.showModal();
  }

  function bindAdminUserCrud() {
    document.getElementById("btnOpenCreate").onclick = openCreate;
    document.getElementById("btnCancelDialog").onclick = () => dialog.close();
    document.getElementById("searchForm").onsubmit = (e) => {
      e.preventDefault();
      page = 1;
      loadUsers();
    };

    tbody.addEventListener("click", async (e) => {
      const editBtn = e.target.closest("[data-edit-user]");
      const toggleBtn = e.target.closest("[data-toggle]");
      if (editBtn) {
        try {
          const found = JSON.parse(
            decodeURIComponent(editBtn.getAttribute("data-edit-user") || "")
          );
          openEdit(found);
        } catch (_) {
          alert("无法打开编辑");
        }
        return;
      }
      if (toggleBtn) {
        const id = toggleBtn.getAttribute("data-toggle");
        const active = toggleBtn.getAttribute("data-active") === "1";
        const res = await fetch("/api/admin/users/" + id, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ is_active: !active }),
        });
        const data = await res.json();
        if (!data.ok) alert(data.error || "操作失败");
        loadUsers();
      }
    });

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      showDialogError("");
      const username = document.getElementById("formUsername").value.trim();
      const display_name = document.getElementById("formDisplay").value.trim();
      const password = document.getElementById("formPassword").value;
      const role = document.getElementById("formRole").value;
      let res;
      if (mode === "create") {
        res = await fetch("/api/admin/users", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username, display_name, password, role }),
        });
      } else {
        const id = document.getElementById("editUserId").value;
        const body = {
          display_name,
          role,
          is_active: document.getElementById("formActive").checked,
        };
        if (password) body.password = password;
        res = await fetch("/api/admin/users/" + id, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
      }
      const data = await res.json();
      if (!data.ok) {
        showDialogError(data.error || "保存失败");
        return;
      }
      dialog.close();
      loadUsers();
    });
  }

  function bindPasswordForm() {
    const pwdError = document.getElementById("pwdError");
    const pwdOk = document.getElementById("pwdOk");
    document.getElementById("pwdForm").addEventListener("submit", async (e) => {
      e.preventDefault();
      pwdError.hidden = true;
      pwdOk.hidden = true;
      const old_password = document.getElementById("pwdOld").value;
      const new_password = document.getElementById("pwdNew").value;
      const new2 = document.getElementById("pwdNew2").value;
      if (new_password !== new2) {
        pwdError.hidden = false;
        pwdError.textContent = "两次输入的新密码不一致";
        return;
      }
      const btn = document.getElementById("btnSavePwd");
      btn.disabled = true;
      try {
        const res = await fetch("/api/auth/change-password", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ old_password, new_password }),
        });
        const data = await res.json();
        if (!data.ok) {
          pwdError.hidden = false;
          pwdError.textContent = data.error || "修改失败";
          return;
        }
        document.getElementById("pwdOld").value = "";
        document.getElementById("pwdNew").value = "";
        document.getElementById("pwdNew2").value = "";
        pwdOk.hidden = false;
      } catch (_) {
        pwdError.hidden = false;
        pwdError.textContent = "网络错误，请稍后重试";
      } finally {
        btn.disabled = false;
      }
    });
  }

  async function bootstrap() {
    const user = await Auth.requireAuth();
    if (!user) return;
    currentUser = user;

    const roleText = user.is_admin ? "系统管理员" : "普通用户";
    const who = document.getElementById("adminWho");
    const avatar = document.getElementById("adminAvatar");
    const roleLabel = document.getElementById("adminRoleLabel");
    const menuRole = document.getElementById("adminMenuRole");
    if (who) who.textContent = user.display_name || user.username;
    if (roleLabel) roleLabel.textContent = roleText;
    if (menuRole) menuRole.textContent = roleText;
    if (avatar) {
      const label = (user.display_name || user.username || "?").trim();
      avatar.textContent = label.slice(0, 1).toUpperCase();
    }

    Auth.bindUserMenu({
      menuRootId: "adminUserMenu",
      triggerId: "adminUserTrigger",
      panelId: "adminUserPanel",
      logoutId: "btnLogout",
    });
    Auth.bindSidebarCollapse({
      shellId: "adminLayout",
      buttonId: "btnToggleSidebar",
      labelId: "sidebarCollapseText",
      storageKey: "zkbz_admin_sidebar_collapsed",
    });

    fillProfile(user);
    bindPasswordForm();

    navProfile.addEventListener("click", () => switchPanel("profile"));
    if (user.is_admin) {
      navUsers.hidden = false;
      bindAdminUserCrud();
      navUsers.addEventListener("click", () => switchPanel("users"));
      const hash = (location.hash || "").replace("#", "");
      switchPanel(hash === "users" ? "users" : "users");
    } else {
      switchPanel("profile");
    }
  }

  bootstrap();
})();
