/** Fields from an n8n Error Trigger item. */
function fromErrorTrigger(raw) {
  const execution = raw.execution || {};
  const error = execution.error || {};
  const node = error.node || {};
  return {
    source: 'n8n-error-trigger',
    workflow_name: text((raw.workflow || {}).name),
    execution_id: text(execution.id),
    execution_url: text(execution.url),
    failed_node: text(execution.lastNodeExecuted || node.name),
    error_message: text(error.message).slice(0, 1000),
    error_detail: [text(error.description), text((error.messages || [''])[0])].filter(Boolean).join(' | ').slice(0, 500),
    error_stack: text(error.stack).slice(0, SPEC.STACK_LIMIT),
    mode: text(execution.mode),
    occurred_at: '',
    explicit_status: text(error.httpCode),
  };
}

/** Fields from a generic JSON alert POSTed to the webhook. */
function fromAlertWebhook(raw) {
  const body = raw.body && typeof raw.body === 'object' && !Array.isArray(raw.body) ? raw.body : raw;
  return {
    source: text(body.source || 'webhook'),
    workflow_name: text(body.service || body.workflow || 'unknown'),
    execution_id: text(body.id),
    execution_url: text(body.url),
    failed_node: text(body.component),
    error_message: text(body.error_message || body.message).slice(0, 1000),
    error_detail: text(body.detail).slice(0, 500),
    error_stack: text(body.stack).slice(0, SPEC.STACK_LIMIT),
    mode: text(body.environment),
    occurred_at: text(body.occurred_at),
    explicit_status: text(body.http_status),
  };
}

/** Flat incident record with fingerprint, HTTP status and the Claude request body. */
function normalizeIncident(raw, receivedAt) {
  const isObj = (v) => v && typeof v === 'object' && !Array.isArray(v);
  const record = isObj(raw.execution) && isObj(raw.workflow) ? fromErrorTrigger(raw) : fromAlertWebhook(raw);
  record.http_status = httpStatusOf(record.explicit_status, record.error_message);
  delete record.explicit_status;
  const shape = record.error_message.replace(/[0-9]/g, '#');
  record.fingerprint = fnv1a(`${record.workflow_name}|${record.failed_node}|${shape}`);
  record.received_at = receivedAt;
  const userText = renderUser(SPEC.INCIDENT_FIELDS, record, 'Stack (truncated)', record.error_stack);
  record.claude_request = buildRequest(SPEC.INCIDENT_SYSTEM, SPEC.INCIDENT_SCHEMA, userText);
  return record;
}

return $input.all().map((item) => ({ json: normalizeIncident(item.json, nowIso()) }));
