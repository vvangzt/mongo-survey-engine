'use strict';

const mongoose = require('mongoose');

const { Schema } = mongoose;
const {
  MAX_QUESTIONS,
  MAX_OPTIONS,
  MAX_TEXT_ANSWER_LENGTH,
  CONTENT_HASH_RE,
  QUESTION_ID_RE,
  OPTION_ID_RE,
  RULE_ID_RE,
  validateSurveyVersionSemantics,
} = require('./validation');
const { questionRefSchema } = require('./questionRef');

const optionSchema = new Schema(
  {
    option_id: {
      type: String,
      required: true,
      match: OPTION_ID_RE,
    },
    label: {
      type: String,
      required: true,
      trim: true,
      minlength: 1,
      maxlength: 500,
    },
  },
  { _id: false, strict: 'throw' },
);

const multiChoiceValidationSchema = new Schema(
  {
    min_selected: { type: Number, min: 0, max: MAX_OPTIONS, default: undefined },
    max_selected: { type: Number, min: 1, max: MAX_OPTIONS, default: undefined },
    exact_selected: {
      type: Number,
      min: 1,
      max: MAX_OPTIONS,
      default: undefined,
    },
  },
  { _id: false, strict: 'throw' },
);

const textValidationSchema = new Schema(
  {
    min_length: {
      type: Number,
      min: 0,
      max: MAX_TEXT_ANSWER_LENGTH,
      default: 0,
    },
    max_length: {
      type: Number,
      required: true,
      min: 1,
      max: MAX_TEXT_ANSWER_LENGTH,
    },
    trim: { type: Boolean, default: true },
  },
  { _id: false, strict: 'throw' },
);

const numberValidationSchema = new Schema(
  {
    integer: {
      type: Boolean,
      required: true,
      default: true,
    },
    min: { type: Number, default: undefined },
    max: { type: Number, default: undefined },
  },
  { _id: false, strict: 'throw' },
);

const fallbackActionSchema = new Schema(
  {
    action: {
      type: String,
      required: true,
      enum: ['next', 'end'],
    },
  },
  { _id: false, strict: 'throw' },
);

const conditionSchema = new Schema(
  {
    question_id: {
      type: String,
      required: true,
      match: QUESTION_ID_RE,
    },
    operator: {
      type: String,
      required: true,
      enum: [
        'eq',
        'neq',
        'in',
        'not_in',
        'includes_any',
        'includes_all',
        'includes_none',
        'equals_set',
        'selection_count_eq',
        'selection_count_gte',
        'selection_count_lte',
        'gt',
        'gte',
        'lt',
        'lte',
        'between',
      ],
    },
    value: {
      type: Schema.Types.Mixed,
      required: true,
    },
  },
  { _id: false, strict: 'throw' },
);

const conditionGroupSchema = new Schema(
  {
    mode: {
      type: String,
      required: true,
      enum: ['all', 'any'],
    },
    conditions: {
      type: [conditionSchema],
      required: true,
      validate: {
        validator: (value) => value.length >= 1 && value.length <= 50,
        message: 'conditions must contain 1..50 items',
      },
    },
  },
  { _id: false, strict: 'throw' },
);

const ruleActionSchema = new Schema(
  {
    action: {
      type: String,
      required: true,
      enum: ['goto', 'end'],
    },
    target_question_id: {
      type: String,
      match: QUESTION_ID_RE,
      required: function targetRequired() {
        return this.action === 'goto';
      },
    },
  },
  { _id: false, strict: 'throw' },
);

const jumpRuleSchema = new Schema(
  {
    rule_id: {
      type: String,
      required: true,
      match: RULE_ID_RE,
    },
    when: {
      type: conditionGroupSchema,
      required: true,
    },
    then: {
      type: ruleActionSchema,
      required: true,
      validate: {
        validator: (value) => {
          if (!value) return false;
          if (value.action === 'goto') {
            return typeof value.target_question_id === 'string';
          }
          if (value.action === 'end') {
            return value.target_question_id == null;
          }
          return false;
        },
        message: 'invalid jump action',
      },
    },
  },
  { _id: false, strict: 'throw' },
);

