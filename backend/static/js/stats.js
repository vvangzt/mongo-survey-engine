(function () {
  "use strict";

  const SURVEY_ID = window.SURVEY_ID;
  const TYPE_LABELS = {
    single_choice: "单选题",
    multi_choice: "多选题",
    text: "文本题",
    number: "数字题",
  };
  const state = {
    overview: null,
    textPages: new Map(),
  };

  const loading = document.getElementById("statsLoading");
  const content = document.getElementById("statsContent");
  const errorNode = document.getElementById("statsError");
  const errorText = document.getElementById("statsErrorText");
  const container = document.getElementById("questionStats");

  function percent(value) {
    return `${Number(value || 0).toFixed(value % 1 === 0 ? 0 : 2)}%`;
  }

  function average(value) {
    if (value == null) return "—";
    return Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
  }

  function renderBars(question) {
    return `
      <div class="bar-list">
        ${question.option_counts.map((option) => `
          <div class="bar-row">
            <span class="bar-label" title="${App.escapeHtml(option.label)}">${App.escapeHtml(option.label)}</span>
            <div class="bar-track">
              <div class="bar-fill" style="width:${Math.max(0, Math.min(100, option.percentage))}%"></div>
            </div>
            <span class="bar-value">${option.count} · ${percent(option.percentage)}</span>
          </div>`).join("")}
      </div>
      ${question.type === "multi_choice"
        ? `<p class="stat-note">多选题按选择频次统计，各选项比例之和可能超过 100%。本题共有 ${question.answered_count} 人作答。</p>`
        : `<p class="stat-note">本题共有 ${question.answered_count} 人作答。</p>`}
    `;
  }

  function renderNumbers(question) {
    return `
      <div class="summary-grid" style="grid-template-columns:repeat(3,minmax(0,1fr));margin-bottom:0">
        <div class="card metric" style="box-shadow:none">
          <div class="metric-label">平均值</div>
          <div class="metric-value">${average(question.average)}</div>
        </div>
        <div class="card metric" style="box-shadow:none">
          <div class="metric-label">最小值</div>
          <div class="metric-value">${question.min ?? "—"}</div>
        </div>
        <div class="card metric" style="box-shadow:none">
          <div class="metric-label">最大值</div>
          <div class="metric-value">${question.max ?? "—"}</div>
        </div>
      </div>
      <p class="stat-note">本题共有 ${question.answered_count} 人作答，平均值按有效数字答案计算。</p>
    `;
  }

  function renderText(question) {
    return `
      <div id="textStats-${question.question_id}">
        <p class="small muted" style="margin-bottom:12px">本题共有 ${question.answered_count} 条文本回答。文本内容按页加载，保护数据展示性能。</p>
        <button class="btn secondary small" type="button"
          data-load-text="${question.question_id}" data-page="1">加载文本回答</button>
        <div class="text-answers" style="margin-top:14px"></div>
      </div>
    `;
  }

  function renderQuestion(question, index) {
    let body = "";
    if (question.type === "single_choice" || question.type === "multi_choice") {
      body = renderBars(question);
    } else if (question.type === "number") {
      body = renderNumbers(question);
    } else {
      body = renderText(question);
    }
    return `
      <section class="card stats-q" data-question-id="${App.escapeHtml(question.question_id)}">
        <div class="stats-q-head">
          <div>
            <div class="eyebrow" style="margin-bottom:4px">${App.escapeHtml(TYPE_LABELS[question.type] || question.type)}</div>
            <h3>${index + 1}. ${App.escapeHtml(question.title)}</h3>
            <span class="small subtle">${question.required ? "必答题" : "选答题"} · 作答率 ${percent(question.response_rate * 100)}</span>
          </div>
          <span class="badge closed">${question.answered_count} 份回答</span>
        </div>
        ${body}
      </section>
    `;
  }

  function renderOverview() {
    const overview = state.overview;
    document.getElementById("statsTitle").textContent = overview.survey.title;
    document.getElementById("statsSubtitle").textContent = `统计口径：当前已发布版本 v${overview.version.version_no} · ${App.statusLabel(overview.survey.status)}`;
    document.getElementById("editLink").href = `/surveys/${SURVEY_ID}/edit`;
    document.getElementById("responseCount").textContent = overview.response_count;
    document.getElementById("questionTotal").textContent = overview.questions.length;
    document.getElementById("versionNo").textContent = `v${overview.version.version_no}`;
    document.getElementById("generatedAt").textContent = `生成于 ${App.formatDate(overview.generated_at, true)}${overview.version.published_at ? ` · 发布于 ${App.formatDate(overview.version.published_at, true)}` : ""}`;
    if (!overview.questions.length) {
      container.innerHTML = `<div class="card empty"><h2>暂无题目</h2><p>先去编辑器添加题目并发布。</p></div>`;
      return;
    }
    container.innerHTML = overview.questions
      .map((question, index) => renderQuestion(question, index))
      .join("");
  }

  async function loadTextAnswers(questionId, page, button) {
    const wrapper = document.getElementById(`textStats-${questionId}`);
    if (!wrapper) return;
    const list = wrapper.querySelector(".text-answers");
    button.disabled = true;
    button.textContent = "加载中…";
    try {
      const payload = await App.api(
        `/api/surveys/${SURVEY_ID}/questions/${encodeURIComponent(questionId)}/stats?page=${page}&page_size=20`
      );
      state.textPages.set(questionId, page);
      const items = payload.answers || [];
      list.innerHTML = items.length
        ? items.map((item) => `<div class="text-answer">${App.escapeHtml(item.text)}</div>`).join("")
        : `<p class="small subtle">暂无文本回答。</p>`;
      const pagination = payload.pagination || { page, total_pages: 0, total: 0 };
      const pager = document.createElement("div");
      pager.className = "actions";
      pager.style.marginTop = "12px";
      pager.innerHTML = `
        <button class="btn secondary small" type="button" data-text-page="${Math.max(1, page - 1)}" ${page <= 1 ? "disabled" : ""}>上一页</button>
        <span class="small subtle">第 ${page} / ${Math.max(1, pagination.total_pages)} 页 · 共 ${pagination.total} 条</span>
        <button class="btn secondary small" type="button" data-text-page="${page + 1}" ${page >= pagination.total_pages ? "disabled" : ""}>下一页</button>
      `;
      list.appendChild(pager);
    } catch (error) {
      list.innerHTML = `<div class="alert">${App.escapeHtml(error.message)}</div>`;
    } finally {
      button.disabled = false;
      button.textContent = "加载文本回答";
    }
  }

  container.addEventListener("click", (event) => {
    const loadButton = event.target.closest("[data-load-text]");
    if (loadButton) {
      loadTextAnswers(loadButton.dataset.loadText, 1, loadButton);
      return;
    }
    const pageButton = event.target.closest("[data-text-page]");
    if (pageButton) {
      const section = pageButton.closest("[data-question-id]");
      if (!section) return;
      const qid = section.dataset.questionId;
      const mainButton = section.querySelector("[data-load-text]");
      loadTextAnswers(qid, Number(pageButton.dataset.textPage), mainButton);
    }
  });

  async function loadStats() {
    loading.classList.remove("hidden");
    content.classList.add("hidden");
    errorNode.classList.add("hidden");
    try {
      state.overview = await App.api(`/api/surveys/${SURVEY_ID}/stats`);
      renderOverview();
      loading.classList.add("hidden");
      content.classList.remove("hidden");
    } catch (error) {
      loading.classList.add("hidden");
      if (error.status === 401) {
        window.location.href = App.loginUrl(`/surveys/${SURVEY_ID}/stats`);
        return;
      }
      errorNode.classList.remove("hidden");
      errorText.textContent = error.message;
    }
  }

  document.getElementById("refreshButton").addEventListener("click", loadStats);
  loadStats();
})();
