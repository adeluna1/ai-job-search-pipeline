'use strict';

const DEFAULT_QUERY = [
  '"Recruiting Coordinator"',
  '"Recruiting Assistant"',
  '"Recruiting Scheduler"',
  '"Recruiting Operations Coordinator"',
  '"Talent Acquisition Coordinator"',
  '"Talent Operations Coordinator"',
  '"Talent Coordinator"',
  '"Candidate Experience Coordinator"',
  '"Sourcing Coordinator"',
  '"Junior Recruiter"',
  '"Recruiter I"',
  '"Associate Recruiter"',
  '"Recruiting Associate"',
  '"Talent Acquisition Associate"',
  '"Talent Acquisition Specialist"',
  '"University Recruiter"',
  '"University Recruiting Coordinator"',
].join(' OR ');

const DEFAULT_LOCATIONS = [
  'San Francisco Bay Area, California',
  'San Francisco, California',
  'San Jose, California',
  'Oakland, California',
  'Sacramento, California',
  'Remote, United States',
  'Remote, California',
  'California',
  'Santa Clara, California',
  'Palo Alto, California',
  'Mountain View, California',
  'Sunnyvale, California',
  'Fremont, California',
  'Walnut Creek, California',
  'Pleasanton, California',
];

const SESSION_DOMAINS = [
  'linkedin.com',
  'glassdoor.com',
  'ziprecruiter.com',
  'indeed.com',
];

const AUTH_DOMAINS = [
  'accounts.google.com',
  'appleid.apple.com',
  'login.microsoftonline.com',
];

function cleanText(value, label, maxLength) {
  const text = String(value ?? '').trim();
  if (!text) throw new Error(`${label} is required.`);
  if (text.length > maxLength) throw new Error(`${label} is too long.`);
  if (/[\u0000-\u001f\u007f]/.test(text)) {
    throw new Error(`${label} contains control characters.`);
  }
  return text;
}

function boundedInteger(value, fallback, minimum, maximum) {
  const parsed = Number.parseInt(String(value ?? fallback), 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(minimum, Math.min(maximum, parsed));
}

function validateSearchArgs(input = {}) {
  const query = cleanText(input.query || DEFAULT_QUERY, 'Query', 900);
  const sourceLocations = Array.isArray(input.locations)
    ? input.locations
    : input.location
      ? [input.location]
      : DEFAULT_LOCATIONS;
  const locations = [...new Set(
    sourceLocations
      .flatMap((value) => String(value ?? '').split(/[\n;]+/))
      .map((value) => value.trim())
      .filter(Boolean)
      .map((value) => cleanText(value, 'Location', 120)),
  )];
  if (locations.length === 0) throw new Error('At least one location is required.');
  if (locations.length > 16) throw new Error('Use no more than sixteen locations per run.');

  const requestedFreshHours = boundedInteger(input.freshHours, 168, 1, 336);
  const freshHours = requestedFreshHours <= 24
    ? 24
    : requestedFreshHours <= 72
      ? 72
      : requestedFreshHours <= 168
        ? 168
        : 336;
  const resultsWanted = boundedInteger(input.resultsWanted, 10, 1, 10);
  const concurrency = boundedInteger(input.concurrency, 4, 1, 4);
  const resumePath = String(input.resumePath || '').trim();
  if (resumePath && !resumePath.toLowerCase().endsWith('.docx')) {
    throw new Error('Resume must be a .docx file.');
  }
  return { query, locations, freshHours, resultsWanted, concurrency, resumePath };
}

function buildPipelineSearchArgs(agentRunPath, input = {}) {
  const safe = validateSearchArgs(input);
  const args = [
    '-File', agentRunPath,
    'agent-a-find',
    '--query', safe.query,
  ];
  for (const location of safe.locations) {
    args.push('--location', location);
  }
  args.push(
    '--hours-old', String(safe.freshHours),
    '--fresh-hours', String(safe.freshHours),
    '--fresh-days', String(Math.ceil(safe.freshHours / 24)),
    '--results-wanted', String(safe.resultsWanted),
    '--max-results', '10',
    '--concurrency', String(safe.concurrency),
  );
  if (safe.resumePath) args.push('--resume', safe.resumePath);
  return { args, safe };
}

function hostnameMatches(hostname, domain) {
  const host = String(hostname || '').toLowerCase();
  const expected = String(domain || '').toLowerCase();
  return host === expected || host.endsWith(`.${expected}`);
}

function isAllowedSessionUrl(rawUrl, additionalDomains = []) {
  if (rawUrl === 'about:blank') return true;
  let parsed;
  try {
    parsed = new URL(rawUrl);
  } catch {
    return false;
  }
  if (parsed.protocol !== 'https:') return false;
  return [...SESSION_DOMAINS, ...AUTH_DOMAINS, ...additionalDomains].some(
    (domain) => hostnameMatches(parsed.hostname, domain),
  );
}

function isAllowedWebviewUrl(rawUrl) {
  if (rawUrl === 'about:blank') return true;
  let parsed;
  try {
    parsed = new URL(rawUrl);
  } catch {
    return false;
  }
  if (
    parsed.protocol === 'http:'
    && new Set(['127.0.0.1', 'localhost']).has(parsed.hostname)
    && new Set(['3000', '3100']).has(parsed.port)
  ) {
    return true;
  }
  return isAllowedSessionUrl(rawUrl);
}

function validateApplicationIdentity(value) {
  const identityKey = String(value || '').trim().toLowerCase();
  if (!/^[0-9a-f]{16}$/.test(identityKey)) {
    throw new Error('Invalid application identity.');
  }
  return identityKey;
}

function validateApplicationMutation(input = {}) {
  const identityKey = validateApplicationIdentity(input.identityKey);
  const flag = String(input.flag || '').trim();
  if (!new Set(['interview', 'denied', 'not_selected']).has(flag)) {
    throw new Error('Invalid application outcome flag.');
  }
  return { identityKey, flag };
}

module.exports = {
  AUTH_DOMAINS,
  DEFAULT_LOCATIONS,
  DEFAULT_QUERY,
  SESSION_DOMAINS,
  buildPipelineSearchArgs,
  hostnameMatches,
  isAllowedSessionUrl,
  isAllowedWebviewUrl,
  validateApplicationIdentity,
  validateApplicationMutation,
  validateSearchArgs,
};