const jumpLogicSchema = new Schema(
  {
    fallback: {
      type: fallbackActionSchema,
      required: true,
    },
    rules: {
      type: [jumpRuleSchema],
      default: [],
      validate: {
        validator: (value) => value.length <= 50,
        message: 'at most 50 jump rules are allowed',
      },
    },
  },
  { _id: false, strict: 'throw' },
);

const questionBaseSchema = new Schema(
  {
    question_id: {
      type: String,
      required: true,
      match: QUESTION_ID_RE,
    },
    title: {
      type: String,
      required: true,
      trim: true,
      minlength: 1,
      maxlength: 500,
    },
    description: {
      type: String,
      maxlength: 2000,
    },
    required: {
      type: Boolean,
      required: true,
      default: false,
    },
    logic: {
      type: jumpLogicSchema,
      default: undefined,
    },
    question_ref: {
      type: questionRefSchema,
      default: undefined,
    },
  },
  {
    _id: false,
    discriminatorKey: 'type',
    strict: 'throw',
  },
);

const choiceOptionsPath = {
  type: [optionSchema],
  required: true,
  validate: {
    validator: (value) =>
      Array.isArray(value) &&
      value.length >= 2 &&
      value.length <= MAX_OPTIONS,
    message: `a choice question needs 2..${MAX_OPTIONS} options`,
  },
};

const singleChoiceQuestionSchema = new Schema(
  {
    options: choiceOptionsPath,
  },
  { _id: false, strict: 'throw' },
);

const multiChoiceQuestionSchema = new Schema(
  {
    options: choiceOptionsPath,
    validation: {
      type: multiChoiceValidationSchema,
      required: true,
    },
  },
  { _id: false, strict: 'throw' },
);

const textQuestionSchema = new Schema(
  {
    validation: {
      type: textValidationSchema,
      required: true,
    },
  },
  { _id: false, strict: 'throw' },
);

const numberQuestionSchema = new Schema(
  {
    validation: {
      type: numberValidationSchema,
      required: true,
    },
  },
  { _id: false, strict: 'throw' },
);

questionBaseSchema.discriminator('single_choice', singleChoiceQuestionSchema);
questionBaseSchema.discriminator('multi_choice', multiChoiceQuestionSchema);
questionBaseSchema.discriminator('text', textQuestionSchema);
questionBaseSchema.discriminator('number', numberQuestionSchema);

const surveyVersionSchema = new Schema(
  {
    schema_version: {
      type: Number,
      required: true,
      default: 1,
      enum: [1],
      immutable: true,
    },
    survey_id: {
      type: Schema.Types.ObjectId,
      ref: 'Survey',
      required: true,
    },
    version_no: {
      type: Number,
      required: true,
      min: 1,
    },
    state: {
      type: String,
      required: true,
      enum: ['draft', 'published'],
      default: 'draft',
    },
    content_schema_version: {
      type: Number,
      required: true,
      enum: [1, 2],
      default: 1,
    },
    revision: {
      type: Number,
      required: true,
      min: 1,
      default: 1,
    },
    questions: {
      type: [questionBaseSchema],
      required: true,
      validate: {
        validator: (value) =>
          Array.isArray(value) &&
          value.length >= 1 &&
          value.length <= MAX_QUESTIONS,
        message: `questions must contain 1..${MAX_QUESTIONS} items`,
      },
    },
    created_by: {
      type: Schema.Types.ObjectId,
      ref: 'User',
      required: true,
    },
    published_at: {
      type: Date,
      default: null,
    },
    content_hash: {
      type: String,
      match: CONTENT_HASH_RE,
      default: null,
    },
  },
  {
    collection: 'survey_versions',
    timestamps: { createdAt: 'created_at', updatedAt: 'updated_at' },
    versionKey: false,
    strict: 'throw',
  },
);

surveyVersionSchema.index(
  { survey_id: 1, version_no: 1 },
  { unique: true, name: 'ux_versions_survey_version_no' },
);
surveyVersionSchema.index(
  { survey_id: 1, state: 1 },
  { name: 'ix_versions_survey_state' },
);

surveyVersionSchema.pre('validate', function validateSemantics(next) {
  try {
    validateSurveyVersionSemantics(this);
    next();
  } catch (error) {
    next(error);
  }
});

module.exports =
  mongoose.models.SurveyVersion ||
  mongoose.model('SurveyVersion', surveyVersionSchema);
