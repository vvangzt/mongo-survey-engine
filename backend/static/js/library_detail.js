(function () {
  "use strict";

  const { api, escapeHtml, formatDate, showToast } = window.App;
  const LIBRARY_ID = window.location.pathname.split("/")[2];
  const TYPE_LABELS = {
    single_choice: "单选题",
    multi_choice: "多选题",
    text: "文本题",
    number: "数字题",
  };

  const itemNode = document.getElementById("itemList");
  const emptyNode = document.getElementById("itemEmpty");
  const selectNode = document.getElementById("questionSelect");
  const errorNode = document.getElementById("addError");

  async function loadSelect(selected) {
    const questions = await api("/api/questions?scope=usable&limit=200");
    selectNode.innerHTML = questions
      .map(
        (item) =>
          `<option value="${item.id}">${escapeHtml(item.title)} · ${TYPE_LABELS[item.type] || item.type}</option>`
      )
      .join("");
    if (selected) {
      selectNode.value = selected;
    }
  }

  async function load() {
    const library = await api(`/api/libraries/${LIBRARY_ID}`);
    document.getElementById("libraryName").textContent = library.name;
    document.getElementById("libraryMeta").textContent =
      `${library.visibility === "public" ? "公开题库" : "私有题库"} · ${library.item_count} 道题 · 更新于 ${formatDate(library.updated_at)}`;

    itemNode.innerHTML = library.items
      .map(
        (item) => `
        <div class="qv-version-row">
          <div>
            <strong>${escapeHtml(item.title)}</strong>
            <span class="pill">${TYPE_LABELS[item.type] || item.type}</span>
            <span class="pill">v${item.latest_version_no}</span>
            ${item.note ? `<div class="muted">${escapeHtml(item.note)}</div>` : ""}
            ${item.tags.length ? `<div class="muted">${item.tags.map((tag) => `#${escapeHtml(tag)}`).join(" ")}</div>` : ""}
          </div>
          <div class="qv-actions">
            <a class="btn ghost small" href="/questions/${item.entity_id}">查看题目</a>
            <button class="btn ghost small" data-remove="${item.entity_id}" type="button">移出</button>
          </div>
        </div>`
      )
      .join("");
    emptyNode.classList.toggle("hidden", library.items.length > 0);

    itemNode.querySelectorAll("[data-remove]").forEach((button) => {
      button.addEventListener("click", async () => {
        try {
          await api(`/api/libraries/${LIBRARY_ID}/items/${button.dataset.remove}`, {
            method: "DELETE",
          });
          showToast("已移出题库", "success");
          await load();
        } catch (error) {
          showToast(error.message, "error");
        }
      });
    });
  }

  document.getElementById("addButton").addEventListener("click", async () => {
    errorNode.classList.add("hidden");
    const entityId = selectNode.value;
    if (!entityId) {
      showToast("请选择一道题目", "error");
      return;
    }
    try {
      await api(`/api/libraries/${LIBRARY_ID}/items`, {
        method: "POST",
        body: {
          entity_id: entityId,
          note: document.getElementById("itemNote").value.trim() || null,
          tags: [],
        },
      });
      document.getElementById("itemNote").value = "";
      showToast("已加入题库", "success");
      await load();
    } catch (error) {
      errorNode.textContent = error.message;
      errorNode.classList.remove("hidden");
    }
  });

  document.getElementById("deleteButton").addEventListener("click", async () => {
    if (!window.confirm("删除题库只移除条目，题目本身不会被删除。确认？")) return;
    try {
      await api(`/api/libraries/${LIBRARY_ID}`, { method: "DELETE" });
      window.location.href = "/libraries";
    } catch (error) {
      showToast(error.message, "error");
    }
  });

  (async () => {
    try {
      await loadSelect();
      await load();
    } catch (error) {
      showToast(error.message, "error");
    }
  })();
})();
