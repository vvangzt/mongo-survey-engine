(function () {
  "use strict";

  class ApiError extends Error {
    constructor(status, detail) {
      const message = ApiError.describe(detail);
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.detail = detail;
    }

    static describe(detail) {
      if (!detail) return "请求失败，请稍后重试";
      if (typeof detail === "string") return detail;
      if (typeof detail.message === "string") return detail.message;
      if (typeof detail.detail === "string") return detail.detail;
      if (Array.isArray(detail)) {
        return detail.map((item) => item.msg || "参数错误").join("；");
      }
      return "请求失败，请检查输入";
    }
  }

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    let body = options.body;
    if (body !== undefined && body !== null && typeof body !== "string") {
      headers.set("Content-Type", "application/json");
      body = JSON.stringify(body);
    }
    const response = await fetch(path, {
      ...options,
      headers,
      body,
      credentials: "same-origin",
    });
    if (response.status === 204) return null;
    const contentType = response.headers.get("content-type") || "";
    let payload = null;
    if (contentType.includes("application/json")) {
      payload = await response.json();
    } else {
      const text = await response.text();
      payload = text || null;
    }
    if (!response.ok) {
      const detail = payload && typeof payload === "object" && "detail" in payload
        ? payload.detail
        : payload;
      throw new ApiError(response.status, detail);
    }
    return payload;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function showToast(message, type = "info", timeout = 3200) {
    const stack = document.getElementById("toastStack");
    if (!stack) return;
    const node = document.createElement("div");
    node.className = `toast ${type}`;
    node.textContent = message;
    stack.appendChild(node);
    window.setTimeout(() => node.remove(), timeout);
  }

  function formatDate(value, withTime = false) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat("zh-CN", {
      year: "numeric",
      month: "short",
      day: "numeric",
      ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
    }).format(date);
  }

  function statusLabel(status) {
    return {
      draft: "草稿",
      published: "已发布",
      closed: "已关闭",
    }[status] || status;
  }

  function initials(name) {
    const value = String(name || "?").trim();
    return value ? value[0].toUpperCase() : "?";
  }

  function randomId(prefix, length = 12) {
    const bytes = new Uint8Array(Math.ceil(length / 2));
    crypto.getRandomValues(bytes);
    const value = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
    return `${prefix}${value.slice(0, length)}`;
  }

  async function copyText(value) {
    try {
      await navigator.clipboard.writeText(value);
      showToast("链接已复制", "success");
    } catch (error) {
      window.prompt("复制以下链接：", value);
    }
  }

  function loginUrl(next) {
    return `/login?next=${encodeURIComponent(next || "/dashboard")}`;
  }

  async function logout() {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } finally {
      window.location.href = "/login";
    }
  }

  function bindLogout() {
    const button = document.getElementById("logoutButton");
    if (button) {
      button.addEventListener("click", logout);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindLogout);
  } else {
    bindLogout();
  }

  window.App = {
    ApiError,
    api,
    copyText,
    escapeHtml,
    formatDate,
    initials,
    loginUrl,
    logout,
    randomId,
    showToast,
    statusLabel,
  };
})();
