'use strict';

const mongoose = require('mongoose');

const { Schema } = mongoose;
const { CONTENT_HASH_RE } = require('./validation');
const { contentBaseSchema, hashContent } = require('./questionContent');

/**
 * Immutable content snapshot of a question.
 *
 * There is no code path in the application that updates a version document;
 * editing a question inserts a new version with `version_no + 1` and points
 * `parent_version_id` at the previous one (v1 -> v2 -> v3).
 */
const questionVersionSchema = new Schema(
  {
    schema_version: {
      type: Number,
      required: true,
      default: 1,
      enum: [1],
      immutable: true,
    },
    entity_id: {
      type: Schema.Types.ObjectId,
      ref: 'Question',
      required: true,
      immutable: true,
    },
    version_no: {
      type: Number,
      required: true,
      min: 1,
      immutable: true,
    },
    parent_version_id: {
      type: Schema.Types.ObjectId,
      ref: 'QuestionVersion',
      default: null,
    },
    restored_from_version_id: {
      type: Schema.Types.ObjectId,
      ref: 'QuestionVersion',
      default: null,
    },
    content: {
      type: contentBaseSchema,
      required: true,
    },
    content_hash: {
      type: String,
      required: true,
      match: CONTENT_HASH_RE,
    },
    created_by: {
      type: Schema.Types.ObjectId,
      ref: 'User',
      required: true,
    },
    legacy_key: {
      type: String,
      default: null,
      maxlength: 200,
    },
  },
  {
    collection: 'question_versions',
    timestamps: { createdAt: 'created_at', updatedAt: false },
    versionKey: false,
    strict: 'throw',
  },
);

questionVersionSchema.index(
  { entity_id: 1, version_no: 1 },
  { unique: true, name: 'ux_qversions_entity_version_no' },
);
questionVersionSchema.index(
  { entity_id: 1, created_at: -1 },
  { name: 'ix_qversions_entity_created' },
);
questionVersionSchema.index(
  { parent_version_id: 1 },
  { name: 'ix_qversions_parent' },
);
questionVersionSchema.index(
  { legacy_key: 1 },
  {
    unique: true,
    name: 'ux_qversions_legacy_key',
    partialFilterExpression: { legacy_key: { $type: 'string' } },
  },
);

questionVersionSchema.pre('validate', function validateVersionChain(next) {
  try {
    if (this.version_no === 1 && this.parent_version_id != null) {
      throw new Error('the first version cannot have a parent');
    }
    if (this.version_no > 1 && this.parent_version_id == null) {
      throw new Error('a later version requires parent_version_id');
    }
    if (this.restored_from_version_id != null && this.parent_version_id == null) {
      throw new Error('restored versions require a parent version');
    }
    const actual = hashContent(this.content);
    if (actual !== this.content_hash) {
      throw new Error(
        `content_hash does not match the version content (${actual})`,
      );
    }
    next();
  } catch (error) {
    next(error);
  }
});

// Immutability guard: reject updates to any field except the derived hash
// metadata. Insert-only is enforced in the service layer, this is a safety net.
questionVersionSchema.pre('save', function forbidMutation(next) {
  if (!this.isNew) {
    next(new Error('question_versions are immutable; insert a new version'));
    return;
  }
  next();
});

module.exports =
  mongoose.models.QuestionVersion ||
  mongoose.model('QuestionVersion', questionVersionSchema);
