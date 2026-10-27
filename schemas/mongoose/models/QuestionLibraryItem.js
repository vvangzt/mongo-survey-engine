'use strict';

const mongoose = require('mongoose');

const { Schema } = mongoose;

const questionLibraryItemSchema = new Schema(
  {
    schema_version: {
      type: Number,
      required: true,
      default: 1,
      enum: [1],
      immutable: true,
    },
    library_id: {
      type: Schema.Types.ObjectId,
      ref: 'QuestionLibrary',
      required: true,
    },
    entity_id: {
      type: Schema.Types.ObjectId,
      ref: 'Question',
      required: true,
    },
    added_by: {
      type: Schema.Types.ObjectId,
      ref: 'User',
      required: true,
    },
    note: {
      type: String,
      default: null,
      maxlength: 500,
    },
    tags: {
      type: [String],
      default: [],
      validate: [
        {
          validator: (value) => Array.isArray(value) && value.length <= 10,
          message: 'at most 10 tags are allowed',
        },
        {
          validator: (value) =>
            Array.isArray(value) &&
            value.every((tag) => typeof tag === 'string' && tag.length >= 1 && tag.length <= 32),
          message: 'each tag must be 1..32 characters',
        },
        {
          validator: (value) =>
            Array.isArray(value) && new Set(value).size === value.length,
          message: 'tags must not contain duplicates',
        },
      ],
    },
  },
  {
    collection: 'question_library_items',
    timestamps: { createdAt: 'added_at', updatedAt: false },
    versionKey: false,
    strict: 'throw',
  },
);

questionLibraryItemSchema.index(
  { library_id: 1, entity_id: 1 },
  { unique: true, name: 'ux_litems_library_entity' },
);
questionLibraryItemSchema.index(
  { library_id: 1, added_at: -1 },
  { name: 'ix_litems_library_added' },
);
questionLibraryItemSchema.index(
  { entity_id: 1 },
  { name: 'ix_litems_entity' },
);

module.exports =
  mongoose.models.QuestionLibraryItem ||
  mongoose.model('QuestionLibraryItem', questionLibraryItemSchema);
