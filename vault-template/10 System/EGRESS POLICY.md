# EGRESS POLICY — Control What May Leave the Computer

The system must never silently upload all source material to a cloud AI provider.

## Sensitivity classes

- `local_only` — default for unknown imported files; may be processed locally, not sent to cloud AI.
- `cloud_allowed` — source/content explicitly permitted for configured cloud processing.
- `sensitive` — contains or is likely to contain private/high-risk information; local processing only unless a narrow explicit override exists.
- `blocked` — credentials/secrets or policy-prohibited material; never sent to cloud providers.

## Default

Unknown imported files are private and classified `local_only` unless policy/configuration says otherwise. `ai.allow_cloud_ai` defaults to false.

## Mandatory secret scan before cloud egress

At minimum detect filenames/content resembling `.env`, API keys, private keys, PEM/SSH keys, cloud credentials, authorization tokens, password exports, and credential JSON. Such material is preserved locally, marked sensitive/blocked, and withheld from cloud egress.

Never write discovered secret values to logs, review notes, error traces, prompts, metrics, or status pages.

## Provider use

A cloud provider may be called only when all are true:

1. cloud AI is enabled in runtime configuration;
2. the selected provider is configured and healthy;
3. the specific source/request sensitivity permits egress;
4. secret scanning passes;
5. only the smallest required content is sent.

Local/Ollama-compatible providers are still untrusted software boundaries for sensitive deployments, but they do not count as cloud egress when configured to a local endpoint.
<!-- PHASE25_FINAL -->
## Phase 2.5 hardening

Security precedence is blocked secret > sensitive > explicit local-only > explicit cloud allow > trusted AI Allowed path > default local-only. Trust never overrides a fresh secret scan.
