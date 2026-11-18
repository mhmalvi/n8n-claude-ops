/** Classification, route, alert text and log row for one inbound message. */
function leadResult(record, response) {
  const [found, ok, reason] = parseClassification(response, SPEC.LEAD_SCHEMA, SPEC.LEAD_FALLBACK_CLASSIFICATION);
  found.lead_score = Math.max(0, Math.min(100, found.lead_score));
  const branch = SPEC.LEAD_BRANCHES[found.intent] || SPEC.LEAD_FALLBACK;
  const notify = `[${found.intent} ${found.priority} score ${found.lead_score}] `
    + `${record.from_name} (${record.sender_domain || 'unknown domain'}): ${found.summary}`;
  const log_row = {
    from_email: record.from_email, channel: record.channel, subject: record.subject,
    intent: found.intent, priority: found.priority, lead_score: found.lead_score,
    summary: found.summary, classifier_ok: ok, received_at: record.received_at,
  };
  const route = { branch, channels: SPEC.LEAD_CHANNELS[branch] };
  return { classification: found, classifier_ok: ok, classifier_error: reason, route, notify_text: notify, log_row };
}

const records = $('Normalize message').all();
return $input.all().map((item, i) => {
  const { claude_request, ...record } = records[i].json;
  return { json: { ...record, ...leadResult(record, item.json) } };
});
