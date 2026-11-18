/** Flat inbound-message record; only the sender's domain goes to Claude. */
function normalizeLead(raw, receivedAt) {
  const body = raw.body && typeof raw.body === 'object' && !Array.isArray(raw.body) ? raw.body : raw;
  const email = text(body.from_email).trim().toLowerCase();
  const record = {
    channel: text(body.channel || 'email'),
    from_name: text(body.from_name),
    from_email: email,
    sender_domain: email.includes('@') ? email.split('@').pop() : '',
    subject: text(body.subject).slice(0, 300),
    body: text(body.body || body.text).slice(0, SPEC.BODY_LIMIT),
    received_at: receivedAt,
  };
  const userText = renderUser(SPEC.LEAD_FIELDS, record, 'Message', record.body);
  record.claude_request = buildRequest(SPEC.LEAD_SYSTEM, SPEC.LEAD_SCHEMA, userText);
  return record;
}

return $input.all().map((item) => ({ json: normalizeLead(item.json, nowIso()) }));
