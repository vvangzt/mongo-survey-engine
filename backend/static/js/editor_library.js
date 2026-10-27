(function () {
  "use strict";

  // Additive editor integration: insert a shared-library question into the
  // draft, and refresh an already-inserted question to its newest version.
  // The main editor script stays untouched apart from two markup hooks.

  const { api, escapeHtml, showToast } = window.App;
  const SURVEY_ID = window.SURVEY_ID;
  const TYPE_LABELS = {
    single_choice: "单选题",
    multi_choice: "多选题",
    text: "文本题",
    number: "数字题",
  };

  const modal = document.getElementById("libraryModal");
  const select = document.getElementById("libraryQuestionSelect");
  const scope = document.getElementById("libraryScope");
  const errorNode = document.getElementById("libraryError");

  async function loadQuestions() {
    errorNode.classList.add("hidden");
    select.innerHTML = '<option value="">加载中…</option>';
    try {
      const items = await api(
        `/api/questions?scope=${scope.value}&limit=200`
      );
      if (!items.length) {
        select.innerHTML = '<option value="">这个范围下还没有题目</option>';
        return;
      }
      select.innerHTML = items
        .map(
          (item) =>
            `<option value="${item.latest_version.id}">${escapeHtml(item.title)} · ${TYPE_LABELS[item.type] || item.type} · v${item.latest_version_no}</option>`
        )
        .join("");
    } catch (error) {
      select.innerHTML = '<option value="">加载失败</option>';
      errorNode.textContent = error.message;
      errorNode.classList.remove("hidden");
    }
  }

  function closeModal() {
    modal.classList.add("hidden");
  }

  document.addEventListener("click", async (event) => {
    if (event.target.closest("[data-close-library]")) {
      closeModal();
      return;
    }

    if (event.target.closest("#libraryPickButton")) {
      modal.classList.remove("hidden");
      await loadQuestions();
      return;
    }

    const refresh = event.target.closest("[data-refresh-question]");
    if (refresh) {
      const instanceId = refresh.dataset.refreshQuestion;
      refresh.disabled = true;
      try {
        const payload = await api(
          `/api/surveys/${SURVEY_ID}/questions/${encodeURIComponent(instanceId)}/refresh`,
          { method: "POST" }
        );
        showToast(`已更新到 v${payload.question.question_ref ? "最新" : ""}版本`, "success");
        window.location.reload();
      } catch (error) {
        refresh.disabled = false;
        showToast(error.message, "error");
      }
    }
  });

  document.getElementById("libraryScope").addEventListener("change", loadQuestions);

  document.getElementById("libraryInsertButton").addEventListener("click", async () => {
    const versionId = select.value;
    if (!versionId) {
      showToast("请先选择一个题目", "error");
      return;
    }
    try {
      await api(`/api/surveys/${SURVEY_ID}/questions/from-library`, {
        method: "POST",
        body: { question_version_id: versionId },
      });
      closeModal();
      showToast("已插入并保存到草稿", "success");
      window.location.reload();
    } catch (error) {
      errorNode.textContent = error.message;
      errorNode.classList.remove("hidden");
    }
  });
})();
