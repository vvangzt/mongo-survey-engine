(function () {
  "use strict";

  const { api, escapeHtml, formatDate, showToast } = window.App;

  const listNode = document.getElementById("libraryList");
  const emptyNode = document.getElementById("libraryEmpty");
  const panel = document.getElementById("createPanel");
  const errorNode = document.getElementById("createError");

  function card(item) {
    return `
      <article class="card survey-card">
        <div class="survey-card-head">
          <div>
            <div class="qv-tags">
              <span class="pill">${item.visibility === "public" ? "公开" : "私有"}</span>
              ${item.is_owner ? '<span class="pill good">我的</span>' : ""}
            </div>
            <h2><a href="/libraries/${item.id}">${escapeHtml(item.name)}</a></h2>
            <p class="muted">${escapeHtml(item.description || "没有说明")}</p>
          </div>
        </div>
        <p class="muted">${item.item_count} 道题 · 更新于 ${formatDate(item.updated_at)}</p>
      </article>`;
  }

  async function load() {
    try {
      const items = await api("/api/libraries");
      listNode.innerHTML = items.map(card).join("");
      emptyNode.classList.toggle("hidden", items.length > 0);
    } catch (error) {
      showToast(error.message, "error");
    }
  }

  document.getElementById("openCreate").addEventListener("click", () => {
    panel.classList.remove("hidden");
    errorNode.classList.add("hidden");
  });
  document.getElementById("cancelCreate").addEventListener("click", () => {
    panel.classList.add("hidden");
  });

  document.getElementById("createForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    errorNode.classList.add("hidden");
    try {
      const created = await api("/api/libraries", {
        method: "POST",
        body: {
          name: document.getElementById("libraryName").value.trim(),
          description: document.getElementById("libraryDescription").value.trim(),
          visibility: document.getElementById("libraryVisibility").value,
        },
      });
      window.location.href = `/libraries/${created.id}`;
    } catch (error) {
      errorNode.textContent = error.message;
      errorNode.classList.remove("hidden");
    }
  });

  load();
})();
