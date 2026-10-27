(function () {
  "use strict";

  const { api, escapeHtml, formatDate, showToast } = window.App;
  const QUESTION_ID = window.location.pathname.split("/")[2];

  const titleNode = document.getElementById("statsTitle");
  const metricGrid = document.getElementById("metricGrid");
  const versionNode = document.getElementById("versionBreakdown");
  const optionNode = document.getElementById("optionChart");
  const optionHint = document.getElementById("optionHint");
  const textSection = document.getElementById("textSection");
  const textNode = document.getElementById("textAnswers");
  const pageLabel = document.getElementById("pageLabel");

  let page = 1;
  let totalPages = 0;

  function metric(label, value) {
    return `
      <div class="card metric">
        <div class="metric-label">${label}</div>
        <div class="metric-value">${value}</div>
      </div>`;
  }

  function renderBars(options) {
    const max = Math.max(1, ...options.map((item) => item.count));
    return options
      .map(
        (item) => `
        <div class="qv-bar-row">
          <span class="qv-bar-label">${escapeHtml(item.label)}</span>
          <span class="qv-bar"><span style="width:${(item.count / max) * 100}%"></span></span>
          <span class="qv-bar-value">${item.count}</span>
        </div>`
      )
      .join("");
  }

  async function load() {
    const version = document.getElementById("versionSelect").value;
    const stats = await api(`/api/questions/${QUESTION_ID}/stats?version=${version}`);
    titleNode.textContent = stats.title;

    const metrics = [
      metric("作答数", stats.answered_count),
      metric("涉及问卷", stats.survey_count),
      metric("题目版本", stats.version_count),
    ];
    if (stats.type === "number") {
      metrics.push(metric("平均值", stats.average === null ? "—" : stats.average));
      metrics.push(metric("最小 / 最大", `${stats.minimum ?? "—"} / ${stats.maximum ?? "—"}`));
    }
    if (stats.type === "text") {
      metrics.push(metric("文本回答", stats.text_count));
    }
    metricGrid.innerHTML = metrics.join("");

    versionNode.innerHTML = stats.versions
      .map(
        (item) => `
        <div class="qv-version-row">
          <strong>v${item.version_no}</strong>
          <span class="muted">答题 ${item.answered_count} 份</span>
        </div>`
      )
      .join("");

    if (stats.option_counts.length) {
      optionNode.innerHTML = renderBars(stats.option_counts);
      optionHint.textContent = stats.option_set_mismatch
        ? `选项集合在不同版本间不一致，已按 option_id 合并；可能有个别版本缺少某些选项。`
        : "按 option_id 合并统计，同一选项跨版本保持同一身份。";
    } else {
      optionNode.innerHTML = "";
      optionHint.textContent = "";
    }

    const isText = stats.type === "text";
    textSection.classList.toggle("hidden", !isText);
    if (isText) {
      await loadText(version);
    }
  }

  async function loadText(version) {
    const payload = await api(
      `/api/questions/${QUESTION_ID}/stats/answers?version=${version}&page=${page}&page_size=10`
    );
    totalPages = payload.total_pages;
    textNode.innerHTML = payload.answers.length
      ? payload.answers
          .map(
            (item) => `
          <blockquote class="qv-quote">
            <p>${escapeHtml(item.text)}</p>
            <cite>${escapeHtml(item.survey_title)} · v${item.version_no} · ${formatDate(item.submitted_at, true)}</cite>
          </blockquote>`
          )
          .join("")
      : '<p class="muted">还没有文本回答。</p>';
    pageLabel.textContent = totalPages
      ? `第 ${payload.page} / ${totalPages} 页 · 共 ${payload.total} 条`
      : "暂无回答";
    document.getElementById("prevPage").disabled = page <= 1;
    document.getElementById("nextPage").disabled = page >= totalPages;
  }

  document.getElementById("refreshButton").addEventListener("click", () => {
    page = 1;
    load().catch((error) => showToast(error.message, "error"));
  });
  document.getElementById("versionSelect").addEventListener("change", () => {
    page = 1;
    load().catch((error) => showToast(error.message, "error"));
  });
  document.getElementById("prevPage").addEventListener("click", () => {
    if (page > 1) {
      page -= 1;
      load().catch((error) => showToast(error.message, "error"));
    }
  });
  document.getElementById("nextPage").addEventListener("click", () => {
    if (page < totalPages) {
      page += 1;
      load().catch((error) => showToast(error.message, "error"));
    }
  });

  load().catch((error) => showToast(error.message, "error"));
})();
