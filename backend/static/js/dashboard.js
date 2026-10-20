(function () {
  "use strict";

  const listNode = document.getElementById("surveyList");
  const emptyNode = document.getElementById("surveyEmpty");
  const loadingNode = document.getElementById("surveyLoading");
  const createModal = document.getElementById("createModal");
  const createForm = document.getElementById("createForm");
  const createError = document.getElementById("createError");
  const createButton = document.getElementById("createButton");
  const settingsModal = document.getElementById("settingsModal");
  const settingsForm = document.getElementById("settingsForm");
  const settingsError = document.getElementById("settingsError");
  const settingsButton = document.getElementById("settingsButton");

  let surveys = [];

  function statusClass(status) {
    if (status === "published") return "published";
    if (status === "closed") return "closed";
    return "draft";
  }

  function openCreate() {
    createError.classList.add("hidden");
    createModal.classList.remove("hidden");
    document.getElementById("title").focus();
  }

  function closeCreate() {
    createModal.classList.add("hidden");
    createForm.reset();
    document.getElementById("allow_anonymous").checked = true;
    document.getElementById("allow_multiple_responses").checked = true;
  }

  function localDatetime(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    const pad = (n) => String(n).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  function openSettings(survey) {
    settingsError.classList.add("hidden");
    document.getElementById("settingsSurveyId").value = survey.id;
    document.getElementById("settingsTitleInput").value = survey.title;
    document.getElementById("settingsDescription").value = survey.description || "";
    document.getElementById("settingsClosesAt").value = localDatetime(survey.closes_at);
    document.getElementById("settingsAnonymous").checked = Boolean(survey.allow_anonymous);
    document.getElementById("settingsMultiple").checked = Boolean(survey.allow_multiple_responses);
    settingsModal.classList.remove("hidden");
    document.getElementById("settingsTitleInput").focus();
  }

  function closeSettings() {
    settingsModal.classList.add("hidden");
    settingsForm.reset();
  }

  function renderMetrics() {
    const draft = surveys.filter((item) => item.status === "draft").length;
    const live = surveys.filter((item) => item.status !== "draft").length;
    document.getElementById("metricTotal").textContent = surveys.length;
    document.getElementById("metricDraft").textContent = draft;
    document.getElementById("metricLive").textContent = live;
  }

  function renderSurveys() {
    renderMetrics();
    loadingNode.classList.add("hidden");
    if (!surveys.length) {
      emptyNode.classList.remove("hidden");
      listNode.classList.add("hidden");
      return;
    }
    emptyNode.classList.add("hidden");
    listNode.classList.remove("hidden");
    listNode.innerHTML = surveys
      .map((survey) => {
        const isDraft = survey.status === "draft";
        const publicLink = `${window.location.origin}/survey/${survey.slug}`;
        return `
          <article class="card survey-card" data-survey-id="${App.escapeHtml(survey.id)}">
            <div class="survey-card-top">
              <div>
                <span class="badge ${statusClass(survey.status)}">${App.escapeHtml(App.statusLabel(survey.status))}</span>
                <h2>${App.escapeHtml(survey.title)}</h2>
                <div class="slug mono">/survey/${App.escapeHtml(survey.slug)}</div>
              </div>
              <span class="subtle small">${App.formatDate(survey.updated_at)}</span>
            </div>
            <p class="description">${App.escapeHtml(survey.description || "暂无问卷说明")}</p>
            <div class="survey-meta">
              <span>${survey.allow_anonymous ? "允许匿名" : "需要登录"}</span>
              <span>${survey.allow_multiple_responses ? "可多次填写" : "仅限一次"}</span>
              ${survey.closes_at ? `<span>截止 ${App.formatDate(survey.closes_at, true)}</span>` : "<span>无截止时间</span>"}
            </div>
            <div class="actions" style="margin-top: 16px">
              <a class="btn secondary small" href="/surveys/${survey.id}/edit">${isDraft ? "继续编辑" : "查看题目"}</a>
              ${isDraft ? "" : `<a class="btn ghost small" href="/surveys/${survey.id}/stats">查看统计</a>`}
              ${isDraft ? "" : `<button class="btn ghost small" data-copy="${App.escapeHtml(publicLink)}" type="button">复制填写链接</button>`}
              ${survey.status === "published" ? `<button class="btn ghost small" data-new-version="${survey.id}" type="button">创建新版本</button>` : ""}
              ${survey.status === "published" ? `<button class="btn ghost small" data-settings-survey="${survey.id}" type="button">运营设置</button>` : ""}
              ${survey.status === "published" ? `<button class="btn danger small" data-close-survey="${survey.id}" type="button">关闭问卷</button>` : ""}
            </div>
          </article>
        `;
      })
      .join("");
  }

  async function loadSurveys() {
    try {
      surveys = await App.api("/api/surveys");
      renderSurveys();
    } catch (error) {
      loadingNode.innerHTML = `<div class="card empty"><h2>无法加载问卷</h2><p>${App.escapeHtml(error.message)}</p></div>`;
    }
  }

  document.getElementById("openCreate").addEventListener("click", openCreate);
  document.getElementById("emptyCreate").addEventListener("click", openCreate);
  document.querySelectorAll("[data-close-modal]").forEach((button) => {
    button.addEventListener("click", closeCreate);
  });
  createModal.addEventListener("click", (event) => {
    if (event.target === createModal) closeCreate();
  });

  createForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    createError.classList.add("hidden");
    createButton.disabled = true;
    createButton.textContent = "创建中…";
    const closesAt = document.getElementById("closes_at").value;
    try {
      const survey = await App.api("/api/surveys", {
        method: "POST",
        body: {
          title: document.getElementById("title").value.trim(),
          description: document.getElementById("description").value.trim(),
          allow_anonymous: document.getElementById("allow_anonymous").checked,
          allow_multiple_responses: document.getElementById("allow_multiple_responses").checked,
          closes_at: closesAt ? new Date(closesAt).toISOString() : null,
        },
      });
      window.location.href = `/surveys/${survey.id}/edit`;
    } catch (error) {
      createError.textContent = error.message;
      createError.classList.remove("hidden");
    } finally {
      createButton.disabled = false;
      createButton.textContent = "创建并编辑";
    }
  });

  listNode.addEventListener("click", async (event) => {
    const newVersionButton = event.target.closest("[data-new-version]");
    if (newVersionButton) {
      newVersionButton.disabled = true;
      try {
        await App.api(
          `/api/surveys/${newVersionButton.dataset.newVersion}/new-draft`,
          { method: "POST" }
        );
        window.location.href = `/surveys/${newVersionButton.dataset.newVersion}/edit`;
      } catch (error) {
        App.showToast(error.message, "error");
        newVersionButton.disabled = false;
      }
      return;
    }
    const settingsButtonNode = event.target.closest("[data-settings-survey]");
    if (settingsButtonNode) {
      const survey = surveys.find(
        (item) => item.id === settingsButtonNode.dataset.settingsSurvey
      );
      if (survey) openSettings(survey);
      return;
    }
    const copyButton = event.target.closest("[data-copy]");
    if (copyButton) {
      await App.copyText(copyButton.dataset.copy);
      return;
    }
    const closeButton = event.target.closest("[data-close-survey]");
    if (!closeButton) return;
    const survey = surveys.find((item) => item.id === closeButton.dataset.closeSurvey);
    if (!survey) return;
    if (!window.confirm(`关闭「${survey.title}」后将不再接受新答卷，确定继续吗？`)) return;
    closeButton.disabled = true;
    try {
      await App.api(`/api/surveys/${survey.id}/close`, { method: "POST" });
      App.showToast("问卷已关闭", "success");
      await loadSurveys();
    } catch (error) {
      App.showToast(error.message, "error");
      closeButton.disabled = false;
    }
  });

  document.querySelectorAll("[data-close-settings]").forEach((button) => {
    button.addEventListener("click", closeSettings);
  });
  settingsModal.addEventListener("click", (event) => {
    if (event.target === settingsModal) closeSettings();
  });
  settingsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    settingsError.classList.add("hidden");
    settingsButton.disabled = true;
    settingsButton.textContent = "保存中…";
    const surveyId = document.getElementById("settingsSurveyId").value;
    const closesAt = document.getElementById("settingsClosesAt").value;
    try {
      await App.api(`/api/surveys/${surveyId}`, {
        method: "PATCH",
        body: {
          title: document.getElementById("settingsTitleInput").value.trim(),
          description: document.getElementById("settingsDescription").value.trim(),
          allow_anonymous: document.getElementById("settingsAnonymous").checked,
          allow_multiple_responses: document.getElementById("settingsMultiple").checked,
          closes_at: closesAt ? new Date(closesAt).toISOString() : null,
        },
      });
      closeSettings();
      App.showToast("运营设置已更新", "success");
      await loadSurveys();
    } catch (error) {
      settingsError.textContent = error.message;
      settingsError.classList.remove("hidden");
    } finally {
      settingsButton.disabled = false;
      settingsButton.textContent = "保存设置";
    }
  });

  loadSurveys();
})();
