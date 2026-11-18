/** Classification, route, notification text and log row for one incident. */
function incidentResult(record, response) {
  const [found, ok, reason] = parseClassification(response, SPEC.INCIDENT_SCHEMA, SPEC.INCIDENT_FALLBACK_CLASSIFICATION);
  const branch = SPEC.INCIDENT_BRANCHES[found.severity] || SPEC.INCIDENT_FALLBACK;
  const where = record.execution_url || record.execution_id || 'n/a';
  const notify = `[${found.severity.toUpperCase()}] ${record.workflow_name}: ${found.summary}\n`
    + `Cause: ${found.probable_cause}\nFix: ${found.fix_note}\nExecution: ${where}`;
  const log_row = {
    fingerprint: record.fingerprint, source: record.source,
    workflow_name: record.workflow_name, failed_node: record.failed_node,
    severity: found.severity, category: found.category, summary: found.summary,
    fix_note: found.fix_note, classifier_ok: ok, received_at: record.received_at,
  };
  const route = { branch, channels: SPEC.INCIDENT_CHANNELS[branch] };
  return { classification: found, classifier_ok: ok, classifier_error: reason, route, notify_text: notify, log_row };
}

const records = $('Normalize + enrich').all();
return $input.all().map((item, i) => {
  const { claude_request, ...record } = records[i].json;
  return { json: { ...record, ...incidentResult(record, item.json) } };
});
