(function () {
  "use strict";

  const { api, escapeHtml, formatDate, showToast } = window.App;

  const listNode = document.getElementById("questionList");
  const emptyNode = document.getElementById("questionEmpty");
  const countNode = document.getElementById("listCount");
  const createPanel = document.getElementById("createPanel");
  const createError = document.getElementById("createError");
  const scopeFilter = document.getElementById("scopeFilter");
  const typeFilter = document.getElementById("typeFilter");
  const searchInput = document.getElementById("searchInput");
  const TYPE_LABELS = window.QuestionForm.TYPE_LABELS;

  let form = null;
  let searchTimer = null;

  function card(item) {
    const owner = item.is_owner
      ? '<span class="pill good">我的</span>'
      : `<span class="pill">${escapeHtml(item.owner_username || "协作者")}</span>`;
    return `
      <article class="card survey-card">
        <div class="survey-card-head">
          <div>
            <div class="qv-tags">
              <span class="pill">${TYPE_LABELS[item.type] || item.type}</span>
              ${owner}
              <span class="pill">v${item.latest_version_no}</span>
            </div>
            <h2><a href="/questions/${item.id}">${escapeHtml(item.title)}</a></h2>
          </div>
        </div>
        <p class="muted">${item.version_count} 个版本 · 更新于 ${formatDate(item.updated_at)}</p>
        <div class="qv-actions">
          <a class="btn secondary small" href="/questions/${item.id}">版本历史</a>
          <a class="btn ghost small" href="/questions/${item.id}/stats">跨问卷统计</a>
        </div>
      </article>`;
  }

  async function load() {
    const params = new URLSearchParams({
      scope: scopeFilter.value,
      limit: "200",
    });
    if (typeFilter.value) params.set("type", typeFilter.value);
    if (searchInput.value.trim()) params.set("q", searchInput.value.trim());
    try {
      const items = await api(`/api/questions?${params.toString()}`);
      listNode.innerHTML = items.map(card).join("");
      emptyNode.classList.toggle("hidden", items.length > 0);
      countNode.textContent = items.length ? `共 ${items.length} 道题` : "";
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  function openCreate() {
    createPanel.classList.remove("hidden");
    createError.classList.add("hidden");
    form = window.QuestionForm.buildForm(
      document.getElementById("questionForm"),
      { content: { type: "number", title: "", required: true, validation: { integer: true, min: 0, max: 120 } } }
    );
  }

  document.getElementById("openCreate").addEventListener("click", openCreate);
  document.getElementById("emptyCreate").addEventListener("click", openCreate);
  document.getElementById("cancelCreate").addEventListener("click", () => {
    createPanel.classList.add("hidden");
  });

  document.getElementById("createForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    createError.classList.add("hidden");
    try {
      const content = form.read();
      const created = await api("/api/questions", {
        method: "POST",
        body: { content, visibility: "private" },
      });
      showToast("题目已保存", "success");
      createPanel.classList.add("hidden");
      window.location.href = `/questions/${created.id}`;
    } catch (error) {
      createError.textContent = error.message;
      createError.classList.remove("hidden");
    }
  });

  scopeFilter.addEventListener("change", load);
  typeFilter.addEventListener("change", load);
  searchInput.addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(load, 250);
  });

  load();
})();
