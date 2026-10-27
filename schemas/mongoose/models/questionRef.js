'use strict';

const mongoose = require('mongoose');

const { Schema } = mongoose;

/**
 * Pointer from a survey-embedded question (or a stored answer) to the shared
 * question library.
 *
 * - `entity_id` is the stable cross-survey identity of the question.
 * - `version_id` is the immutable content version the survey pinned.
 *
 * Both fields are optional on the surrounding documents so phase-1 data, which
 * has no library reference at all, stays valid.
 */
const questionRefSchema = new Schema(
  {
    entity_id: {
      type: Schema.Types.ObjectId,
      ref: 'Question',
      required: true,
    },
    version_id: {
      type: Schema.Types.ObjectId,
      ref: 'QuestionVersion',
      required: true,
    },
  },
  { _id: false, strict: 'throw' },
);

module.exports = { questionRefSchema };
