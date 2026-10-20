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

  await user.validate();
  await survey.validate();
  await version.validate();
  await anonymous.validate();
  await identified.validate();
  await snapshot.validate();

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

  console.log('\nMongoose schema checks passed');
}

main().catch((error) => {
  console.error('FAILED', firstError(error));
  if (error && error.errors) {
    console.error(error.errors);
  }
  process.exitCode = 1;
});
