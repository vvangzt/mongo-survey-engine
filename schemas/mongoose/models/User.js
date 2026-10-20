'use strict';

const mongoose = require('mongoose');

const { Schema } = mongoose;

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

const userSchema = new Schema(
  {
    schema_version: {
      type: Number,
      required: true,
      default: 1,
      enum: [1],
      immutable: true,
    },
    username: {
      type: String,
      required: true,
      trim: true,
      lowercase: true,
      minlength: 3,
      maxlength: 32,
      match: /^[a-z0-9_]{3,32}$/,
    },
    email: {
      type: String,
      required: true,
      trim: true,
      lowercase: true,
      minlength: 3,
      maxlength: 254,
      match: EMAIL_RE,
    },
    password_hash: {
      type: String,
      required: true,
      minlength: 20,
      maxlength: 255,
      select: false,
    },
    display_name: {
      type: String,
      required: true,
      trim: true,
      minlength: 1,
      maxlength: 80,
    },
    status: {
      type: String,
      required: true,
      enum: ['active', 'disabled'],
      default: 'active',
    },
    last_login_at: {
      type: Date,
      default: null,
    },
  },
  {
    collection: 'users',
    timestamps: { createdAt: 'created_at', updatedAt: 'updated_at' },
    versionKey: false,
    strict: 'throw',
  },
);

userSchema.index(
  { username: 1 },
  { unique: true, name: 'ux_users_username' },
);
userSchema.index(
  { email: 1 },
  { unique: true, name: 'ux_users_email' },
);

userSchema.set('toJSON', {
  transform(_doc, ret) {
    delete ret.password_hash;
    return ret;
  },
});

module.exports =
  mongoose.models.User || mongoose.model('User', userSchema);
