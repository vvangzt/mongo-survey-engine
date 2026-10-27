(function () {
  "use strict";

  const SURVEY_ID = window.SURVEY_ID;
  const TYPE_LABELS = {
    single_choice: "单选题",
    multi_choice: "多选题",
    text: "文本题",
    number: "数字题",
  };
  const OPERATOR_LABELS = {
    eq: "等于",
    neq: "不等于",
    in: "属于集合",
    not_in: "不属于集合",
    includes_any: "包含任意",
    includes_all: "包含全部",
    includes_none: "不包含任何",
    equals_set: "选择集合等于",
    selection_count_eq: "选择数量等于",
    selection_count_gte: "选择数量至少",
    selection_count_lte: "选择数量至多",
    gt: "大于",
    gte: "大于等于",
    lt: "小于",
    lte: "小于等于",
    between: "位于区间",
  };
  const LIST_OPERATORS = new Set([
    "in",
    "not_in",
    "includes_any",
    "includes_all",
    "includes_none",
    "equals_set",
  ]);
  const COUNT_OPERATORS = new Set([
    "selection_count_eq",
    "selection_count_gte",
    "selection_count_lte",
  ]);

  const state = {
    survey: null,
    version: null,
    revision: 0,
    questions: [],
    readonly: false,
    dirty: false,
    saving: false,
  };
  let ruleContext = null;

  const questionList = document.getElementById("questionList");
  const loading = document.getElementById("editorLoading");
  const content = document.getElementById("editorContent");
  const errorNode = document.getElementById("editorError");
  const errorText = document.getElementById("editorErrorText");
  const saveState = document.getElementById("saveState");
  const saveButton = document.getElementById("saveButton");
  const publishButton = document.getElementById("publishButton");
  const readonlyNotice = document.getElementById("readonlyNotice");
  const statusBadge = document.getElementById("statusBadge");
  const previewLink = document.getElementById("previewLink");
  const statsLink = document.getElementById("statsLink");
  const addBar = document.getElementById("addQuestionBar");

  function deepClone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function typeLabel(type) {
    return TYPE_LABELS[type] || type;
  }

  function localDatetime(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    const pad = (n) => String(n).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  function markDirty() {
    if (state.readonly) return;
    state.dirty = true;
    saveState.textContent = "有未保存修改";
  }

  function setStatusBadge(status) {
    statusBadge.className = `badge ${status}`;
    statusBadge.textContent = App.statusLabel(status);
  }

  function disableStaticControls() {
    ["surveyTitle", "surveyDescription", "allowAnonymous", "allowMultiple", "closesAt"].forEach((id) => {
      const node = document.getElementById(id);
      if (node) node.disabled = state.readonly;
    });
    addBar.querySelectorAll("button").forEach((button) => {
      button.disabled = state.readonly;
    });
    saveButton.disabled = state.readonly;
    publishButton.disabled = state.readonly;
  }

  async function loadSurvey() {
    try {
      const survey = await App.api(`/api/surveys/${SURVEY_ID}`);
      state.survey = survey;
      const version = survey.current_draft || survey.published_version;
      if (!version) {
        throw new Error("问卷还没有可编辑的版本");
      }
      state.version = version;
      state.revision = version.revision;
      state.questions = deepClone(version.questions || []);
      state.readonly = survey.status === "closed" || !survey.current_draft;

      document.getElementById("surveyTitle").value = survey.title || "";
      document.getElementById("surveyDescription").value = survey.description || "";
      document.getElementById("allowAnonymous").checked = Boolean(survey.allow_anonymous);
      document.getElementById("allowMultiple").checked = Boolean(survey.allow_multiple_responses);
      document.getElementById("closesAt").value = localDatetime(survey.closes_at);
      const editLabel = state.readonly
        ? "只读"
        : survey.status === "published"
          ? "新版本草稿可编辑"
          : "草稿可编辑";
      document.getElementById("editorSubtitle").textContent = `${survey.title} · ${editLabel}`;
      document.getElementById("surveySlug").textContent = `/survey/${survey.slug}`;
      document.getElementById("versionNumber").textContent = `v${version.version_no}`;
      statsLink.href = `/surveys/${SURVEY_ID}/stats`;
      setStatusBadge(survey.status);
      publishButton.textContent = survey.status === "published" ? "发布新版本" : "发布问卷";

      if (survey.status !== "draft") {
        previewLink.classList.remove("hidden");
        previewLink.href = `/survey/${survey.slug}`;
      }
      if (state.readonly) {
        readonlyNotice.classList.remove("hidden");
        saveState.textContent = "已冻结";
      } else {
        saveState.textContent = "尚未修改";
      }
      disableStaticControls();
      renderQuestions();
      loading.classList.add("hidden");
      content.classList.remove("hidden");
      if (!state.readonly) {
        saveButton.disabled = false;
        publishButton.disabled = false;
      }
    } catch (error) {
      loading.classList.add("hidden");
      errorNode.classList.remove("hidden");
      errorText.textContent = error.message;
    }
  }

  function newQuestion(type) {
    const q = {
      question_id: App.randomId("q_", 12),
      type,
      title: `未命名的${typeLabel(type)}`,
      required: false,
    };
    if (type === "single_choice" || type === "multi_choice") {
      q.options = [
        { option_id: App.randomId("o_", 12), label: "选项 A" },
        { option_id: App.randomId("o_", 12), label: "选项 B" },
        { option_id: App.randomId("o_", 12), label: "选项 C" },
      ];
      if (type === "multi_choice") {
        q.validation = { min_selected: 1, max_selected: 2 };
      }
    } else if (type === "text") {
      q.validation = { min_length: 0, max_length: 500, trim: true };
    } else {
      q.validation = { integer: true, min: 0, max: 100 };
    }
    return q;
  }

  function disabledAttr() {
    return state.readonly ? "disabled" : "";
  }

  function optionLetters(index) {
    return String.fromCharCode(65 + index);
  }

  function renderOptions(question) {
    if (question.type !== "single_choice" && question.type !== "multi_choice") return "";
    return `
      <div class="field">
        <span class="label">选项</span>
        <div class="option-list" style="display:grid;gap:8px">
          ${(question.options || [])
            .map(
              (option, index) => `
                <div class="option-row">
                  <span class="option-dot">${optionLetters(index)}</span>
                  <input data-option-label="${index}" value="${App.escapeHtml(option.label)}"
                    aria-label="选项 ${optionLetters(index)} 文案" ${disabledAttr()}>
                  <button class="btn ghost small" type="button" data-remove-option="${index}"
                    ${state.readonly || question.options.length <= 2 ? "disabled" : ""}>移除</button>
                </div>`
            )
            .join("")}
        </div>
        ${state.readonly ? "" : `<button class="btn ghost small" type="button" data-add-option style="justify-self:start">＋ 添加选项</button>`}
      </div>
    `;
  }

  function renderValidation(question) {
    if (question.type === "single_choice") {
      return `<p class="small subtle" style="margin:0">单选只能选择一个选项。</p>`;
    }
    if (question.type === "multi_choice") {
      const validation = question.validation || {};
      const mode = validation.exact_selected != null ? "exact" : "range";
      return `
        <div class="field">
          <span class="label">选择数量</span>
          <div class="mini-grid">
            <select data-multi-mode ${disabledAttr()}>
              <option value="range" ${mode === "range" ? "selected" : ""}>区间限制</option>
              <option value="exact" ${mode === "exact" ? "selected" : ""}>指定数量</option>
            </select>
            ${
              mode === "range"
                ? `<input type="number" min="0" placeholder="最少" data-validation="min_selected"
                     value="${validation.min_selected ?? ""}" ${disabledAttr()}>
                   <input type="number" min="1" placeholder="最多" data-validation="max_selected"
                     value="${validation.max_selected ?? ""}" ${disabledAttr()}>`
                : `<input type="number" min="1" placeholder="必须选择几项" data-validation="exact_selected"
                     value="${validation.exact_selected ?? 2}" ${disabledAttr()}>`
            }
          </div>
          <span class="hint">范围与指定数量不能同时设置。必答题未填写时至少选择 1 项。</span>
        </div>
      `;
    }
    if (question.type === "text") {
      const validation = question.validation || {};
      return `
        <div class="field">
          <span class="label">文本限制</span>
          <div class="mini-grid">
            <input type="number" min="0" max="5000" data-validation="min_length"
              placeholder="最少字数" value="${validation.min_length ?? 0}" ${disabledAttr()}>
            <input type="number" min="1" max="5000" data-validation="max_length"
              placeholder="最多字数" value="${validation.max_length ?? 500}" ${disabledAttr()}>
            <label class="checkbox-row" style="padding:9px 11px">
              <input type="checkbox" data-trim ${validation.trim !== false ? "checked" : ""} ${disabledAttr()}>
              <span>自动去首尾空格</span>
            </label>
          </div>
        </div>
      `;
    }
    const validation = question.validation || {};
    const integer = validation.integer !== false;
    return `
      <div class="field">
        <span class="label">数字限制</span>
        <div class="mini-grid">
          <input type="number" step="any" data-validation="min"
            placeholder="最小值" value="${validation.min ?? ""}" ${disabledAttr()}>
          <input type="number" step="any" data-validation="max"
            placeholder="最大值" value="${validation.max ?? ""}" ${disabledAttr()}>
          <label class="checkbox-row" style="padding:9px 11px">
            <input type="checkbox" data-number-integer ${integer ? "checked" : ""} ${disabledAttr()}>
            <span>必须是整数</span>
          </label>
        </div>
        <span class="hint">${integer ? "当前只接受整数；手机号、年龄等场景适用。" : "当前允许小数；输入框按有限数值校验。"}</span>
      </div>
    `;
  }

  function formatRuleValue(rule, question) {
    const condition = rule.when && rule.when.conditions && rule.when.conditions[0];
    if (!condition) return "复杂条件";
    const value = condition.value;
    if (LIST_OPERATORS.has(condition.operator)) {
      const labels = (Array.isArray(value) ? value : [value]).map((id) => {
        const option = (question.options || []).find((item) => item.option_id === id);
        return option ? option.label : id;
      });
      return labels.join("、");
    }
    if (question.type !== "number" && typeof value === "string") {
      const option = (question.options || []).find((item) => item.option_id === value);
      return option ? option.label : value;
    }
    if (condition.operator === "between" && Array.isArray(value)) {
      return `${value[0]} ~ ${value[1]}`;
    }
    return String(value);
  }

  function renderRuleSummary(rule, question, questionIndex, ruleIndex) {
    const condition = rule.when && rule.when.conditions && rule.when.conditions[0];
    const isSimple = rule.when.conditions && rule.when.conditions.length === 1 && condition &&
      condition.question_id === question.question_id;
    const target = rule.then && rule.then.action === "end"
      ? "结束问卷"
      : (() => {
          const targetIndex = state.questions.findIndex((item) => item.question_id === rule.then.target_question_id);
          return targetIndex >= 0 ? `跳转到第 ${targetIndex + 1} 题` : "目标题目";
        })();
    const opLabel = condition ? (OPERATOR_LABELS[condition.operator] || condition.operator) : "复杂条件";
    const valueLabel = condition ? formatRuleValue(rule, question) : "";
    return `
      <div class="rule-chip">
        <span>当回答 <strong>${App.escapeHtml(opLabel)} ${App.escapeHtml(valueLabel)}</strong> → ${App.escapeHtml(target)}</span>
        <span class="actions">
          ${!state.readonly && isSimple ? `<button class="btn ghost small" type="button" data-edit-rule="${ruleIndex}">编辑</button>` : ""}
          ${!state.readonly ? `<button class="btn ghost small" type="button" data-delete-rule="${ruleIndex}">删除</button>` : ""}
        </span>
      </div>
    `;
  }

  function renderLogic(question, index) {
    if (question.type === "text") {
      return `<p class="small subtle" style="margin:0">文本题暂不参与跳转条件。</p>`;
    }
    const logic = question.logic || {};
    const fallback = logic.fallback ? logic.fallback.action : "next";
    const rules = logic.rules || [];
    return `
      <div class="field">
        <div class="rule-list" style="display:grid;gap:8px">
          ${rules.length
            ? rules.map((rule, ruleIndex) => renderRuleSummary(rule, question, index, ruleIndex)).join("")
            : `<span class="small subtle">暂无跳转规则，按顺序进入下一题。</span>`}
        </div>
        <div class="actions" style="margin-top:2px">
          ${state.readonly ? "" : `<button class="btn secondary small" type="button" data-add-rule>＋ 添加跳转规则</button>`}
          <span class="small muted">无规则时</span>
          <select data-fallback style="width:auto;min-height:34px;padding:5px 9px" ${disabledAttr()}>
            <option value="next" ${fallback === "next" ? "selected" : ""}>进入下一题</option>
            <option value="end" ${fallback === "end" ? "selected" : ""}>结束问卷</option>
          </select>
        </div>
      </div>
    `;
  }

  function renderQuestions() {
    document.getElementById("questionCount").textContent = `${state.questions.length} 道题`;
    if (!state.questions.length) {
      questionList.innerHTML = `
        <div class="card empty">
          <div class="empty-mark">?</div>
          <h2>还没有题目</h2>
          <p>从下方添加单选、多选、文本或数字题。保存草稿后可以随时回来继续编辑。</p>
        </div>`;
      return;
    }
    questionList.innerHTML = state.questions
      .map((question, index) => {
        const required = question.required === true;
        const description = question.description || "";
        return `
          <article class="question-card" data-qindex="${index}" id="question-${index}">
            <div class="question-head">
              <div class="question-index">
                <span class="qnum">${index + 1}</span>
                <span>${App.escapeHtml(typeLabel(question.type))}</span>
                ${required ? `<span class="badge draft">必答</span>` : ""}
                ${question.question_ref ? `<span class="badge published">题库</span>` : ""}
              </div>
              <div class="actions">
                ${question.question_ref ? `<button class="btn ghost small" type="button" data-refresh-question="${App.escapeHtml(question.question_id)}" ${state.readonly ? "disabled" : ""}>更新到最新版本</button>` : ""}
                <button class="btn ghost small" type="button" data-move="up" ${state.readonly || index === 0 ? "disabled" : ""}>上移</button>
                <button class="btn ghost small" type="button" data-move="down" ${state.readonly || index === state.questions.length - 1 ? "disabled" : ""}>下移</button>
                <button class="btn danger small" type="button" data-delete-question ${state.readonly ? "disabled" : ""}>删除</button>
              </div>
            </div>
            <div class="question-body">
              <input class="question-title-input" data-field="title" value="${App.escapeHtml(question.title || "")}"
                placeholder="输入题目" ${disabledAttr()}>
              <input data-field="description" value="${App.escapeHtml(description)}"
                placeholder="补充说明（可选）" ${disabledAttr()}>
              <label class="checkbox-row">
                <input type="checkbox" data-field="required" ${required ? "checked" : ""} ${disabledAttr()}>
                <span><strong>必答题。</strong> 只有实际展示路径上的题目才会检查必答。</span>
              </label>
              ${renderOptions(question)}
              ${renderValidation(question)}
              ${renderLogic(question, index)}
            </div>
          </article>
        `;
      })
      .join("");
  }

  function markAndRender() {
    markDirty();
    renderQuestions();
  }

  function pruneInvalidRules() {
    const positions = new Map(state.questions.map((q, i) => [q.question_id, i]));
    let changed = false;
    state.questions.forEach((question, index) => {
      if (!question.logic) return;
      const rules = question.logic.rules || [];
      const valid = rules.filter((rule) => {
        const conditions = (rule.when && rule.when.conditions) || [];
        if (!conditions.length) return false;
        const conditionsOk = conditions.every((condition) => {
          const sourceIndex = positions.get(condition.question_id);
          return sourceIndex !== undefined && sourceIndex <= index;
        });
        if (!conditionsOk) return false;
        if (rule.then && rule.then.action === "goto") {
          const targetIndex = positions.get(rule.then.target_question_id);
          return targetIndex !== undefined && targetIndex > index;
        }
        return rule.then && rule.then.action === "end";
      });
      if (valid.length !== rules.length) changed = true;
      question.logic.rules = valid;
      if (!valid.length && question.logic.fallback.action === "next") {
        delete question.logic;
      }
    });
    if (changed) App.showToast("顺序变化后，已移除指向前面题目的失效规则", "warning");
  }

  function addQuestion(type) {
    if (state.readonly) return;
    state.questions.push(newQuestion(type));
    markAndRender();
    const last = document.getElementById(`question-${state.questions.length - 1}`);
    if (last) last.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  async function saveDraft(options = {}) {
    if (state.readonly || state.saving) return false;
    const title = document.getElementById("surveyTitle").value.trim();
    if (!title) {
      App.showToast("请填写问卷标题", "error");
      return false;
    }
    for (let i = 0; i < state.questions.length; i += 1) {
      const question = state.questions[i];
      question.title = (question.title || "").trim();
      question.description = (question.description || "").trim();
      if (!question.title) {
        App.showToast(`第 ${i + 1} 题缺少标题`, "error");
        return false;
      }
      if (question.options) {
        question.options.forEach((option) => {
          option.label = (option.label || "").trim();
        });
        if (question.options.length < 2 || question.options.some((option) => !option.label)) {
          App.showToast(`第 ${i + 1} 题至少需要两个有文案的选项`, "error");
          return false;
        }
      }
      if (question.type === "multi_choice") {
        const validation = question.validation || {};
        if (validation.exact_selected != null) {
          delete validation.min_selected;
          delete validation.max_selected;
          if (validation.exact_selected > question.options.length) {
            App.showToast(`第 ${i + 1} 题的指定数量不能超过选项数`, "error");
            return false;
          }
        } else {
          delete validation.exact_selected;
          if (validation.min_selected == null) delete validation.min_selected;
          if (validation.max_selected == null) delete validation.max_selected;
          if (validation.min_selected != null && validation.min_selected > question.options.length) {
            App.showToast(`第 ${i + 1} 题的最少选择数不能超过选项数`, "error");
            return false;
          }
          if (validation.max_selected != null && validation.max_selected > question.options.length) {
            App.showToast(`第 ${i + 1} 题的最多选择数不能超过选项数`, "error");
            return false;
          }
          if (validation.min_selected != null && validation.max_selected != null &&
              validation.min_selected > validation.max_selected) {
            App.showToast(`第 ${i + 1} 题的最少选择数不能大于最多选择数`, "error");
            return false;
          }
        }
      }
      if (question.type === "text") {
        const validation = question.validation || {};
        if (!Number.isInteger(validation.max_length) || validation.max_length < 1) {
          App.showToast(`第 ${i + 1} 题请填写有效的最大字数`, "error");
          return false;
        }
        if (validation.min_length != null && validation.min_length > validation.max_length) {
          App.showToast(`第 ${i + 1} 题最少字数不能大于最多字数`, "error");
          return false;
        }
      }
      if (question.type === "number") {
        const validation = question.validation || {};
        if (typeof validation.integer !== "boolean") validation.integer = true;
        if (validation.min != null && !Number.isFinite(Number(validation.min))) {
          App.showToast(`第 ${i + 1} 题最小值必须是有限数值`, "error");
          return false;
        }
        if (validation.max != null && !Number.isFinite(Number(validation.max))) {
          App.showToast(`第 ${i + 1} 题最大值必须是有限数值`, "error");
          return false;
        }
        if (validation.min != null && validation.max != null &&
            Number(validation.min) > Number(validation.max)) {
          App.showToast(`第 ${i + 1} 题最小值不能大于最大值`, "error");
          return false;
        }
      }
      if (question.logic && (!question.logic.rules || !question.logic.rules.length) &&
          question.logic.fallback.action === "next") {
        delete question.logic;
      }
    }
    pruneInvalidRules();
    const closesAt = document.getElementById("closesAt").value;
    state.saving = true;
    saveButton.disabled = true;
    publishButton.disabled = true;
    saveState.textContent = "保存中…";
    const originalText = saveButton.textContent;
    saveButton.textContent = "保存中…";
    try {
      await App.api(`/api/surveys/${SURVEY_ID}`, {
        method: "PATCH",
        body: {
          title,
          description: document.getElementById("surveyDescription").value.trim(),
          allow_anonymous: document.getElementById("allowAnonymous").checked,
          allow_multiple_responses: document.getElementById("allowMultiple").checked,
          closes_at: closesAt ? new Date(closesAt).toISOString() : null,
        },
      });
      const version = await App.api(`/api/surveys/${SURVEY_ID}/draft`, {
        method: "PUT",
        body: {
          revision: state.revision,
          questions: state.questions,
        },
      });
      state.version = version;
      state.revision = version.revision;
      state.survey.title = title;
      state.survey.description = document.getElementById("surveyDescription").value.trim();
      state.survey.allow_anonymous = document.getElementById("allowAnonymous").checked;
      state.survey.allow_multiple_responses = document.getElementById("allowMultiple").checked;
      state.dirty = false;
      saveState.textContent = "已保存";
      document.getElementById("editorSubtitle").textContent = `${title} · 草稿可编辑`;
      if (!options.silent) App.showToast("草稿已保存", "success");
      return true;
    } catch (error) {
      saveState.textContent = "保存失败";
      App.showToast(error.message, "error");
      return false;
    } finally {
      state.saving = false;
      if (!state.readonly) {
        saveButton.disabled = false;
        publishButton.disabled = false;
      }
      saveButton.textContent = originalText;
    }
  }

  async function publishSurvey() {
    if (state.readonly) return;
    const ok = await saveDraft({ silent: true });
    if (!ok) return;
    publishButton.disabled = true;
    publishButton.textContent = "发布中…";
    try {
      const published = await App.api(`/api/surveys/${SURVEY_ID}/publish`, {
        method: "POST",
      });
      state.survey.status = "published";
      state.readonly = true;
      setStatusBadge("published");
      App.showToast("问卷已发布，填写链接已生成", "success");
      window.setTimeout(() => {
        window.location.href = `/surveys/${SURVEY_ID}/stats`;
      }, 700);
      return published;
    } catch (error) {
      App.showToast(error.message, "error");
      publishButton.disabled = false;
      publishButton.textContent = "发布问卷";
      return null;
    }
  }

  function closeRuleModal() {
    document.getElementById("ruleModal").classList.add("hidden");
    ruleContext = null;
  }

  function operatorsFor(type) {
    if (type === "single_choice") return ["eq", "neq", "in", "not_in"];
    if (type === "multi_choice") {
      return ["includes_any", "includes_all", "includes_none", "equals_set",
        "selection_count_eq", "selection_count_gte", "selection_count_lte"];
    }
    if (type === "number") return ["eq", "neq", "gt", "gte", "lt", "lte", "between"];
    return [];
  }

  function optionValueOptions(question) {
    return (question.options || []).map((option) => ({
      value: option.option_id,
      label: option.label,
    }));
  }

  function renderRuleOperand(operator, value) {
    const question = state.questions[ruleContext.qIndex];
    const container = document.getElementById("ruleOperand");
    if (LIST_OPERATORS.has(operator)) {
      const selected = new Set(Array.isArray(value) ? value : value ? [value] : []);
      container.innerHTML = `
        <div class="choice-grid" style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px">
          ${optionValueOptions(question)
            .map((option) => `
              <label class="checkbox-row">
                <input type="checkbox" data-rule-option value="${App.escapeHtml(option.value)}"
                  ${selected.has(option.value) ? "checked" : ""}>
                <span>${App.escapeHtml(option.label)}</span>
              </label>`)
            .join("")}
        </div>`;
      return;
    }
    if (COUNT_OPERATORS.has(operator)) {
      container.innerHTML = `<input id="ruleNumber" type="number" min="0" step="1" value="${Number.isInteger(value) ? value : 0}">`;
      return;
    }
    if (question.type === "number" && operator === "between") {
      const pair = Array.isArray(value) && value.length === 2 ? value : [0, 0];
      container.innerHTML = `
        <div class="mini-grid">
          <input id="ruleRangeLow" type="number" step="any" value="${pair[0]}" placeholder="下限">
          <input id="ruleRangeHigh" type="number" step="any" value="${pair[1]}" placeholder="上限">
          <span></span>
        </div>`;
      return;
    }
    if (question.type === "number") {
      const numeric = typeof value === "number" && Number.isFinite(value) ? value : 0;
      container.innerHTML = `<input id="ruleNumber" type="number" step="any" value="${numeric}">`;
      return;
    }
    const options = optionValueOptions(question);
    const selected = typeof value === "string" ? value : "";
    container.innerHTML = `
      <select id="ruleSelect">
        ${options.map((option) => `<option value="${App.escapeHtml(option.value)}" ${option.value === selected ? "selected" : ""}>${App.escapeHtml(option.label)}</option>`).join("")}
      </select>`;
  }

  function ruleTargetOptions(questionIndex, selected) {
    const later = state.questions.slice(questionIndex + 1);
    const options = later.map((question, offset) => ({
      value: question.question_id,
      label: `第 ${questionIndex + offset + 2} 题 · ${question.title}`,
    }));
    if (!options.length || selected === "end") {
      return `<option value="end" selected>结束问卷</option>`;
    }
    return options
      .map((option) => `<option value="${App.escapeHtml(option.value)}" ${option.value === selected ? "selected" : ""}>${App.escapeHtml(option.label)}</option>`)
      .join("") + `<option value="end" ${selected === "end" ? "selected" : ""}>结束问卷</option>`;
  }

  function updateRuleTargetVisibility() {
    const action = document.getElementById("ruleAction").value;
    document.getElementById("ruleTargetField").classList.toggle("hidden", action === "end");
  }

  function openRuleModal(questionIndex, ruleIndex = null) {
    if (state.readonly) return;
    const question = state.questions[questionIndex];
    if (!question || question.type === "text") return;
    ruleContext = { qIndex: questionIndex, ruleIndex };
    const existing = ruleIndex != null
      ? question.logic.rules[ruleIndex]
      : null;
    const operator = existing && existing.when
      ? existing.when.conditions[0].operator
      : operatorsFor(question.type)[0];
    document.getElementById("ruleTitle").textContent = ruleIndex == null ? "添加跳转规则" : "编辑跳转规则";
    document.getElementById("ruleSubtitle").textContent = `条件来自第 ${questionIndex + 1} 题：${question.title}`;
    const operatorSelect = document.getElementById("ruleOperator");
    operatorSelect.innerHTML = operatorsFor(question.type)
      .map((operator) => `<option value="${operator}" ${operator === operator ? "" : ""}>${OPERATOR_LABELS[operator]}</option>`)
      .join("");
    operatorSelect.value = operator;
    const action = existing && existing.then ? existing.then.action : (questionIndex < state.questions.length - 1 ? "goto" : "end");
    document.getElementById("ruleAction").value = action;
    const target = existing && existing.then && existing.then.target_question_id
      ? existing.then.target_question_id
      : (questionIndex < state.questions.length - 1 ? state.questions[questionIndex + 1].question_id : "end");
    document.getElementById("ruleTarget").innerHTML = ruleTargetOptions(questionIndex, target);
    if (action === "end") document.getElementById("ruleTarget").value = "end";
    const value = existing && existing.when ? existing.when.conditions[0].value : undefined;
    renderRuleOperand(operator, value);
    document.getElementById("ruleError").classList.add("hidden");
    updateRuleTargetVisibility();
    document.getElementById("ruleModal").classList.remove("hidden");
  }

  function readRuleOperand(operator) {
    if (LIST_OPERATORS.has(operator)) {
      const selected = Array.from(document.querySelectorAll("[data-rule-option]:checked"))
        .map((input) => input.value);
      if (!selected.length) throw new Error("请至少选择一个条件值");
      return selected;
    }
    if (COUNT_OPERATORS.has(operator)) {
      const value = Number(document.getElementById("ruleNumber").value);
      if (!Number.isInteger(value)) throw new Error("选择数量必须是整数");
      return value;
    }
    if (state.questions[ruleContext.qIndex].type === "number") {
      if (operator === "between") {
        const low = Number(document.getElementById("ruleRangeLow").value);
        const high = Number(document.getElementById("ruleRangeHigh").value);
        if (!Number.isFinite(low) || !Number.isFinite(high) || low > high) {
          throw new Error("区间必须是两个有限数值，且下限不大于上限");
        }
        return [low, high];
      }
      const value = Number(document.getElementById("ruleNumber").value);
      if (!Number.isFinite(value)) throw new Error("请输入有限数值");
      return value;
    }
    const value = document.getElementById("ruleSelect").value;
    if (!value) throw new Error("请选择一个条件值");
    return value;
  }

  function saveRule(event) {
    event.preventDefault();
    if (!ruleContext) return;
    const question = state.questions[ruleContext.qIndex];
    const operator = document.getElementById("ruleOperator").value;
    const action = document.getElementById("ruleAction").value;
    let target = action === "goto" ? document.getElementById("ruleTarget").value : "end";
    if (action === "goto" && (!target || target === "end")) {
      document.getElementById("ruleError").textContent = "请选择后续题目，或把动作改为结束问卷";
      document.getElementById("ruleError").classList.remove("hidden");
      return;
    }
    try {
      const value = readRuleOperand(operator);
      const existing = ruleContext.ruleIndex != null
        ? question.logic.rules[ruleContext.ruleIndex]
        : null;
      const rule = {
        rule_id: existing ? existing.rule_id : App.randomId("r_", 12),
        when: {
          mode: "all",
          conditions: [{
            question_id: question.question_id,
            operator,
            value,
          }],
        },
        then: action === "end"
          ? { action: "end" }
          : { action: "goto", target_question_id: target },
      };
      if (!question.logic) {
        question.logic = { fallback: { action: "next" }, rules: [] };
      }
      const rules = question.logic.rules || [];
      if (ruleContext.ruleIndex != null) {
        rules[ruleContext.ruleIndex] = rule;
      } else {
        rules.push(rule);
      }
      question.logic.rules = rules;
      markDirty();
      renderQuestions();
      closeRuleModal();
    } catch (error) {
      document.getElementById("ruleError").textContent = error.message;
      document.getElementById("ruleError").classList.remove("hidden");
    }
  }

  document.getElementById("ruleOperator").addEventListener("change", (event) => {
    renderRuleOperand(event.target.value, undefined);
  });
  document.getElementById("ruleAction").addEventListener("change", updateRuleTargetVisibility);
  document.getElementById("ruleForm").addEventListener("submit", saveRule);
  document.querySelectorAll("[data-close-rule]").forEach((button) => {
    button.addEventListener("click", closeRuleModal);
  });
  document.getElementById("ruleModal").addEventListener("click", (event) => {
    if (event.target.id === "ruleModal") closeRuleModal();
  });

  questionList.addEventListener("input", (event) => {
    if (state.readonly) return;
    const card = event.target.closest("[data-qindex]");
    if (!card) return;
    const question = state.questions[Number(card.dataset.qindex)];
    if (!question) return;
    const target = event.target;
    if (target.dataset.field === "title") {
      question.title = target.value;
      markDirty();
    } else if (target.dataset.field === "description") {
      question.description = target.value;
      markDirty();
    } else if (target.dataset.optionLabel != null) {
      const option = question.options[Number(target.dataset.optionLabel)];
      if (option) option.label = target.value;
      markDirty();
    } else if (target.dataset.validation) {
      const field = target.dataset.validation;
      question.validation = question.validation || {};
      if (target.value === "" && field !== "max_length") {
        delete question.validation[field];
      } else {
        const number = Number(target.value);
        question.validation[field] = Number.isNaN(number) ? null : Math.trunc(number);
      }
      markDirty();
    }
  });

  questionList.addEventListener("change", (event) => {
    if (state.readonly) return;
    const card = event.target.closest("[data-qindex]");
    if (!card) return;
    const index = Number(card.dataset.qindex);
    const question = state.questions[index];
    const target = event.target;
    if (target.dataset.field === "required") {
      question.required = target.checked;
      markDirty();
      renderQuestions();
    } else if (target.dataset.multiMode) {
      question.validation = question.validation || {};
      if (target.value === "exact") {
        question.validation = { exact_selected: question.validation.exact_selected || 2 };
      } else {
        question.validation = {
          min_selected: question.validation.min_selected ?? 1,
          max_selected: question.validation.max_selected ?? Math.min(3, question.options.length),
        };
      }
      markDirty();
      renderQuestions();
    } else if (target.dataset.trim !== undefined) {
      question.validation = question.validation || {};
      question.validation.trim = target.checked;
      markDirty();
    } else if (target.dataset.numberInteger !== undefined) {
      question.validation = question.validation || { integer: true };
      question.validation.integer = target.checked;
      markDirty();
      renderQuestions();
    } else if (target.dataset.fallback !== undefined) {
      question.logic = question.logic || { fallback: { action: "next" }, rules: [] };
      question.logic.fallback = { action: target.value };
      if (!question.logic.rules.length && target.value === "next") {
        delete question.logic;
      }
      markDirty();
    }
  });

  questionList.addEventListener("click", (event) => {
    if (state.readonly) return;
    const card = event.target.closest("[data-qindex]");
    if (!card) return;
    const index = Number(card.dataset.qindex);
    const question = state.questions[index];
    if (!question) return;
    if (event.target.closest("[data-add-option]")) {
      question.options.push({ option_id: App.randomId("o_", 12), label: `选项 ${optionLetters(question.options.length)}` });
      markAndRender();
      return;
    }
    const removeOption = event.target.closest("[data-remove-option]");
    if (removeOption) {
      if (question.options.length <= 2) return;
      question.options.splice(Number(removeOption.dataset.removeOption), 1);
      markAndRender();
      return;
    }
    const move = event.target.closest("[data-move]");
    if (move) {
      const targetIndex = move.dataset.move === "up" ? index - 1 : index + 1;
      if (targetIndex < 0 || targetIndex >= state.questions.length) return;
      [state.questions[index], state.questions[targetIndex]] = [state.questions[targetIndex], state.questions[index]];
      pruneInvalidRules();
      markAndRender();
      return;
    }
    if (event.target.closest("[data-delete-question]")) {
      if (!window.confirm("确定删除这道题吗？")) return;
      state.questions.splice(index, 1);
      pruneInvalidRules();
      markAndRender();
      return;
    }
    if (event.target.closest("[data-add-rule]")) {
      openRuleModal(index);
      return;
    }
    const editRule = event.target.closest("[data-edit-rule]");
    if (editRule) {
      openRuleModal(index, Number(editRule.dataset.editRule));
      return;
    }
    const deleteRule = event.target.closest("[data-delete-rule]");
    if (deleteRule) {
      if (!question.logic) return;
      question.logic.rules.splice(Number(deleteRule.dataset.deleteRule), 1);
      if (!question.logic.rules.length && question.logic.fallback.action === "next") {
        delete question.logic;
      }
      markAndRender();
    }
  });

  addBar.addEventListener("click", (event) => {
    const button = event.target.closest("[data-add-type]");
    if (!button || state.readonly) return;
    addQuestion(button.dataset.addType);
  });

  ["surveyTitle", "surveyDescription", "allowAnonymous", "allowMultiple", "closesAt"].forEach((id) => {
    const node = document.getElementById(id);
    if (!node) return;
    node.addEventListener("input", () => {
      if (node.type === "checkbox") return;
      markDirty();
    });
    node.addEventListener("change", () => {
      if (!state.readonly) markDirty();
    });
  });

  saveButton.addEventListener("click", () => saveDraft());
  publishButton.addEventListener("click", publishSurvey);
  window.addEventListener("beforeunload", (event) => {
    if (!state.dirty) return;
    event.preventDefault();
    event.returnValue = "";
  });

  loadSurvey();
})();
