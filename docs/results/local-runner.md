Model `claude-haiku-5-5`, 12/12 samples met their expectation. Reached through our self-hosted LiteLLM gateway (alias cloud-flash -> OpenRouter anthropic/claude-haiku-5.5), because the direct Anthropic key returned 401 on 2026-11-18.

| sample | kind | label | branch | classifier_ok | expected | latency_ms | tokens_in | tokens_out |
|---|---|---|---|---|---|---|---|---|
| 01-invoice-auth-401.json | incident | high | high | True | True | 5245 | 227 | 175 |
| 02-enrich-rate-limit-429.json | incident | medium | medium | True | True | 2440 | 763 | 244 |
| 03-checkout-down-503.json | incident | critical | critical | True | True | 3060 | 752 | 274 |
| 04-staging-typeerror.json | incident | low | low | True | True | 2875 | 791 | 256 |
| 05-backup-report-timeout.json | incident | high | high | True | True | 3137 | 753 | 254 |
| 06-disk-full-with-injection.json | incident | critical | critical | True | True | 2964 | 758 | 231 |
| 01-hot-clinic-reminders.json | lead | hot_lead | hot | True | True | 2992 | 772 | 325 |
| 02-warm-ecommerce.json | lead | warm_lead | warm | True | True | 3135 | 694 | 239 |
| 03-support-form-broken.json | lead | support | ticket | True | True | 2254 | 714 | 221 |
| 04-billing-invoice.json | lead | billing | ticket | True | True | 2057 | 707 | 191 |
| 05-spam-seo.json | lead | spam | spam | True | True | 2427 | 725 | 139 |
| 06-injection-crypto.json | lead | spam | spam | True | True | 3498 | 724 | 165 |
