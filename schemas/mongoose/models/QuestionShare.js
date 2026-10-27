'use strict';

const mongoose = require('mongoose');

const { Schema } = mongoose;

const questionShareSchema = new Schema(
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
    },
    grantee_id: {
      type: Schema.Types.ObjectId,
      ref: 'User',
      required: true,
    },
    permission: {
      type: String,
      required: true,
      enum: ['view', 'use'],
      default: 'use',
    },
    granted_by: {
      type: Schema.Types.ObjectId,
      ref: 'User',
      required: true,
    },
  },
  {
    collection: 'question_shares',
    timestamps: { createdAt: 'created_at', updatedAt: false },
    versionKey: false,
    strict: 'throw',
  },
);

questionShareSchema.index(
  { entity_id: 1, grantee_id: 1 },
  { unique: true, name: 'ux_shares_entity_grantee' },
);
questionShareSchema.index(
  { grantee_id: 1, created_at: -1 },
  { name: 'ix_shares_grantee_created' },
);

questionShareSchema.pre('validate', function validateSharing(next) {
  try {
    if (String(this.grantee_id) === String(this.granted_by)) {
      throw new Error('the owner does not need a share record');
    }
    next();
  } catch (error) {
    next(error);
  }
});

module.exports =
  mongoose.models.QuestionShare ||
  mongoose.model('QuestionShare', questionShareSchema);
