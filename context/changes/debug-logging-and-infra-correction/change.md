---
change_id: debug-logging-and-infra-correction
title: DEBUG observability + close empty-emit retry gap + CI trigger
status: implementing
created: 2026-08-05
updated: 2026-08-05
archived_at: null
---

## Notes

The reviewer produces 0 findings on `krkruk/target-o-meter#28` in CI (works
locally on the same commit). The CI log's smoking gun is
`node checks — model usage: input=58396 output=25 total=58421 finish_reason=stop`:
the model emitted ~25 output tokens (a valid-but-empty FindingsReport) and
stopped. There is no "structured emit came back empty (retry)" warning and no
"agent invoke failed" warning, so the ~25 tokens PARSED SUCCESSFULLY as an empty
report — which bypasses `_invoke_with_emit_retry` (it only retries on a parse
*failure* exception, never on a valid-but-empty emit). This is exactly the
silent-degrade-to-0-findings mode recorded in `lessons.md` and the
fine-tune-context diagnosis.

This change: (1) adds DEBUG observability so the next CI run is diagnosable
(redacted env dump, head/base git SHA + branch breadcrumb, assembled inbound
prompt char count, outbound per-turn message trace + final structured_response
preview); (2) closes the empty-emit retry gap (retry when the parsed report is
empty AND zero tool-call turns were made); (3) pins the consumer's `review.yml`
at a tool `debug-ci-logging` branch and commits it on the feature branch to
trigger PR #28's diagnostic run. Phase 4 (merge branch to tool master + revert
the workflow pin) is the post-diagnosis cleanup.
