'use strict';

const mongoose = require('mongoose');

const { Schema } = mongoose;
const {
  MAX_QUESTIONS,
  MAX_OPTIONS,
  OPTION_ID_RE,
  QUESTION_ID_RE,
} = require('./validation');

const optionCountSchema = new Schema(
  {
    option_id: {
      type: String,
      required: true,
      match: OPTION_ID_RE,
    },
    count: {
      type: Number,
      required: true,
      min: 0,
    },
  },
  { _id: false, strict: 'throw' },
);

const numericStatsSchema = new Schema(
  {
    sum: { type: Number, required: true },
    avg: { type: Number, required: true },
    min: { type: Number, required: true },
    max: { type: Number, required: true },
  },
  { _id: false, strict: 'throw' },
);

const questionStatsBaseSchema = new Schema(
  {
    question_id: {
      type: String,
      required: true,
      match: QUESTION_ID_RE,
    },
    answered_count: {
      type: Number,
      required: true,
      min: 0,
    },
  },
  {
    _id: false,
    discriminatorKey: 'question_type',
    strict: 'throw',
  },
);

questionStatsBaseSchema.discriminator(
  'single_choice',
  new Schema(
    {
      option_counts: {
        type: [optionCountSchema],
        required: true,
        validate: {
          validator: (value) => value.length <= MAX_OPTIONS,
          message: `at most ${MAX_OPTIONS} option counts are allowed`,
        },
      },
    },
    { _id: false, strict: 'throw' },
  ),
);

questionStatsBaseSchema.discriminator(
  'multi_choice',
  new Schema(
    {
      option_counts: {
        type: [optionCountSchema],
        required: true,
        validate: {
          validator: (value) => value.length <= MAX_OPTIONS,
          message: `at most ${MAX_OPTIONS} option counts are allowed`,
        },
      },
    },
    { _id: false, strict: 'throw' },
  ),
);

questionStatsBaseSchema.discriminator(
  'text',
  new Schema({}, { _id: false, strict: 'throw' }),
);

questionStatsBaseSchema.discriminator(
  'number',
  new Schema(
    {
      numeric_stats: {
        type: numericStatsSchema,
        default: null,
      },
    },
    { _id: false, strict: 'throw' },
  ),
);

const surveyStatSnapshotSchema = new Schema(
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
    response_count: {
      type: Number,
      required: true,
      min: 0,
    },
    questions: {
      type: [questionStatsBaseSchema],
      required: true,
      validate: {
        validator: (value) =>
          Array.isArray(value) &&
          value.length >= 1 &&
          value.length <= MAX_QUESTIONS,
        message: `questions must contain 1..${MAX_QUESTIONS} items`,
      },
    },
    latest_submitted_at: {
      type: Date,
      default: null,
    },
    computed_at: {
      type: Date,
      required: true,
    },
  },
  {
    collection: 'survey_stat_snapshots',
    versionKey: false,
    strict: 'throw',
  },
);

surveyStatSnapshotSchema.index(
  { survey_id: 1, survey_version_id: 1 },
  { unique: true, name: 'ux_stats_survey_version' },
);

surveyStatSnapshotSchema.pre('validate', function validateStats(next) {
  try {
    const questionIds = this.questions.map((question) => question.question_id);
    if (new Set(questionIds).size !== questionIds.length) {
      throw new Error('question_id values must be unique in a stat snapshot');
    }

    for (const question of this.questions) {
      if (question.answered_count > this.response_count) {
        throw new Error(
          `${question.question_id}: answered_count cannot exceed response_count`,
        );
      }
      if (
        (question.question_type === 'single_choice' ||
          question.question_type === 'multi_choice') &&
        Array.isArray(question.option_counts)
      ) {
        const optionIds = question.option_counts.map((item) => item.option_id);
        if (new Set(optionIds).size !== optionIds.length) {
          throw new Error(
            `${question.question_id}: duplicate option_id in option_counts`,
          );
        }
      }
      if (question.question_type === 'number') {
        const stats = question.numeric_stats;
        if (question.answered_count === 0 && stats != null) {
          throw new Error(
            `${question.question_id}: numeric_stats must be null when unanswered`,
          );
        }
        if (question.answered_count > 0 && stats == null) {
          throw new Error(
            `${question.question_id}: numeric_stats are required for answered questions`,
          );
        }
        if (stats != null && stats.min > stats.max) {
          throw new Error(`${question.question_id}: numeric min exceeds max`);
        }
      }
    }
    next();
  } catch (error) {
    next(error);
  }
});

module.exports =
  mongoose.models.SurveyStatSnapshot ||
  mongoose.model('SurveyStatSnapshot', surveyStatSnapshotSchema);
