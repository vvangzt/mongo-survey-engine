(function () {
  "use strict";

  const root = document.getElementById("fillRoot");
  const slug = window.SURVEY_SLUG;
  const authenticated = Boolean(window.IS_AUTHENTICATED);
  const state = {
    survey: null,
    answers: [],
    skipped: new Set(),
    currentQuestion: null,
    completed: false,
    busy: false,
    token: (crypto.randomUUID && crypto.randomUUID()) || App.randomId("sub_", 32),
  };

  function shellTop(content, compact = false) {
    return `
      <div class="fill-top${compact ? " compact" : ""}">
        <div class="eyebrow">Survey Studio</div>
        ${content}
      </div>`;
  }

  function renderError(message, title = "暂时无法继续") {
    root.innerHTML = `
      ${shellTop(`<h1>${App.escapeHtml(title)}</h1>`)}
      <div class="fill-body">
        <div class="alert">${App.escapeHtml(message)}</div>
        <div class="fill-actions">
          <a class="btn secondary" href="/">返回首页</a>
        </div>
      </div>`;
  }

  function renderClosed() {
    const survey = state.survey;
    const reason = survey.status === "closed" ? "这份问卷已经关闭。" : "这份问卷当前不在开放时间内。";
    root.innerHTML = `
      ${shellTop(`
        <h1>${App.escapeHtml(survey.title)}</h1>
        <p class="muted" style="margin-bottom:0">${App.escapeHtml(survey.description || "")}</p>
      `)}
      <div class="fill-body">
        <div class="done-panel">
          <div class="done-mark" style="background:var(--warning-soft);color:var(--warning)">·</div>
          <h2>停止收集答卷</h2>
          <p class="muted">${App.escapeHtml(reason)}感谢你的关注。</p>
        </div>
      </div>`;
  }

  function renderIntro() {
    const survey = state.survey;
    const requiresLogin = survey.requires_login && !authenticated;
    const meta = [];
    meta.push(survey.allow_anonymous ? "支持匿名填写" : "需要登录后填写");
    if (survey.allow_multiple_responses) meta.push("允许多次提交");
    if (survey.closes_at) meta.push(`截止 ${App.formatDate(survey.closes_at, true)}`);
    root.innerHTML = `
      ${shellTop(`
        <h1>${App.escapeHtml(survey.title)}</h1>
        <p class="muted" style="max-width:620px">${App.escapeHtml(survey.description || "感谢你参与这次调查。")}</p>
        <div class="actions" style="margin-top:20px">
          ${meta.map((item) => `<span class="badge closed">${App.escapeHtml(item)}</span>`).join("")}
        </div>
      `)}
      <div class="fill-body">
        <div class="done-panel" style="text-align:left;padding:8px 0">
          <h2>开始前请确认</h2>
          <p class="muted">问卷会逐题展示，并根据你的回答自动进入下一题。请按照真实情况作答。</p>
          ${
            requiresLogin
              ? `<div class="alert warning" style="margin-top:14px">这份问卷要求登录后填写。</div>`
              : `<p class="small subtle">${authenticated ? "你已登录，可选择实名或匿名提交。" : "你当前未登录，提交时将以匿名身份保存。"}</p>`
          }
          <div class="fill-actions" style="border-top:0;padding-top:18px">
            <span></span>
            ${
              requiresLogin
                ? `<a class="btn" href="${App.loginUrl(`/survey/${slug}`)}">登录后填写</a>`
                : `<button class="btn" id="startButton" type="button">开始填写</button>`
            }
          </div>
        </div>
      </div>`;
    const start = document.getElementById("startButton");
    if (start) start.addEventListener("click", () => advance([]).catch(handleError));
  }

  function renderQuestion(question) {
    state.currentQuestion = question;
    const description = question.description
      ? `<p class="muted" style="margin:8px 0 0">${App.escapeHtml(question.description)}</p>`
      : "";
    let inputHtml = "";
    if (question.type === "single_choice" || question.type === "multi_choice") {
      inputHtml = `
        <div class="fill-options" id="fillOptions">
          ${(question.options || []).map((option, index) => `
            <label class="choice">
              <input type="${question.type === "single_choice" ? "radio" : "checkbox"}"
                name="choice" value="${App.escapeHtml(option.option_id)}">
              <span>
                <strong>${App.escapeHtml(option.label)}</strong>
              </span>
            </label>`).join("")}
        </div>`;
    } else if (question.type === "text") {
      const validation = question.validation || {};
      inputHtml = `
        <div class="field" style="margin-top:20px">
          <textarea id="textAnswer" maxlength="${validation.max_length || 5000}"
            placeholder="在这里填写你的回答"></textarea>
          <span class="hint">
            ${validation.min_length ? `至少 ${validation.min_length} 字 · ` : ""}
            最多 ${validation.max_length || 5000} 字
          </span>
        </div>`;
    } else {
      const validation = question.validation || {};
      const integer = validation.integer !== false;
      inputHtml = `
        <div class="field" style="margin-top:20px;max-width:300px">
          <input id="numberAnswer" type="number" step="${integer ? "1" : "any"}"
            inputmode="${integer ? "numeric" : "decimal"}"
            ${validation.min != null ? `min="${validation.min}"` : ""}
            ${validation.max != null ? `max="${validation.max}"` : ""}
            placeholder="${integer ? "输入整数" : "输入数字"}">
          <span class="hint">
            ${integer ? "必须是整数" : "允许小数"}
            ${validation.min != null ? ` · 最小 ${validation.min}` : ""}
            ${validation.max != null ? ` · 最大 ${validation.max}` : ""}
          </span>
        </div>`;
    }

    const validation = question.validation || {};
    let constraint = "";
    if (question.type === "multi_choice") {
      if (validation.exact_selected != null) {
        constraint = `必须选择 ${validation.exact_selected} 项`;
      } else {
        const bits = [];
        if (validation.min_selected != null) bits.push(`至少 ${validation.min_selected} 项`);
        if (validation.max_selected != null) bits.push(`最多 ${validation.max_selected} 项`);
        constraint = bits.length ? bits.join(" · ") : "可多选";
      }
    }

    root.innerHTML = `
      ${shellTop(`
        <span class="badge ${question.required ? "draft" : "closed"}">${question.required ? "必答" : "选答"}</span>
        <p class="small subtle" style="margin:12px 0 0">第 ${state.answers.length + 1} 步</p>
      `)}
      <div class="fill-body">
        <div class="progress-line" style="margin-bottom:24px"><span style="width:${Math.min(90, 18 + state.answers.length * 12)}%"></span></div>
        <div class="fill-question">
          <h2>${App.escapeHtml(question.title)}</h2>
          ${description}
          ${constraint ? `<p class="small subtle" style="margin:12px 0 0">${constraint}</p>` : ""}
          ${inputHtml}
        </div>
        <div class="form-error hidden" id="fillError" role="alert"></div>
        <div class="fill-actions">
          <span class="small subtle">${question.required ? "此题必须回答" : ""}</span>
          <div class="actions">
            ${question.required ? "" : `<button class="btn ghost" id="skipButton" type="button">跳过</button>`}
            <button class="btn" id="nextButton" type="button">继续</button>
          </div>
        </div>
      </div>`;
    document.getElementById("nextButton").addEventListener("click", handleNext);
    const skip = document.getElementById("skipButton");
    if (skip) skip.addEventListener("click", handleSkip);
    if (question.type === "text") {
      document.getElementById("textAnswer").focus();
    } else if (question.type === "number") {
      document.getElementById("numberAnswer").focus();
    }
  }

  function showFillError(message) {
    const node = document.getElementById("fillError");
    if (!node) {
      App.showToast(message, "error");
      return;
    }
    node.textContent = message;
    node.classList.remove("hidden");
  }

  function selectedOptionIds() {
    return Array.from(document.querySelectorAll("#fillOptions input:checked"))
      .map((input) => input.value);
  }

  function buildAnswer(question) {
    if (question.type === "single_choice" || question.type === "multi_choice") {
      const ids = selectedOptionIds();
      if (!ids.length) throw new Error("请选择一个选项");
      if (question.type === "single_choice" && ids.length !== 1) {
        throw new Error("单选只能选择一个选项");
      }
      if (question.type === "multi_choice") {
        const validation = question.validation || {};
        if (validation.exact_selected != null && ids.length !== validation.exact_selected) {
          throw new Error(`请选择 ${validation.exact_selected} 项`);
        }
        if (validation.min_selected != null && ids.length < validation.min_selected) {
          throw new Error(`至少选择 ${validation.min_selected} 项`);
        }
        if (validation.max_selected != null && ids.length > validation.max_selected) {
          throw new Error(`最多选择 ${validation.max_selected} 项`);
        }
      }
      return {
        question_id: question.question_id,
        type: question.type,
        option_ids: ids,
      };
    }
    if (question.type === "text") {
      const value = document.getElementById("textAnswer").value;
      const validation = question.validation || {};
      const trimmed = validation.trim === false ? value : value.trim();
      if (!trimmed) throw new Error("请输入回答");
      if (validation.min_length != null && trimmed.length < validation.min_length) {
        throw new Error(`至少输入 ${validation.min_length} 个字`);
      }
      if (validation.max_length != null && trimmed.length > validation.max_length) {
        throw new Error(`最多输入 ${validation.max_length} 个字`);
      }
      return {
        question_id: question.question_id,
        type: "text",
        text: trimmed,
      };
    }
    const rawValue = document.getElementById("numberAnswer").value;
    if (rawValue === "") throw new Error("请输入数字");
    const value = Number(rawValue);
    const validation = question.validation || {};
    if (!Number.isFinite(value)) throw new Error("请输入合法数字");
    if (validation.integer !== false && !Number.isInteger(value)) {
      throw new Error("请输入合法的整数");
    }
    if (validation.min != null && value < validation.min) {
      throw new Error(`数字不能小于 ${validation.min}`);
    }
    if (validation.max != null && value > validation.max) {
      throw new Error(`数字不能大于 ${validation.max}`);
    }
    return {
      question_id: question.question_id,
      type: "number",
      number: value,
    };
  }

  async function advance(answers, skipped = null) {
    if (state.busy) return;
    state.busy = true;
    try {
      const result = await App.api(`/api/public/surveys/${slug}/next`, {
        method: "POST",
        body: {
          answers,
          skipped_question_ids: Array.from(skipped || state.skipped),
        },
      });
      state.answers = answers;
      state.skipped = new Set(skipped || state.skipped);
      if (result.completed) {
        state.completed = true;
        state.currentQuestion = null;
        renderComplete(result);
      } else {
        renderQuestion(result.next_question);
      }
    } catch (error) {
      if (error.status === 401) {
        window.location.href = App.loginUrl(`/survey/${slug}`);
        return;
      }
      if (error.status === 409) {
        renderError(error.message, "问卷当前不可填写");
        return;
      }
      showFillError(error.message);
    } finally {
      state.busy = false;
    }
  }

  function handleNext() {
    if (state.busy) return;
    try {
      const answer = buildAnswer(state.currentQuestion);
      const exists = state.answers.findIndex((item) => item.question_id === answer.question_id);
      const nextAnswers = state.answers.slice();
      if (exists >= 0) nextAnswers[exists] = answer;
      else nextAnswers.push(answer);
      const nextSkipped = new Set(state.skipped);
      nextSkipped.delete(answer.question_id);
      advance(nextAnswers, nextSkipped);
    } catch (error) {
      showFillError(error.message);
    }
  }

  function handleSkip() {
    if (state.busy || !state.currentQuestion || state.currentQuestion.required) return;
    const skipped = new Set(state.skipped);
    skipped.add(state.currentQuestion.question_id);
    advance(state.answers, skipped);
  }

  function renderComplete() {
    const survey = state.survey;
    const canChooseAnonymous = survey.allow_anonymous && authenticated;
    const anonymousForced = survey.allow_anonymous && !authenticated;
    root.innerHTML = `
      ${shellTop(`
        <h1>${App.escapeHtml(survey.title)}</h1>
      `)}
      <div class="fill-body">
        <div class="done-panel">
          <div class="done-mark">✓</div>
          <h2>已到达本次问卷末尾</h2>
          <p class="muted">你已经完成所有可见题目，确认后提交即可保存答卷。</p>
        </div>
        ${
          canChooseAnonymous
            ? `<label class="checkbox-row" style="margin-top:16px">
                 <input id="anonymousChoice" type="checkbox">
                 <span><strong>匿名提交。</strong> 勾选后不记录你的账号身份。</span>
               </label>`
            : anonymousForced
              ? `<div class="alert warning" style="margin-top:16px">你当前未登录，本答卷将以匿名身份提交。</div>`
              : `<div class="alert" style="margin-top:16px">本问卷要求登录，提交时将记录你的账号身份。</div>`
        }
        <div class="form-error hidden" id="fillError" role="alert"></div>
        <div class="fill-actions">
          <span class="small subtle">${state.answers.length} 个已回答题目</span>
          <button class="btn" id="submitButton" type="button">提交答卷</button>
        </div>
      </div>`;
    document.getElementById("submitButton").addEventListener("click", submitAnswers);
  }

  async function submitAnswers() {
    if (state.busy) return;
    state.busy = true;
    const button = document.getElementById("submitButton");
    button.disabled = true;
    button.textContent = "提交中…";
    const checkbox = document.getElementById("anonymousChoice");
    const isAnonymous = state.survey.allow_anonymous
      ? (authenticated ? Boolean(checkbox && checkbox.checked) : true)
      : false;
    try {
      await App.api(`/api/public/surveys/${slug}/responses`, {
        method: "POST",
        body: {
          answers: state.answers,
          is_anonymous: isAnonymous,
          submission_token: state.token,
        },
      });
      renderSubmitted();
    } catch (error) {
      if (error.status === 401) {
        window.location.href = App.loginUrl(`/survey/${slug}`);
        return;
      }
      showFillError(error.message);
      button.disabled = false;
      button.textContent = "提交答卷";
    } finally {
      state.busy = false;
    }
  }

  function renderSubmitted() {
    root.innerHTML = `
      ${shellTop(`<h1>提交成功</h1>`)}
      <div class="fill-body">
        <div class="done-panel">
          <div class="done-mark">✓</div>
          <h2>谢谢你完成这份问卷</h2>
          <p class="muted">你的回答已经保存。可以关闭此页面。</p>
          <div class="fill-actions" style="justify-content:center;border-top:0">
            <a class="btn secondary" href="/">返回首页</a>
          </div>
        </div>
      </div>`;
  }

  function handleError(error) {
    if (error.status === 401) {
      window.location.href = App.loginUrl(`/survey/${slug}`);
      return;
    }
    renderError(error.message, "加载问卷失败");
  }

  async function load() {
    try {
      state.survey = await App.api(`/api/public/surveys/${slug}`);
      if (!state.survey.is_open) {
        renderClosed();
        return;
      }
      renderIntro();
    } catch (error) {
      if (error.status === 404) {
        renderError("问卷不存在，或尚未发布。", "找不到这份问卷");
      } else {
        handleError(error);
      }
    }
  }

  load();
})();
