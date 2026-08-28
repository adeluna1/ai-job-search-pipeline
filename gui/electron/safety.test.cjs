'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
  DEFAULT_QUERY,
  buildPipelineSearchArgs,
  isAllowedSessionUrl,
  isAllowedWebviewUrl,
  validateApplicationIdentity,
  validateApplicationMutation,
  validateSearchArgs,
} = require('./safety.cjs');

test('default search covers the expanded junior recruiting family', () => {
  const value = validateSearchArgs({});
  assert.match(value.query, /Junior Recruiter/);
  assert.match(value.query, /Talent Acquisition Specialist/);
  assert.match(value.query, /Recruiting Assistant/);
  assert.ok(value.locations.includes('Remote, United States'));
  assert.ok(value.locations.includes('Palo Alto, California'));
  assert.equal(value.resultsWanted, 10);
  assert.equal(value.freshHours, 168);
});

test('search input is bounded and locations are deduplicated', () => {
  const value = validateSearchArgs({
    locations: ['San Jose, California', 'San Jose, California', 'Oakland, California'],
    freshHours: 71,
    resultsWanted: 500,
    concurrency: 20,
  });
  assert.deepEqual(value.locations, ['San Jose, California', 'Oakland, California']);
  assert.equal(value.freshHours, 72);
  assert.equal(value.resultsWanted, 10);
  assert.equal(value.concurrency, 4);
});

test('weekly expansion supports a strict fourteen-day window', () => {
  const value = validateSearchArgs({ freshHours: 336 });
  assert.equal(value.freshHours, 336);
});
test('pipeline arguments preserve strict freshness and hard top-ten cap', () => {
  const built = buildPipelineSearchArgs('scripts/agent-run.ps1', {
    query: DEFAULT_QUERY,
    locations: ['San Francisco, California', 'San Jose, California'],
    freshHours: 24,
    resultsWanted: 6,
    resumePath: 'C:\\Users\\candidate\\resume.docx',
  });
  assert.equal(built.args.filter((value) => value === '--location').length, 2);
  assert.equal(built.args[built.args.indexOf('--fresh-hours') + 1], '24');
  assert.equal(built.args[built.args.indexOf('--max-results') + 1], '10');
  assert.equal(
    built.args[built.args.indexOf('--resume') + 1],
    'C:\\Users\\candidate\\resume.docx',
  );
});

test('embedded browser allows exact sites and trusted identity providers only', () => {
  assert.equal(isAllowedSessionUrl('https://www.glassdoor.com/profile/login_input.htm'), true);
  assert.equal(isAllowedSessionUrl('https://accounts.google.com/o/oauth2/v2/auth'), true);
  assert.equal(isAllowedSessionUrl('https://glassdoor.com.evil.example/login'), false);
  assert.equal(isAllowedSessionUrl('http://www.glassdoor.com/login'), false);
  assert.equal(isAllowedSessionUrl('file:///C:/Windows/System32/config'), false);
});

test('unsafe search strings and non-docx resumes are rejected', () => {
  assert.throws(() => validateSearchArgs({ query: 'Recruiter\nInjected' }), /control/);
  assert.throws(() => validateSearchArgs({ resumePath: 'resume.pdf' }), /\.docx/);
});

test('webview policy permits only local services or approved session sites', () => {
  assert.equal(isAllowedWebviewUrl('http://127.0.0.1:3000/'), true);
  assert.equal(isAllowedWebviewUrl('http://localhost:3100/api/health'), true);
  assert.equal(isAllowedWebviewUrl('https://www.indeed.com/jobs?q=recruiter'), true);
  assert.equal(isAllowedWebviewUrl('http://127.0.0.1:7896/health'), false);
  assert.equal(isAllowedWebviewUrl('http://localhost:3100.evil.example/'), false);
  assert.equal(isAllowedWebviewUrl('https://example.com/'), false);
  assert.equal(isAllowedWebviewUrl('javascript:alert(1)'), false);
});

test('application outcome mutations accept only bounded identities and flags', () => {
  assert.equal(validateApplicationIdentity('ABCDEF0123456789'), 'abcdef0123456789');
  assert.deepEqual(
    validateApplicationMutation({
      identityKey: '0123456789abcdef',
      flag: 'interview',
    }),
    { identityKey: '0123456789abcdef', flag: 'interview' },
  );
  assert.throws(
    () => validateApplicationMutation({ identityKey: '../reports', flag: 'interview' }),
    /identity/,
  );
  assert.throws(() => validateApplicationIdentity(''), /identity/);
  assert.throws(
    () => validateApplicationMutation({ identityKey: '0123456789abcdef', flag: 'submitted' }),
    /outcome/,
  );
});
