'use strict';

const mongoose = require('mongoose');

const { Schema } = mongoose;
const {
  MAX_QUESTIONS,
  MAX_OPTIONS,
  MAX_TEXT_ANSWER_LENGTH,
  OPTION_ID_RE,
  QUESTION_ID_RE,
  SUBMISSION_TOKEN_RE,
} = require('./validation');

const answerBaseSchema = new Schema(
  {
    question_id: {
      type: String,
      required: true,
      match: QUESTION_ID_RE,
    },
  },
  {
    _id: false,
    discriminatorKey: 'type',
    strict: 'throw',
  },
);

const singleChoiceAnswerSchema = new Schema(
  {
    option_ids: {
      type: [{ type: String, match: OPTION_ID_RE }],
      required: true,
      validate: {
        validator: (value) => Array.isArray(value) && value.length === 1,
        message: 'single_choice requires exactly one option_id',
      },
    },
  },
  { _id: false, strict: 'throw' },
);

const multiChoiceAnswerSchema = new Schema(
  {
    option_ids: {
      type: [{ type: String, match: OPTION_ID_RE }],
      required: true,
      validate: {
        validator: (value) =>
          Array.isArray(value) &&
          value.length >= 1 &&
          value.length <= MAX_OPTIONS &&
          new Set(value).size === value.length,
        message: `multi_choice requires 1..${MAX_OPTIONS} unique option_ids`,
      },
    },
  },
  { _id: false, strict: 'throw' },
);

const textAnswerSchema = new Schema(
  {
    text: {
      type: String,
      required: true,
      minlength: 1,
      maxlength: MAX_TEXT_ANSWER_LENGTH,
    },
  },
  { _id: false, strict: 'throw' },
);

const numberAnswerSchema = new Schema(
  {
    number: {
      type: Number,
      required: true,
      validate: {
        validator: (value) => Number.isFinite(value),
        message: 'number must be a finite integer or decimal',
      },
    },
  },
  { _id: false, strict: 'throw' },
);

answerBaseSchema.discriminator(
  'single_choice',
  singleChoiceAnswerSchema,
);
answerBaseSchema.discriminator('multi_choice', multiChoiceAnswerSchema);
answerBaseSchema.discriminator('text', textAnswerSchema);
answerBaseSchema.discriminator('number', numberAnswerSchema);

const responseSchema = new Schema(
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
    survey_version_id: {
      type: Schema.Types.ObjectId,
      ref: 'SurveyVersion',
      required: true,
    },
    respondent_id: {
      type: Schema.Types.ObjectId,
      ref: 'User',
      default: null,
    },
    is_anonymous: {
      type: Boolean,
      required: true,
    },
    submission_token: {
      type: String,
      required: true,
      match: SUBMISSION_TOKEN_RE,
    },
    answers: {
      type: [answerBaseSchema],
      default: [],
      validate: {
        validator: (value) =>
          Array.isArray(value) && value.length <= MAX_QUESTIONS,
        message: `a response may contain at most ${MAX_QUESTIONS} answers`,
      },
    },
    submitted_at: {
      type: Date,
      required: true,
      default: Date.now,
    },
  },
  {
    collection: 'responses',
    versionKey: false,
    strict: 'throw',
  },
);

responseSchema.index(
  { survey_id: 1, submission_token: 1 },
  { unique: true, name: 'ux_responses_survey_token' },
);
responseSchema.index(
  { survey_id: 1, submitted_at: -1 },
  { name: 'ix_responses_survey_submitted' },
);
responseSchema.index(
  { survey_id: 1, survey_version_id: 1, submitted_at: -1 },
  { name: 'ix_responses_survey_version_submitted' },
);
responseSchema.index(
  { survey_id: 1, survey_version_id: 1, 'answers.question_id': 1 },
  { name: 'ix_responses_survey_version_question' },
);
responseSchema.index(
  { survey_id: 1, respondent_id: 1 },
  {
    name: 'ix_responses_survey_respondent',
    partialFilterExpression: {
      respondent_id: { $type: 'objectId' },
    },
  },
);

responseSchema.pre('validate', function validateResponseEnvelope(next) {
  try {
    if (this.is_anonymous && this.respondent_id != null) {
      throw new Error('anonymous responses must not carry respondent_id');
    }
    if (!this.is_anonymous && this.respondent_id == null) {
      throw new Error('identified responses require respondent_id');
    }

    const questionIds = this.answers.map((answer) => answer.question_id);
    if (new Set(questionIds).size !== questionIds.length) {
      throw new Error('a response may answer each question at most once');
    }
    next();
  } catch (error) {
    next(error);
  }
});

module.exports =
  mongoose.models.Response || mongoose.model('Response', responseSchema);
