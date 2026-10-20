'use strict';

const SAFE_INT_MIN = -9007199254740991;
const SAFE_INT_MAX = 9007199254740991;
const MAX_QUESTIONS = 300;
const MAX_OPTIONS = 100;
const MAX_TEXT_ANSWER_LENGTH = 5000;
const MAX_CONDITIONS = 50;
const MAX_RULES = 50;

const OBJECT_ID_RE = /^[0-9a-fA-F]{24}$/;
const QUESTION_ID_RE = /^q_[A-Za-z0-9_-]{8,64}$/;
const OPTION_ID_RE = /^o_[A-Za-z0-9_-]{8,64}$/;
const RULE_ID_RE = /^r_[A-Za-z0-9_-]{8,64}$/;
const SLUG_RE = /^[a-z0-9](?:[a-z0-9-]{4,61}[a-z0-9])$/;
const SUBMISSION_TOKEN_RE = /^[A-Za-z0-9_-]{16,128}$/;
const CONTENT_HASH_RE = /^[a-f0-9]{64}$/;

const SINGLE_OPS = new Set(['eq', 'neq', 'in', 'not_in']);
const MULTI_LIST_OPS = new Set([
  'includes_any',
  'includes_all',
  'includes_none',
  'equals_set',
]);
const MULTI_COUNT_OPS = new Set([
  'selection_count_eq',
  'selection_count_gte',
  'selection_count_lte',
]);
const NUMBER_COMPARE_OPS = new Set(['eq', 'neq', 'gt', 'gte', 'lt', 'lte']);

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

function plain(document) {
  if (document && typeof document.toObject === 'function') {
    return document.toObject({ depopulate: true, virtuals: false });
  }
  return document;
}

function isSafeInteger(value) {
  return Number.isSafeInteger(value);
}

