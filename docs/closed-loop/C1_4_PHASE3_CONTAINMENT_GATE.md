# C1.4 Phase 3 — blocked at descendant containment gate

Baseline: `7ac24dc0898b5831495ee255236c19f7f6b83bac` (80 tests).
Result: **BLOCKED; NOT ACCEPTED**. C1.3 remains COMPLETE / APPROVED / FROZEN.
No runtime code, production state, provider, browser or deployed artifact was touched.

## Reproduced finding

Platform: Darwin 24.6.0 arm64. The current lifecycle helper relies on a retained,
reaped parent process handle and disappearance of its POSIX process group.
An inert parent was launched with `start_new_session=True`. It launched an inert
child with another `start_new_session=True`. Both scripts lived in a temporary
directory and had bounded self-exit deadlines plus host-controlled exit files.
The parent exited normally and was reaped. Its process group no longer existed,
but the escaped child's different process group and live PID remained observable.

`verify_process_group_exit` returned TERMINATED in that condition. This is a
counterexample to treating that helper's receipt as VERIFIED_QUIESCENCE for a
potentially escaping process tree. No such receipt was accepted by the test host.
The host supplied UNKNOWN to a disposable contract-state test; quiescence and
Backend B authorization were rejected, with the publication token unchanged.
That contract-state exercise is separate from the OS reproduction: it does not
claim durable OS identity binding or real backend execution integration.

The characterization test passes by proving the unsafe helper behavior and the
fail-closed contract response. **One passing characterization test is not passing
Phase-3 lifecycle acceptance.** The previous 80-test baseline was not rerun because
no runtime code changed. Remaining lifecycle scenarios were stopped as instructed.

## Identity, cleanup and evidence boundaries

Only known disposable PIDs were queried with `ps` for PID, PPID, process group,
start time and status. No command lines, environment, credentials or global process
inventory were collected. Those observations are forensic identity fields; they
are not a restart-safe identity implementation or PID-reuse protection.

The escaped child was known only because this cooperative fixture reported it.
The current mechanism does not guarantee discovery of arbitrary descendants that
escape before enumeration or reparent themselves. Enumerating a process tree once
or successfully killing a group would not close this gap.

Cleanup used the disposable exit files, reaped the parent, observed the child's
completion marker and verified that its PID disappeared. No unknown process was
signalled. The fixture had no network/provider dependency or workspace authority.

See [recorded evidence](C1_4_PHASE3_ESCAPE_EVIDENCE.json). The reproduction test is
`tests/test_c14_process_escape_gate.py`; it is Darwin-specific. A temporary SQLite
file was used only to confirm UNKNOWN blocks the Phase-1 handoff contract.

## Acceptance disposition

- Descendant escape: reproduced; containment acceptance FAILED.
- UNKNOWN termination: explicit UNKNOWN rejected; B blocked.
- Normal parent exit: observed, but not sufficient for full-tree acceptance.
- Timeout/tree termination, crash classification, late-result fencing, restart
  reconciliation, PID-reuse mismatch and full handoff lineage: NOT RUN in Phase 3.
- No Phase-3 runtime fix or production migration was attempted.

Do not rely on the group-only verifier for live handoff acceptance. A separately
approved design must provide enforceable containment with durable process-instance
identity and restart reconciliation, potentially using an isolated VM/container
whose lifecycle the trusted host can positively verify. No claim is made that all
Darwin containment options are impossible; the current implementation is insufficient.

Next action is Lead Architect review of this blocker and a containment redesign,
not Phase 4 or live-provider acceptance. No automatic fallback is authorized.
