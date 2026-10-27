'use strict';

const mongoose = require('mongoose');

const { Schema } = mongoose;

const questionLibrarySchema = new Schema(
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
    name: {
      type: String,
      required: true,
      trim: true,
      minlength: 1,
      maxlength: 120,
    },
    description: {
      type: String,
      required: true,
      default: '',
      maxlength: 1000,
    },
    visibility: {
      type: String,
      required: true,
      enum: ['private', 'public'],
      default: 'private',
    },
  },
  {
    collection: 'question_libraries',
    timestamps: { createdAt: 'created_at', updatedAt: 'updated_at' },
    versionKey: false,
    strict: 'throw',
  },
);

questionLibrarySchema.index(
  { owner_id: 1, name: 1 },
  { unique: true, name: 'ux_libraries_owner_name' },
);
questionLibrarySchema.index(
  { owner_id: 1, updated_at: -1 },
  { name: 'ix_libraries_owner_updated' },
);
questionLibrarySchema.index(
  { visibility: 1, updated_at: -1 },
  { name: 'ix_libraries_visibility_updated' },
);

module.exports =
  mongoose.models.QuestionLibrary ||
  mongoose.model('QuestionLibrary', questionLibrarySchema);
