# C1.4 Capacity Observability Investigation

## A. INVENTORY AVAILABLE CAPACITY SOURCES
- Checked `agy --help`: No commands related to quota, remaining tokens, or capacity limits exist.
- Checked `agy models`: Lists available models but provides no capacity metrics, limits, or percentage information.
- Checked DAIO `CapacityRegistry` (`scripts/daio_closed_loop/capacity.py`): Tracks binary execution-time states (e.g., `AVAILABLE`, `CAPACITY_EXHAUSTED`). Does not contain any fields or mechanisms to record percentages or reset times.
- Local configuration (`~/.gemini/settings.json`, `~/.gemini/antigravity-cli/`): Inaccessible or permission denied, representing unsupported integration paths.
- Local IDE binary state (`~/.gemini/antigravity-ide/user_settings.pb`): Analyzed via `strings`; no readable capacity or quota values found.

## B. DETERMINE WHAT THE UI PERCENTAGE ACTUALLY MEANS
Without credential extraction or access to undocumented/unsupported internal APIs, the actual semantics of the UI percentage are unascertainable programmatically.
- SOURCE: UNKNOWN (Likely an internal UI auth flow or dashboard API not exposed via CLI)
- SEMANTICS: UNKNOWN
- UNIT: Percentage (%)
- SCOPE: UNKNOWN (User context indicates Claude/GPT-OSS/Gemini share pools, suggesting Provider-Shared or Pool-Shared)
- RESET/CADENCE: UNKNOWN
- MODEL_SPECIFIC or PROVIDER_SHARED: UNKNOWN programmatically
- AUTHORITATIVE vs ESTIMATED: UNKNOWN
- PROGRAMMATICALLY_ACCESSIBLE: NO
- SUPPORTED_INTERFACE: NO
- FRESHNESS: UNKNOWN

## C. TEST PROGRAMMATIC OBSERVABILITY — READ ONLY
Executing `agy --model <model_id> --print "test"` provides execution-time status, but there is NO pre-execution command (like `agy quota`) to view capacity states prior to consumption.

| Provider | Model | Observable | State | Remaining % | Reset | Source | Confidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Gemini | gemini-3.7-flash-medium | NO (Pre-execution) | UNKNOWN | UNKNOWN | UNKNOWN | None | High |
| Anthropic | claude-opus-4-6-thinking | NO (Pre-execution) | UNKNOWN | UNKNOWN | UNKNOWN | None | High |
| OpenAI/OSS | gpt-oss-120b-medium | NO (Pre-execution) | UNKNOWN | UNKNOWN | UNKNOWN | None | High |

*(Note: Execution tests via CLI showed SUCCESS for all models, but this only proves execution-time availability, not pre-execution capacity observability.)*

## D. COMPARE WITH DAIO PHASE 4C
1. **Can existing CapacityRegistry represent the observed data?**
   Yes, for execution-time states (`AVAILABLE`, `CAPACITY_EXHAUSTED`). No, for percentages or reset times.
2. **Is remaining_percentage needed, or should it remain metadata only?**
   It should be omitted or remain metadata only, since it's not programmatically accessible via supported interfaces.
3. **Can observations be refreshed without consuming meaningful quota?**
   No. Refreshing requires an actual execution attempt (e.g., `agy --print`), which consumes tokens/quota.
4. **Can observations be obtained BEFORE selecting/executing a backend?**
   No.
5. **Can stale observations be timestamped reliably?**
   Yes, DAIO already timestamps the execution-time observation (`observed_at`).
6. **Can model-level capacity remain isolated from provider-level capacity?**
   Yes programmatically in the registry, but we lack programmatic visibility to know if a provider rate-limit actually spans multiple models unless we execute and fail.
7. **Are some models sharing the same quota pool?**
   Yes (e.g., Claude was stated to share the relevant quota pool).
8. **Can reset/cooldown time be observed reliably?**
   No.

## E. PHASE 5B-2 IMPLICATION
**CASE 2**: ONLY EXECUTION-TIME CAPACITY FAILURE IS OBSERVABLE.
Phase 5B-2 must wait for a naturally occurring real capacity event. We cannot safely or reliably inspect UI percentages to preemptively fail execution.

## F. IMPORTANT SAFETY SEMANTICS
- We cannot safely convert UI percentage thresholds into DAIO authority decisions.
- CapacityRegistry authority should continue to fail closed.
- UNKNOWN must remain UNKNOWN.

## G. REQUIRED REPORT FIELDS
CAPACITY_OBSERVABILITY_RESULT: NO_SUPPORTED_PRE_EXECUTION_INTERFACE
ANTIGRAVITY_UI_PERCENT_SOURCE: UNKNOWN
UI_PERCENT_SEMANTICS: UNKNOWN
SUPPORTED_PROGRAMMATIC_INTERFACE: NONE
PRE_EXECUTION_OBSERVATION_SUPPORTED: FALSE
OBSERVATION_REQUIRES_QUOTA_CONSUMPTION: TRUE
MODEL_LEVEL_OBSERVATION_SUPPORTED: FALSE (Pre-execution)
PROVIDER_SHARED_QUOTA_DETECTED: TRUE (via user context, not programmatic evidence)
REMAINING_PERCENT_AVAILABLE: FALSE
RESET_TIME_AVAILABLE: FALSE
RATE_LIMIT_STATE_AVAILABLE: FALSE (Pre-execution)
OBSERVATION_FRESHNESS_AVAILABLE: FALSE (Pre-execution)
CREDENTIAL_ACCESS_REQUIRED: TRUE (To get UI dashboard data)
CURRENT_CAPACITY_REGISTRY_COMPATIBLE: TRUE (For execution-time binary states)
DAIO_CHANGE_REQUIRED: FALSE
PHASE_5B2_RECOMMENDATION: WAIT_FOR_NATURAL_EXECUTION_FAILURE
KNOWN_LIMITATIONS: DAIO must rely purely on execution-time exceptions (`Outcome.QUOTA_EXHAUSTED`) to detect capacity events.
