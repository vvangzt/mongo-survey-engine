'use strict';

const fs = require('node:fs');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '..');
const EXAMPLES = path.join(ROOT, 'examples');

// eslint-disable-next-line import/no-dynamic-require
const models = require(path.join(ROOT, 'schemas', 'mongoose', 'models'));

function load(name) {
  return JSON.parse(fs.readFileSync(path.join(EXAMPLES, name), 'utf8'));
}

function firstError(error) {
  if (error && Array.isArray(error.errors)) {
    return error.errors.map((item) => item.message).join('; ');
  }
  return error && error.message ? error.message : String(error);
}

async function expectRejected(label, doc) {
  try {
    await doc.validate();
  } catch (error) {
    console.log(`OK   rejected ${label}: ${firstError(error)}`);
    return;
  }
  throw new Error(`expected rejection for ${label}`);
}

async function main() {
  const user = new models.User(load('users.example.json'));
  const survey = new models.Survey(load('surveys.example.json'));
  const versionData = load('survey_versions.example.json');
  const version = new models.SurveyVersion(versionData);
  const anonymous = new models.Response(
    load('responses.anonymous.example.json'),
  );
  const identified = new models.Response(
    load('responses.identified-short-path.example.json'),
  );
  const snapshot = new models.SurveyStatSnapshot(
    load('survey_stat_snapshots.example.json'),
  );
  const question = new models.Question(load('questions.example.json'));
  const questionVersion = new models.QuestionVersion(
    load('question_versions.example.json'),
  );
  const share = new models.QuestionShare(load('question_shares.example.json'));
  const library = new models.QuestionLibrary(
    load('question_libraries.example.json'),
  );
  const libraryItem = new models.QuestionLibraryItem(
    load('question_library_items.example.json'),
  );
  const refVersion = new models.SurveyVersion(
    load('survey_versions.with_library_refs.example.json'),
  );
  const refResponse = new models.Response(
    load('responses.with_library_refs.example.json'),
  );

  await user.validate();
  await survey.validate();
  await version.validate();
  await anonymous.validate();
  await identified.validate();
  await snapshot.validate();
  await question.validate();
  await questionVersion.validate();
  await share.validate();
  await library.validate();
  await libraryItem.validate();
  await refVersion.validate();
  await refResponse.validate();

  console.log('OK   all Mongoose example documents validated');
  console.log(
    'OK   question discriminators:',
    version.questions.map((question) => question.type).join(', '),
  );
  console.log(
    'OK   answer discriminators:',
    anonymous.answers.map((answer) => answer.type).join(', '),
  );
  console.log(
    'OK   stat discriminators:',
    snapshot.questions.map((question) => question.question_type).join(', '),
  );

  const backward = JSON.parse(JSON.stringify(versionData));
  backward.questions[3].logic.rules[0].then.target_question_id =
    'q_nolab_0003';
  await expectRejected(
    'backward jump',
    new models.SurveyVersion(backward),
  );

  const badOption = JSON.parse(JSON.stringify(versionData));
  badOption.questions[0].logic.rules[0].when.conditions[0].value =
    'o_does_not_exist';
  await expectRejected(
    'condition with unknown option',
    new models.SurveyVersion(badOption),
  );

  const badAnonymous = load('responses.anonymous.example.json');
  badAnonymous.respondent_id = '651f1c2a9b3e4d5f6a7b8c9e';
  await expectRejected(
    'anonymous response with identity',
    new models.Response(badAnonymous),
  );

  // ---- phase 2: shared question library -------------------------------

  const pythonHash = questionVersion.content_hash;
  if (models.hashContent(questionVersion.content) !== pythonHash) {
    throw new Error('JS and Python content hashes disagree');
  }
  console.log('OK   content hash matches the Python implementation');

  if (refVersion.content_schema_version !== 2) {
    throw new Error('expected content_schema_version 2');
  }
  const referenced = refVersion.questions.filter(
    (item) => item.question_ref != null,
  );
  if (referenced.length !== 2) {
    throw new Error(`expected 2 referenced questions, got ${referenced.length}`);
  }
  console.log(
    'OK   survey version question_ref:',
    referenced.map((item) => item.question_id).join(', '),
  );
  console.log(
    'OK   response answer refs:',
    refResponse.answers.filter((item) => item.question_ref != null).length,
  );

  const tamperedVersion = load('question_versions.example.json');
  tamperedVersion.content.title = '被篡改的标题';
  await expectRejected(
    'question version with a stale content_hash',
    new models.QuestionVersion(tamperedVersion),
  );

  const orphanVersion = load('question_versions.example.json');
  orphanVersion.version_no = 1;
  await expectRejected(
    'first question version with a parent',
    new models.QuestionVersion(orphanVersion),
  );

  const missingParent = load('question_versions.example.json');
  missingParent.parent_version_id = null;
  await expectRejected(
    'later question version without a parent',
    new models.QuestionVersion(missingParent),
  );

  const selfShare = load('question_shares.example.json');
  selfShare.grantee_id = selfShare.granted_by;
  await expectRejected(
    'share granted to the owner',
    new models.QuestionShare(selfShare),
  );

  const badVisibility = load('questions.example.json');
  badVisibility.visibility = 'everyone';
  await expectRejected(
    'unknown question visibility',
    new models.Question(badVisibility),
  );

  console.log('\nMongoose schema checks passed');
}

main().catch((error) => {
  console.error('FAILED', firstError(error));
  if (error && error.errors) {
    console.error(error.errors);
  }
  process.exitCode = 1;
});
