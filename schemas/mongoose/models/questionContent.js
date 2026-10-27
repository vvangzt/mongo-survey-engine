'use strict';

const crypto = require('node:crypto');
const mongoose = require('mongoose');

const { Schema } = mongoose;
const {
  MAX_OPTIONS,
  MAX_TEXT_ANSWER_LENGTH,
  OPTION_ID_RE,
  isFiniteNumber,
} = require('./validation');

/**
 * The versioned part of a question.
 *
 * Deliberately excludes `question_id` (an instance id inside one survey
 * version) and `logic` (jump rules depend on the survey's position), so the
 * same content can be inserted into any survey.
 *
 * This module is standalone on purpose: the library models must not depend on
 * the survey schema. `SurveyVersion.js` keeps its own inline copy for the
 * embedded question union.
 */

const optionSchema = new Schema(
  {
    option_id: { type: String, required: true, match: OPTION_ID_RE },
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
    integer: { type: Boolean, required: true, default: true },
    min: { type: Number, default: undefined },
    max: { type: Number, default: undefined },
  },
  { _id: false, strict: 'throw' },
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

const contentBaseSchema = new Schema(
  {
    title: {
      type: String,
      required: true,
      trim: true,
      minlength: 1,
      maxlength: 500,
    },
    description: { type: String, maxlength: 2000 },
    required: { type: Boolean, required: true, default: false },
  },
  {
    _id: false,
    discriminatorKey: 'type',
    strict: 'throw',
  },
);

contentBaseSchema.discriminator(
  'single_choice',
  new Schema({ options: choiceOptionsPath }, { _id: false, strict: 'throw' }),
);

contentBaseSchema.discriminator(
  'multi_choice',
  new Schema(
    {
      options: choiceOptionsPath,
      validation: { type: multiChoiceValidationSchema, required: true },
    },
    { _id: false, strict: 'throw' },
  ),
);

contentBaseSchema.discriminator(
  'text',
  new Schema(
    { validation: { type: textValidationSchema, required: true } },
    { _id: false, strict: 'throw' },
  ),
);

contentBaseSchema.discriminator(
  'number',
  new Schema(
    { validation: { type: numberValidationSchema, required: true } },
    { _id: false, strict: 'throw' },
  ),
);

/**
 * Canonical JSON used for the content hash.
 *
 * Must stay byte-identical with the Python implementation in
 * `schemas/pydantic/question_library.py` (`hash_content`):
 * null/undefined dropped, keys sorted at every level, compact separators,
 * non-ASCII kept as raw UTF-8.
 */
function canonicalJson(value) {
  if (value === null || value === undefined) {
    return 'null';
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJson(item)).join(',')}]`;
  }
  if (value instanceof Date) {
    return JSON.stringify(value.toISOString());
  }
  if (typeof value === 'object') {
    const plain =
      typeof value.toObject === 'function'
        ? value.toObject({ depopulate: true, virtuals: false })
        : value;
    const keys = Object.keys(plain)
      .filter((key) => plain[key] !== null && plain[key] !== undefined)
      .sort();
    return `{${keys
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(plain[key])}`)
      .join(',')}}`;
  }
  if (typeof value === 'number' && !isFiniteNumber(value)) {
    throw new Error('content contains a non-finite number');
  }
  return JSON.stringify(value);
}

function hashContent(content) {
  return crypto
    .createHash('sha256')
    .update(canonicalJson(content), 'utf8')
    .digest('hex');
}

module.exports = {
  canonicalJson,
  contentBaseSchema,
  contentDiscriminator: contentBaseSchema,
  hashContent,
  multiChoiceValidationSchema,
  numberValidationSchema,
  optionSchema,
  textValidationSchema,
};
