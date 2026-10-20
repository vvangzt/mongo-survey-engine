'use strict';

const mongoose = require('mongoose');

const { Schema } = mongoose;
const { SLUG_RE } = require('./validation');

const surveySchema = new Schema(
  {
    schema_version: {
      type: Number,
      required: true,
      default: 1,
      enum: [1],
      immutable: true,
    },
    owner_id: {
      type: Schema.Types.ObjectId,
      ref: 'User',
      required: true,
    },
    slug: {
      type: String,
      required: true,
      trim: true,
      minlength: 6,
      maxlength: 63,
      match: SLUG_RE,
    },
    title: {
      type: String,
      required: true,
      trim: true,
      minlength: 1,
      maxlength: 300,
    },
    description: {
      type: String,
      required: true,
      default: '',
      maxlength: 5000,
    },
    status: {
      type: String,
      required: true,
      enum: ['draft', 'published', 'closed'],
      default: 'draft',
    },
    allow_anonymous: {
      type: Boolean,
      required: true,
      default: false,
    },
    allow_multiple_responses: {
      type: Boolean,
      required: true,
      default: true,
    },
    opens_at: {
      type: Date,
      default: null,
    },
    closes_at: {
      type: Date,
      default: null,
    },
    current_draft_version_id: {
      type: Schema.Types.ObjectId,
      ref: 'SurveyVersion',
      default: null,
    },
    published_version_id: {
      type: Schema.Types.ObjectId,
      ref: 'SurveyVersion',
      default: null,
    },
    last_version_no: {
      type: Number,
      required: true,
      default: 0,
      min: 0,
    },
    published_at: {
      type: Date,
      default: null,
    },
    closed_at: {
      type: Date,
      default: null,
    },
    deleted_at: {
      type: Date,
      default: null,
    },
  },
  {
    collection: 'surveys',
    timestamps: { createdAt: 'created_at', updatedAt: 'updated_at' },
    versionKey: false,
    strict: 'throw',
  },
);

surveySchema.index(
  { slug: 1 },
  { unique: true, name: 'ux_surveys_slug' },
);
surveySchema.index(
  { owner_id: 1, created_at: -1 },
  { name: 'ix_surveys_owner_created' },
);
surveySchema.index(
  { status: 1, closes_at: 1 },
  { name: 'ix_surveys_status_close' },
);
surveySchema.index(
  { published_version_id: 1 },
  { name: 'ix_surveys_published_version' },
);

surveySchema.pre('validate', function validateLifecycle(next) {
  try {
    if (this.opens_at && this.closes_at && this.opens_at >= this.closes_at) {
      throw new Error('opens_at must be earlier than closes_at');
    }
    if (
      this.status === 'published' &&
      (!this.published_version_id || !this.published_at)
    ) {
      throw new Error(
        'a published survey requires published_version_id and published_at',
      );
    }
    if (this.status === 'closed' && !this.published_version_id) {
      throw new Error('a closed survey must retain its published version');
    }
    next();
  } catch (error) {
    next(error);
  }
});

module.exports =
  mongoose.models.Survey || mongoose.model('Survey', surveySchema);
