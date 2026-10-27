(function () {
  "use strict";

  const { escapeHtml, randomId, showToast } = window.App;

  const TYPE_LABELS = {
    single_choice: "单选题",
    multi_choice: "多选题",
    text: "文本题",
    number: "数字题",
  };

  function optionRow(option) {
    return `
      <div class="qv-option" data-option-id="${escapeHtml(option.option_id)}">
        <input class="qv-option-label" maxlength="500" value="${escapeHtml(option.label)}" placeholder="选项文字">
        <button class="btn ghost small" type="button" data-remove-option>删除</button>
      </div>`;
  }

  function renderOptions(container, options) {
    container.innerHTML = options.map(optionRow).join("");
    container.querySelectorAll("[data-remove-option]").forEach((button) => {
      button.addEventListener("click", () => {
        const rows = container.querySelectorAll(".qv-option");
        if (rows.length <= 2) {
          showToast("选择题至少需要 2 个选项", "error");
          return;
        }
        button.closest(".qv-option").remove();
      });
    });
  }

  function buildForm(container, initial = {}) {
    const content = initial.content || {};
    const type = content.type || "single_choice";
    const options = (content.options || []).slice();
    const validation = content.validation || {};

    container.innerHTML = `
      <div class="form-grid">
        <div class="field">
          <label>题型</label>
          <select class="qv-type">
            ${Object.entries(TYPE_LABELS)
              .map(
                ([value, label]) =>
                  `<option value="${value}"${value === type ? " selected" : ""}>${label}</option>`
              )
              .join("")}
          </select>
        </div>
        <label class="checkbox-row">
          <input class="qv-required" type="checkbox"${content.required ? " checked" : ""}>
          <span>必答题</span>
        </label>
        <div class="field span-2">
          <label>题目</label>
          <input class="qv-title" maxlength="500" value="${escapeHtml(content.title || "")}" placeholder="例如：你的年龄（周岁）">
        </div>
        <div class="field span-2">
          <label>说明（可选）</label>
          <textarea class="qv-description" maxlength="2000" placeholder="补充说明">${escapeHtml(content.description || "")}</textarea>
        </div>
        <div class="span-2 qv-options-block">
          <label>选项</label>
          <div class="qv-options"></div>
          <button class="btn ghost small" type="button" data-add-option>添加选项</button>
        </div>
        <div class="span-2 qv-validation-block"></div>
      </div>`;

    const typeSelect = container.querySelector(".qv-type");
    const optionsBlock = container.querySelector(".qv-options-block");
    const optionsBox = container.querySelector(".qv-options");
    const validationBox = container.querySelector(".qv-validation-block");

    if (options.length < 2) {
      options.push(
        { option_id: randomId("o_opt_", 10), label: "" },
        { option_id: randomId("o_opt_", 10), label: "" }
      );
    }
    renderOptions(optionsBox, options);

    container.querySelector("[data-add-option]").addEventListener("click", () => {
      const box = container.querySelector(".qv-options");
      box.insertAdjacentHTML(
        "beforeend",
        optionRow({ option_id: randomId("o_opt_", 10), label: "" })
      );
      box.querySelectorAll("[data-remove-option]").forEach((button) => {
        button.onclick = () => {
          if (box.querySelectorAll(".qv-option").length <= 2) {
            showToast("选择题至少需要 2 个选项", "error");
            return;
          }
          button.closest(".qv-option").remove();
        };
      });
    });

    function renderValidation() {
      const current = typeSelect.value;
      optionsBlock.classList.toggle("hidden", current === "text" || current === "number");
      if (current === "multi_choice") {
        validationBox.innerHTML = `
          <div class="form-grid">
            <div class="field"><label>最少选择</label>
              <input class="qv-min-selected" type="number" min="0" value="${validation.min_selected ?? ""}"></div>
            <div class="field"><label>最多选择</label>
              <input class="qv-max-selected" type="number" min="1" value="${validation.max_selected ?? ""}"></div>
          </div>`;
      } else if (current === "text") {
        validationBox.innerHTML = `
          <div class="form-grid">
            <div class="field"><label>最少字数</label>
              <input class="qv-min-length" type="number" min="0" max="5000" value="${validation.min_length ?? 0}"></div>
            <div class="field"><label>最多字数</label>
              <input class="qv-max-length" type="number" min="1" max="5000" value="${validation.max_length ?? 500}"></div>
          </div>`;
      } else if (current === "number") {
        validationBox.innerHTML = `
          <div class="form-grid">
            <div class="field"><label>最小值</label>
              <input class="qv-min" type="number" value="${validation.min ?? 0}"></div>
            <div class="field"><label>最大值</label>
              <input class="qv-max" type="number" value="${validation.max ?? 120}"></div>
            <label class="checkbox-row span-2">
              <input class="qv-integer" type="checkbox"${validation.integer === false ? "" : " checked"}>
              <span>必须是整数</span>
            </label>
          </div>`;
      } else {
        validationBox.innerHTML = "";
      }
    }

    typeSelect.addEventListener("change", renderValidation);
    renderValidation();

    return {
      read() {
        const current = typeSelect.value;
        const payload = {
          type: current,
          title: container.querySelector(".qv-title").value.trim(),
          description: container.querySelector(".qv-description").value.trim() || null,
          required: container.querySelector(".qv-required").checked,
        };
        if (current === "single_choice" || current === "multi_choice") {
          payload.options = Array.from(
            container.querySelectorAll(".qv-option")
          ).map((row) => ({
            option_id: row.dataset.optionId,
            label: row.querySelector(".qv-option-label").value.trim(),
          }));
        }
        if (current === "multi_choice") {
          payload.validation = {};
          const min = container.querySelector(".qv-min-selected").value;
          const max = container.querySelector(".qv-max-selected").value;
          if (min !== "") payload.validation.min_selected = Number(min);
          if (max !== "") payload.validation.max_selected = Number(max);
        } else if (current === "text") {
          payload.validation = {
            min_length: Number(container.querySelector(".qv-min-length").value || 0),
            max_length: Number(container.querySelector(".qv-max-length").value || 500),
            trim: true,
          };
        } else if (current === "number") {
          payload.validation = {
            integer: container.querySelector(".qv-integer").checked,
          };
          const min = container.querySelector(".qv-min").value;
          const max = container.querySelector(".qv-max").value;
          if (min !== "") payload.validation.min = Number(min);
          if (max !== "") payload.validation.max = Number(max);
        }
        if (!payload.title) {
          throw new Error("请填写题目");
        }
        if (payload.options && payload.options.some((option) => !option.label)) {
          throw new Error("每个选项都需要文字");
        }
        return payload;
      },
    };
  }

  window.QuestionForm = { buildForm, TYPE_LABELS };
})();