function isFiniteNumber(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

function assertUnique(values, label) {
  const seen = new Set();
  for (const value of values) {
    assert(!seen.has(value), `${label} must be unique: ${value}`);
    seen.add(value);
  }
}

function validateOptions(question) {
  assert(
    Array.isArray(question.options),
    `${question.question_id}: options must be an array`,
  );
  assert(
    question.options.length >= 2 && question.options.length <= MAX_OPTIONS,
    `${question.question_id}: a choice question needs 2..${MAX_OPTIONS} options`,
  );
  for (const option of question.options) {
    assert(
      OPTION_ID_RE.test(option.option_id),
      `${question.question_id}: invalid option_id ${option.option_id}`,
    );
    assert(
      typeof option.label === 'string' &&
        option.label.trim().length >= 1 &&
        option.label.length <= 500,
      `${question.question_id}: option labels must be 1..500 characters`,
    );
  }
  assertUnique(
    question.options.map((option) => option.option_id),
    `${question.question_id}: option_id`,
  );
}

function validateChoiceValue(source, operator, value) {
  const validIds = new Set(source.options.map((option) => option.option_id));

  if (SINGLE_OPS.has(operator)) {
    if (operator === 'eq' || operator === 'neq') {
      assert(
        typeof value === 'string' && validIds.has(value),
        `${source.question_id}: ${operator} requires an existing option_id`,
      );
      return;
    }
    assert(
      Array.isArray(value) &&
        value.length > 0 &&
        value.every((item) => typeof item === 'string' && validIds.has(item)),
      `${source.question_id}: ${operator} requires a non-empty array of known option_ids`,
    );
    assertUnique(value, `${source.question_id}: condition value`);
    return;
  }

  throw new Error(
    `${source.question_id}: operator ${operator} is not valid for single_choice`,
  );
}

function validateMultiValue(source, operator, value) {
  const validIds = new Set(source.options.map((option) => option.option_id));

  if (MULTI_LIST_OPS.has(operator)) {
    assert(
      Array.isArray(value) &&
        value.length > 0 &&
        value.every((item) => typeof item === 'string' && validIds.has(item)),
      `${source.question_id}: ${operator} requires a non-empty array of known option_ids`,
    );
    assertUnique(value, `${source.question_id}: condition value`);
    return;
  }

  if (MULTI_COUNT_OPS.has(operator)) {
    assert(
      isSafeInteger(value) && value >= 0 && value <= source.options.length,
      `${source.question_id}: ${operator} requires an integer in [0, ${source.options.length}]`,
    );
    return;
  }

  throw new Error(
    `${source.question_id}: operator ${operator} is not valid for multi_choice`,
  );
}

function validateNumberValue(source, operator, value) {
  if (NUMBER_COMPARE_OPS.has(operator)) {
    assert(
      isFiniteNumber(value),
      `${source.question_id}: ${operator} requires a finite number`,
    );
    return;
  }

  if (operator === 'between') {
    assert(
      Array.isArray(value) &&
        value.length === 2 &&
        value.every(isFiniteNumber) &&
        value[0] <= value[1],
      `${source.question_id}: between requires an ordered [low, high] number pair`,
    );
    return;
  }

  throw new Error(
    `${source.question_id}: operator ${operator} is not valid for number`,
  );
}

function validateCondition(source, operator, value) {
  if (!source) {
    throw new Error('condition references an unknown source question');
  }
  if (source.type === 'single_choice') {
    validateChoiceValue(source, operator, value);
    return;
  }
  if (source.type === 'multi_choice') {
    validateMultiValue(source, operator, value);
    return;
  }
  if (source.type === 'number') {
    validateNumberValue(source, operator, value);
    return;
  }
  throw new Error(
    `operator ${operator} is not valid for question type ${source.type}`,
  );
}

function validateQuestionLogic(question, index, positions, questions) {
  const logic = question.logic;
  if (!logic) return;

  assert(
    logic.fallback && ['next', 'end'].includes(logic.fallback.action),
    `${question.question_id}: logic.fallback.action must be next or end`,
  );
  assert(
    Array.isArray(logic.rules) && logic.rules.length <= MAX_RULES,
    `${question.question_id}: at most ${MAX_RULES} jump rules are allowed`,
  );

  const ruleIds = new Set();
  for (const rule of logic.rules) {
    assert(
      RULE_ID_RE.test(rule.rule_id),
      `${question.question_id}: invalid rule_id ${rule.rule_id}`,
    );
    assert(
      !ruleIds.has(rule.rule_id),
      `${question.question_id}: duplicate rule_id ${rule.rule_id}`,
    );
    ruleIds.add(rule.rule_id);

    assert(
      rule.when && ['all', 'any'].includes(rule.when.mode),
      `${rule.rule_id}: when.mode must be all or any`,
    );
    assert(
      Array.isArray(rule.when.conditions) &&
        rule.when.conditions.length >= 1 &&
        rule.when.conditions.length <= MAX_CONDITIONS,
      `${rule.rule_id}: when.conditions must contain 1..${MAX_CONDITIONS} items`,
    );

    for (const condition of rule.when.conditions) {
      assert(
        positions.has(condition.question_id),
        `${rule.rule_id}: condition references unknown question ${condition.question_id}`,
      );
      const sourceIndex = positions.get(condition.question_id);
      assert(
        sourceIndex <= index,
        `${rule.rule_id}: conditions may reference only the current or an earlier question`,
      );
      validateCondition(
        questions[sourceIndex],
        condition.operator,
        condition.value,
      );
    }

    assert(rule.then, `${rule.rule_id}: then action is required`);
    if (rule.then.action === 'goto') {
      const target = rule.then.target_question_id;
      assert(
        positions.has(target),
        `${rule.rule_id}: goto target ${target} does not exist`,
      );
      assert(
        positions.get(target) > index,
        `${rule.rule_id}: goto targets must point forward (cycles are forbidden)`,
      );
    } else {
      assert(
        rule.then.action === 'end',
        `${rule.rule_id}: action must be goto or end`,
      );
    }
  }
}

function validateQuestion(question, index, positions, questions) {
  assert(
    QUESTION_ID_RE.test(question.question_id),
    `invalid question_id: ${question.question_id}`,
  );
  assert(
    typeof question.title === 'string' &&
      question.title.trim().length >= 1 &&
      question.title.length <= 500,
    `${question.question_id}: title must be 1..500 characters`,
  );
  assert(
    typeof question.required === 'boolean',
    `${question.question_id}: required must be boolean`,
  );

  if (question.type === 'single_choice' || question.type === 'multi_choice') {
    validateOptions(question);
  }

  if (question.type === 'multi_choice') {
    const rules = question.validation || {};
    assert(
      rules.exact_selected == null ||
        (rules.min_selected == null && rules.max_selected == null),
      `${question.question_id}: exact_selected conflicts with min/max`,
    );
    assert(
      rules.min_selected == null ||
        (Number.isInteger(rules.min_selected) && rules.min_selected >= 0),
      `${question.question_id}: invalid min_selected`,
    );
    assert(
      rules.max_selected == null ||
        (Number.isInteger(rules.max_selected) && rules.max_selected >= 1),
      `${question.question_id}: invalid max_selected`,
    );
    assert(
      rules.exact_selected == null ||
        (Number.isInteger(rules.exact_selected) && rules.exact_selected >= 1),
      `${question.question_id}: invalid exact_selected`,
    );
    assert(
      rules.min_selected == null ||
        rules.max_selected == null ||
        rules.min_selected <= rules.max_selected,
      `${question.question_id}: min_selected must be <= max_selected`,
    );
    for (const value of [
      rules.min_selected,
      rules.max_selected,
      rules.exact_selected,
    ]) {
      assert(
        value == null || value <= question.options.length,
        `${question.question_id}: selection constraint exceeds option count`,
      );
    }
  }

  if (question.type === 'text') {
    const rules = question.validation || {};
    assert(
      Number.isInteger(rules.min_length) &&
        rules.min_length >= 0 &&
        rules.min_length <= MAX_TEXT_ANSWER_LENGTH,
      `${question.question_id}: invalid min_length`,
    );
    assert(
      Number.isInteger(rules.max_length) &&
        rules.max_length >= 1 &&
        rules.max_length <= MAX_TEXT_ANSWER_LENGTH,
      `${question.question_id}: invalid max_length`,
    );
    assert(
      rules.min_length <= rules.max_length,
      `${question.question_id}: min_length must be <= max_length`,
    );
  }

  if (question.type === 'number') {
    const rules = question.validation || {};
    assert(
      typeof rules.integer === 'boolean',
      `${question.question_id}: integer must be boolean`,
    );
    assert(
      rules.min == null || isFiniteNumber(rules.min),
      `${question.question_id}: invalid numeric min`,
    );
    assert(
      rules.max == null || isFiniteNumber(rules.max),
      `${question.question_id}: invalid numeric max`,
    );
    assert(
      rules.min == null || rules.max == null || rules.min <= rules.max,
      `${question.question_id}: numeric min must be <= max`,
    );
  }

  if (
    question.type !== 'single_choice' &&
    question.type !== 'multi_choice' &&
    question.type !== 'text' &&
    question.type !== 'number'
  ) {
    throw new Error(`unsupported question type: ${question.type}`);
  }

  validateQuestionLogic(question, index, positions, questions);
}

function validateSurveyVersionSemantics(document) {
  const version = plain(document);
  assert(
    ['draft', 'published'].includes(version.state),
    'version.state must be draft or published',
  );
  assert(
    Array.isArray(version.questions) &&
      version.questions.length >= 1 &&
      version.questions.length <= MAX_QUESTIONS,
    `questions must contain 1..${MAX_QUESTIONS} items`,
  );

  const positions = new Map();
  for (let index = 0; index < version.questions.length; index += 1) {
    const question = version.questions[index];
    assert(
      !positions.has(question.question_id),
      `duplicate question_id: ${question.question_id}`,
    );
    positions.set(question.question_id, index);
  }

  for (let index = 0; index < version.questions.length; index += 1) {
    validateQuestion(version.questions[index], index, positions, version.questions);
  }

  if (version.state === 'published') {
    assert(
      version.published_at instanceof Date ||
        typeof version.published_at === 'string',
      'a published version requires published_at',
    );
    assert(
      typeof version.content_hash === 'string' &&
        CONTENT_HASH_RE.test(version.content_hash),
      'a published version requires a 64-character content_hash',
    );
  }
  return true;
}

module.exports = {
  SAFE_INT_MIN,
  SAFE_INT_MAX,
  MAX_QUESTIONS,
  MAX_OPTIONS,
  MAX_TEXT_ANSWER_LENGTH,
  MAX_CONDITIONS,
  MAX_RULES,
  OBJECT_ID_RE,
  QUESTION_ID_RE,
  OPTION_ID_RE,
  RULE_ID_RE,
  SLUG_RE,
  SUBMISSION_TOKEN_RE,
  CONTENT_HASH_RE,
  assert,
  assertUnique,
  isSafeInteger,
  isFiniteNumber,
  validateSurveyVersionSemantics,
};
