(function () {
  "use strict";

  const { api, escapeHtml, formatDate, showToast } = window.App;
  const TYPE_LABELS = window.QuestionForm.TYPE_LABELS;
  const QUESTION_ID = window.location.pathname.split("/")[2];

  const titleNode = document.getElementById("questionTitle");
  const metaNode = document.getElementById("questionMeta");
  const contentNode = document.getElementById("currentContent");
  const versionNode = document.getElementById("versionList");
  const usageNode = document.getElementById("usageList");
  const shareNode = document.getElementById("shareList");
  const versionPanel = document.getElementById("versionPanel");
  const versionError = document.getElementById("versionError");

  let detail = null;
  let versionForm = null;

  function renderContent(content) {
    const rows = [];
    rows.push(`<p><strong>${escapeHtml(content.title)}</strong></p>`);
    if (content.description) {
      rows.push(`<p class="muted">${escapeHtml(content.description)}</p>`);
    }
    rows.push(
      `<p class="muted">${TYPE_LABELS[content.type] || content.type} · ${content.required ? "必答" : "选答"}</p>`
    );
    if (content.options) {
      rows.push(
        `<ul class="qv-plain">${content.options
          .map((option) => `<li>${escapeHtml(option.label)} <code>${escapeHtml(option.option_id)}</code></li>`)
          .join("")}</ul>`
      );
    }
    if (content.validation) {
      rows.push(
        `<pre class="qv-code">${escapeHtml(JSON.stringify(content.validation, null, 2))}</pre>`
      );
    }
    return rows.join("");
  }

  function renderVersions() {
    versionNode.innerHTML = detail.versions
      .slice()
      .sort((a, b) => b.version_no - a.version_no)
      .map((version) => {
        const isLatest = version.version_no === detail.latest_version_no;
        const restored = version.restored_from_version_id
          ? '<span class="pill">恢复自旧版本</span>'
          : "";
        return `
          <div class="qv-version-row">
            <div>
              <strong>v${version.version_no}</strong>
              ${isLatest ? '<span class="pill good">当前</span>' : ""}
              ${restored}
              <span class="muted">${formatDate(version.created_at, true)}</span>
              <div class="muted">${escapeHtml(version.content.title)}</div>
              <code class="qv-hash">${escapeHtml(version.content_hash.slice(0, 16))}…</code>
            </div>
            <div class="qv-actions">
              ${isLatest ? "" : `<button class="btn ghost small" data-restore="${version.version_no}" type="button">恢复此版本</button>`}
            </div>
          </div>`;
      })
      .join("");
    versionNode.querySelectorAll("[data-restore]").forEach((button) => {
      button.addEventListener("click", () => restore(button.dataset.restore));
    });
  }

  function renderUsages(usages) {
    if (!usages.length) {
      usageNode.innerHTML = '<p class="muted">还没有问卷使用这道题。</p>';
      return;
    }
    usageNode.innerHTML = `
      <table class="qv-table">
        <thead><tr><th>问卷</th><th>版本</th><th>题目实例</th><th>题目版本</th><th>状态</th></tr></thead>
        <tbody>${usages
          .map(
            (item) => `
          <tr>
            <td><a href="/surveys/${item.survey_id}/stats">${escapeHtml(item.survey_title)}</a></td>
            <td>v${item.survey_version_no}</td>
            <td><code>${escapeHtml(item.instance_question_id)}</code></td>
            <td>v${item.question_version_no}</td>
            <td>${item.is_published ? '<span class="pill good">已发布</span>' : '<span class="pill">草稿</span>'}</td>
          </tr>`
          )
          .join("")}</tbody>
      </table>`;
  }

  function renderShares(shares) {
    if (!shares.length) {
      shareNode.innerHTML = '<p class="muted">尚未共享给任何人。</p>';
      return;
    }
    shareNode.innerHTML = shares
      .map(
        (share) => `
        <div class="qv-share-row">
          <span>${escapeHtml(share.grantee_username)} · ${share.permission}</span>
          <button class="btn ghost small" data-revoke="${share.grantee_id}" type="button">撤销</button>
        </div>`
      )
      .join("");
    shareNode.querySelectorAll("[data-revoke]").forEach((button) => {
      button.addEventListener("click", async () => {
        try {
          await api(`/api/questions/${QUESTION_ID}/shares/${button.dataset.revoke}`, { method: "DELETE" });
          showToast("已撤销共享", "success");
          await load();
        } catch (error) {
          showToast(error.message, "error");
        }
      });
    });
  }

  async function load() {
    detail = await api(`/api/questions/${QUESTION_ID}`);
    titleNode.textContent = detail.title;
    metaNode.textContent = `${TYPE_LABELS[detail.type] || detail.type} · ${detail.visibility} · 最新 v${detail.latest_version_no} · 被 ${detail.usage_count} 个问卷版本使用`;
    contentNode.innerHTML = renderContent(detail.latest_version.content);
    renderVersions();
    renderShares(detail.shares || []);
    renderUsages(await api(`/api/questions/${QUESTION_ID}/usages`));
    document.getElementById("statsLink").href = `/questions/${QUESTION_ID}/stats`;
  }

  async function restore(versionNo) {
    try {
      await api(`/api/questions/${QUESTION_ID}/versions/${versionNo}/restore`, { method: "POST" });
      showToast(`已从 v${versionNo} 生成新版本`, "success");
      await load();
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  document.getElementById("newVersionButton").addEventListener("click", () => {
    versionPanel.classList.remove("hidden");
    versionError.classList.add("hidden");
    versionForm = window.QuestionForm.buildForm(
      document.getElementById("versionFormBody"),
      { content: detail.latest_version.content }
    );
    versionPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  document.getElementById("cancelVersion").addEventListener("click", () => {
    versionPanel.classList.add("hidden");
  });

  document.getElementById("versionForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    versionError.classList.add("hidden");
    try {
      const content = versionForm.read();
      await api(`/api/questions/${QUESTION_ID}/versions`, {
        method: "POST",
        body: { content },
      });
      showToast("已生成新版本", "success");
      versionPanel.classList.add("hidden");
      await load();
    } catch (error) {
      versionError.textContent = error.message;
      versionError.classList.remove("hidden");
    }
  });

  document.getElementById("shareButton").addEventListener("click", async () => {
    const username = document.getElementById("shareUsername").value.trim();
    if (!username) {
      showToast("请填写用户名", "error");
      return;
    }
    try {
      await api(`/api/questions/${QUESTION_ID}/shares`, {
        method: "POST",
        body: {
          grantee_username: username,
          permission: document.getElementById("sharePermission").value,
        },
      });
      showToast("已共享", "success");
      document.getElementById("shareUsername").value = "";
      await load();
    } catch (error) {
      showToast(error.message, "error");
    }
  });

  document.getElementById("forkButton").addEventListener("click", async () => {
    const title = window.prompt("新题目名称（留空则沿用原标题）", detail.title + "（副本）");
    if (title === null) return;
    try {
      const created = await api(`/api/questions/${QUESTION_ID}/fork`, {
        method: "POST",
        body: title ? { title } : {},
      });
      showToast("已派生新题目", "success");
      window.location.href = `/questions/${created.id}`;
    } catch (error) {
      showToast(error.message, "error");
    }
  });

  document.getElementById("deleteButton").addEventListener("click", async () => {
    if (!window.confirm("删除后题目将不可再用，且无法恢复。确认删除？")) return;
    try {
      await api(`/api/questions/${QUESTION_ID}`, { method: "DELETE" });
      showToast("题目已删除", "success");
      window.location.href = "/questions";
    } catch (error) {
      showToast(error.message, "error");
    }
  });

  load().catch((error) => showToast(error.message, "error"));
})();
