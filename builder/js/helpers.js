// Shared helpers, inlined into every generated Code node (n8n Code nodes cannot import files).
// Mirrors runner/normalize.py and runner/classify.py; tests/test_js_parity.py keeps them equal.

/** value as a string, with null/undefined as "". */
function text(value) {
  return value === undefined || value === null ? '' : String(value);
}

/** 32-bit FNV-1a over UTF-16 code units, as 8 hex chars. */
function fnv1a(value) {
  let digest = 0x811c9dc5;
  for (let i = 0; i < value.length; i++) {
    digest ^= value.charCodeAt(i);
    digest = Math.imul(digest, 0x01000193) >>> 0;
  }
  return digest.toString(16).padStart(8, '0');
}

/** The explicit HTTP status, else the first 4xx/5xx number in the message. */
function httpStatusOf(explicit, message) {
  if (text(explicit)) return text(explicit);
  const match = /\b([45][0-9]{2})\b/.exec(message);
  return match ? match[1] : '';
}

/** One "Label: value" line per non-empty field, then a labelled tail block. */
function renderUser(fields, record, tailLabel, tail) {
  const lines = fields.filter(([, key]) => record[key]).map(([label, key]) => `${label}: ${record[key]}`);
  if (tail) lines.push(`${tailLabel}:\n${tail}`);
  return lines.join('\n');
}

/** Messages API request body with a JSON-schema structured output. */
function buildRequest(system, schema, userText) {
  return {
    model: SPEC.MODEL,
    max_tokens: SPEC.MAX_TOKENS,
    system,
    messages: [{ role: 'user', content: userText }],
    output_config: { effort: SPEC.EFFORT, format: { type: 'json_schema', schema } },
  };
}

/** Text of the first text block of a Messages API response, or "". */
function responseText(response) {
  for (const block of response.content || []) {
    if (block && typeof block === 'object' && block.type === 'text') return String(block.text || '');
  }
  return '';
}

/** "" when data satisfies the flat schema, else the first problem. */
function checkFields(data, schema) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return 'output is not an object';
  for (const key of schema.required) {
    const rule = schema.properties[key];
    const value = data[key];
    if (value === undefined || value === null) return `missing ${key}`;
    if (rule.type === 'string' && typeof value !== 'string') return `${key} is not a string`;
    if (rule.type === 'boolean' && typeof value !== 'boolean') return `${key} is not a boolean`;
    if (rule.type === 'integer' && !Number.isInteger(value)) return `${key} is not an integer`;
    if (rule.enum && !rule.enum.includes(value)) return `${key} not in enum`;
  }
  return '';
}

/** [classification, ok, reason]; the fallback whenever the response is unusable. */
function parseClassification(response, schema, fallback) {
  if (response.type === 'error' || response.error) return [{ ...fallback }, false, 'api error'];
  const stop = response.stop_reason;
  if (!(stop === 'end_turn' || stop === undefined || stop === null)) return [{ ...fallback }, false, `stop_reason ${stop}`];
  let data;
  try { data = JSON.parse(responseText(response)); } catch (e) { return [{ ...fallback }, false, 'output is not JSON']; }
  const problem = checkFields(data, schema);
  if (problem) return [{ ...fallback }, false, problem];
  return [Object.fromEntries(schema.required.map((key) => [key, data[key]])), true, ''];
}

/** Current UTC time, second precision, Z suffix. */
function nowIso() {
  return new Date().toISOString().replace(/\.[0-9]{3}Z$/, 'Z');
}
