# Throwaway n8n 2.4.6 run

Claude reached through a one-port relay to our self-hosted LiteLLM gateway. Postgres after the run: ops_incidents: 4 rows, crm_leads: 2 rows, inbox_triage_log: 6 rows.

| execution | flow | trigger | input | claude | branch | classifier_ok | path | status |
|---|---|---|---|---|---|---|---|---|
| 1 | incident | Alert webhook | checkout-api | critical | critical | True | Route by severity > Email on-call > Page on-call (Telegram) > Log incident | success |
| 2 | incident | Alert webhook | onboarding-flow | low | low | True | Route by severity > Log incident | success |
| 3 | incident | Alert webhook | orders-db | critical | critical | True | Route by severity > Email on-call > Page on-call (Telegram) > Log incident | success |
| 11 | incident | Error Trigger | Nightly order sync | high | high | True | Route by severity > Page on-call (Telegram) > Log incident | success |
| 4 | lead | Inbound message | n8n automation for appointment reminders - can we talk this week? | hot_lead | hot | True | Route by intent > Alert sales (Telegram) > Upsert CRM lead > Log triage | success |
| 5 | lead | Inbound message | Question | warm_lead | warm | True | Route by intent > Upsert CRM lead > Log triage | success |
| 6 | lead | Inbound message | Lead form workflow stopped sending emails | support | ticket | True | Route by intent > Open helpdesk ticket > Log triage | success |
| 7 | lead | Inbound message | Invoice INV-2041 - PO number missing | billing | ticket | True | Route by intent > Open helpdesk ticket > Log triage | success |
| 8 | lead | Inbound message | Guaranteed page 1 Google ranking!!! | spam | spam | True | Route by intent > Drop spam > Log triage | success |
| 9 | lead | Inbound message | urgent partnership | spam | spam | True | Route by intent > Drop spam > Log triage | success |
