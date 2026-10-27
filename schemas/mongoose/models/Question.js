'use strict';

const mongoose = require('mongoose');

const { Schema } = mongoose;
const { OBJECT_ID_RE } = require('./validation');

const QUESTION_TYPES = ['single_choice', 'multi_choice', 'text', 'number'];

const questionEntitySchema = new Schema(
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
    root_entity_id: {
      type: Schema.Types.ObjectId,
      ref: 'Question',
      required: true,
    },
    source_entity_id: {
      type: Schema.Types.ObjectId,
      ref: 'Question',
      default: null,
    },
    source_version_id: {
      type: Schema.Types.ObjectId,
      ref: 'QuestionVersion',
      default: null,
    },
    lineage_depth: {
      type: Number,
      required: true,
      default: 0,
      min: 0,
    },
    type: {
      type: String,
      required: true,
      enum: QUESTION_TYPES,
    },
    title: {
      type: String,
      required: true,
      trim: true,
      minlength: 1,
      maxlength: 500,
    },
    visibility: {
      type: String,
      required: true,
      enum: ['private', 'shared', 'public'],
      default: 'private',
    },
    latest_version_id: {
      type: Schema.Types.ObjectId,
      ref: 'QuestionVersion',
      required: true,
    },
    latest_version_no: {
      type: Number,
      required: true,
      min: 1,
    },
    version_count: {
      type: Number,
      required: true,
      min: 1,
    },
    deleted_at: {
      type: Date,
      default: null,
    },
  },
  {
    collection: 'questions',
    timestamps: { createdAt: 'created_at', updatedAt: 'updated_at' },
    versionKey: false,
    strict: 'throw',
  },
);

questionEntitySchema.index(
  { owner_id: 1, updated_at: -1 },
  { name: 'ix_questions_owner_updated' },
);
questionEntitySchema.index(
  { root_entity_id: 1 },
  { name: 'ix_questions_root' },
);
questionEntitySchema.index(
  { owner_id: 1, type: 1, deleted_at: 1 },
  { name: 'ix_questions_owner_type_deleted' },
);

questionEntitySchema.pre('validate', function validateLineage(next) {
  try {
    if (
      this.source_entity_id == null &&
      this.source_version_id != null
    ) {
      throw new Error(
        'source_version_id requires source_entity_id',
      );
    }
    if (
      String(this.root_entity_id) === String(this.source_entity_id) &&
      this.source_entity_id != null
    ) {
      throw new Error('a question cannot be derived from itself');
    }
    if (this.lineage_depth === 0 && this.source_entity_id != null) {
      throw new Error('a derived question must have lineage_depth > 0');
    }
    if (
      this.latest_version_no !== this.version_count &&
      this.version_count < 1
    ) {
      throw new Error('version_count must be at least 1');
    }
    if (ObjectIdString(this.owner_id) === null) {
      throw new Error('owner_id must be an ObjectId');
    }
    next();
  } catch (error) {
    next(error);
  }
});

function ObjectIdString(value) {
  if (value == null) {
    return null;
  }
  const text = String(value);
  return OBJECT_ID_RE.test(text) ? text : null;
}

module.exports =
  mongoose.models.Question ||
  mongoose.model('Question', questionEntitySchema);
