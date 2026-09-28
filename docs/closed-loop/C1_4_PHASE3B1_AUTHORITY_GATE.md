# C1.4 Phase 3B1 — native Darwin authority-isolation feasibility

Result: **PASS for the bounded disposable authority experiment**; pending Lead
Architect review. This is not full Route-B acceptance, live-backend compatibility,
production deployment, or verified execution quiescence. Accepted source parent:
`83d50fb28a6ee416d27bf001863be3107e5cbeb1`. C1.3 is untouched and remains frozen.

## Experiment boundary

Platform: macOS 15.7.4 (24G517), Darwin 24.6.0, Apple silicon arm64.
The whole inert backend starts under `/usr/bin/sandbox-exec` with a deny-default
Seatbelt profile BEFORE adversarial code executes. Allowed operations are fork/exec,
system parameter reads, reads of named OS/Python runtime paths and ancestor
directories, and reads/writes in one disposable scratch tree. Network/Mach lookup,
authoritative filesystem access and other operations have no allow rule.
The ancestor-directory exceptions do not recursively allow their contents.

The profile is an experimental, host-specific mechanism. The installed manual
marks sandbox-exec DEPRECATED. This result does not establish a supported production
packaging strategy or prove sandbox compatibility with Codex/Antigravity binaries.
No real provider or backend CLI was invoked.

Synthetic authoritative substitutes include repository content, `.git`, a real
fixture SQLite DB, control state, frozen/acceptance records, authorization records,
credential/session files, a trusted-writer socket and host-owned artifacts. The
host creates and reads these normally under the same user; they are not inaccessible
merely because of different UNIX ownership. All sentinel values are synthetic.
Only hashes, test outcomes and known disposable process identities enter evidence.

Scratch contains an allowlisted inert snapshot, the adversarial fixture, its test
configuration, a synthetic HOME/TMPDIR, and synchronization/report files. A deliberate
symlink into the authoritative area tests escape. No production-linked Git worktree,
real HOME, provider token, browser state or agent socket is provided. The backend
has exactly two extra descriptors: request/response pipes for proposal admission.
An authoritative file FD, writer socket and controller-command pipe are deliberately
marked inheritable in the host; close_fds/pass_fds excludes all three from the backend.

## Actual process/lifecycle sequence

1. Sandboxed parent runs read/write, path, descriptor, RPC and publication attacks.
2. It forks a child; that child changes process group and repeats the attacks.
3. The child forks a grandchild, which calls setsid and execs the fixture again.
4. The intermediate child and original parent exit. The grandchild remains alive,
   in its own session/group, reparented to PID 1, and repeats the attacks.
5. Trusted controller commits REVOKED. The living grandchild receives the CURRENT
   tuple and tries publication again; it is rejected despite knowing that tuple.
6. The admission controller exits. A new controller process opens the same temporary
   SQLite state and serves the retained private pipe. The grandchild remains alive
   and repeats direct and indirect attacks. They remain denied.
7. Only after recording ALIVE/REVOKED evidence does the custodian release the fixture
   to exit. Parent and controller handles are reaped, child completion is observed,
   and its PID disappearance is checked.

The trusted launch custodian remains alive across the controller restart. It retains
launch provenance/private pipe ownership, verifies the profile is unchanged, observes
the same live descendant and collects fresh denial results after restart. This is
positive evidence for this specific controller restart. It is NOT recovery after
loss of both controller and launch custodian, nor durable PID-reuse reconciliation.
Such loss remains BLOCKED/UNKNOWN pending a separately accepted recovery design.

## Publication admission and artifacts

The fixed trusted broker is repository-owned test code executed outside the backend
boundary; it never loads backend-generated code. It exposes only declarative JSON
proposal submission. Backend-requested `host_write` is always rejected. Connection
to the separate synthetic writer socket is denied by the native boundary.

Each publication validates exact work/attempt/fence/revision/sequence AND authority
under a SQLite transaction. There is one serialized controller, and revocation uses
the same admission loop/transaction boundary. New state tuples alone cannot grant
authority. Every previously accepted result advances revision/sequence; rejected
requests do not. Authority is enforced in the request handler, not merely stored
as an informational flag. The private inherited channel supplies the attempt's
connection identity; it is not a public endpoint trusting arbitrary supplied IDs.

Accepted JSON bytes are copied to host-only content-addressed files, flushed,
fsynced and made read-only before their hashes are published. The test verifies
stored hashes and backend denial of actual accepted artifact paths. The broker
supports no apply operation. It is NOT a production artifact parser, immutable
storage service, filesystem-apply journal or crash-atomic DB/filesystem protocol.

## Results and twelve-control boundary

One native end-to-end pytest case passed, with six attack phases. Four phases had
32 denied access checks each; the revoked/restarted phases had 30 each (they created
no new accepted artifact to attack). File/socket restrictions return EPERM/EACCES;
closed descriptor and /dev/fd checks return EBADF. No denial is inferred from a
missing authoritative file. Every synthetic authoritative sentinel hash is unchanged.

Four valid proposals were admitted, including from the escaped/reparented process.
Wrong work/attempt/fence/revision/sequence were rejected in each authorized phase.
After revocation, all submissions were rejected, including the exact current tuple
and attempts after controller restart. Event lineage is 1–4 PROPOSAL, 5 REVOKED,
with no post-revocation event. There was no trusted-host proposal application.

| Route-B control | Feasibility evidence / boundary |
|---|---|
| 1. No authoritative writes | All synthetic repository writes denied in every phase. |
| 2. No control-state access | `.git`, SQLite, freeze, acceptance and authorization access denied. |
| 3. Snapshot input | Independent inert snapshot; no project mount or real input. |
| 4. Proposal-only output | Controlled bounded data-only pipe; no mutation operation. |
| 5. No host mutation RPC | Writer socket denied; generic RPC rejected. |
| 6. Current publication tuple | Five independent tuple mismatches rejected. |
| 7. Revocation enforced | Current tuple rejected after REVOKED, including restart. General adversarial partial-message/race stress remains future work. |
| 8. Host-owned artifacts | Copied/sealed bytes inaccessible to backend; hashes checked. Full crash recovery deferred. |
| 9. Trusted-host-only apply | No backend apply capability exists. A production host apply implementation is deliberately absent. |
| 10. Baseline-revalidated apply | No apply endpoint exists, so this prerequisite cannot be bypassed. Actual baseline/apply acceptance is NOT TESTED and remains required later. |
| 11. Stale survivor harmless to authoritative state | Live revoked descendant attacks denied; sentinel hashes unchanged. |
| 12. No credentials/sessions/agent sockets | Synthetic credentials only; clean environment and descriptor allowlist; no model transport or live-auth claim. |

Thus the minimum authority boundary is experimentally feasible for this inert
Darwin process tree. No evidence promotes the entire twelve-control production
architecture to implemented/accepted status. In particular, controls 9–10 require
future writer implementation and tests before any real apply is authorized.

## Reproduction and test history

```sh
/Users/huanchen/opt/anaconda3/bin/python3 -m pytest -q tests/test_c14_authority_isolation_gate.py
```

The host test runner is translated on this machine; the fixture launch explicitly
selects arm64 to avoid an unallowed Rosetta runtime dependency. Strict-profile
preflight failures were resolved by narrowly permitting runtime ancestor-directory
reads. The first integrated run could not start the translated backend; the second
completed the attack scenario but the assertion incorrectly treated EBADF as an
access success for /dev/fd. The assertion was corrected to recognize a closed FD;
filesystem sentinel denials still require EPERM/EACCES. Final native test passed
in 0.79s. Existing 80-test runtime baseline was not rerun: no runtime source changed.

[Raw experiment evidence](C1_4_PHASE3B1_AUTHORITY_EVIDENCE.json) contains profile,
profile hash, per-phase errors, process observations, controller PIDs and event
lineage. Temporary paths in it identify the run, not required permanent resources.
Fixtures reproduce the experiment from scratch without those old paths.

## Limitations and next recommendation

This is a finite adversarial feasibility test, not proof against every kernel
vulnerability or possible syscall. It relies on Darwin's inherited sandbox, the
trusted custodian and broker, and a clean descriptor launch. The backend can still
consume resources or change its own scratch files. Runtime read allowances and
sandbox-exec's deprecated status require review before production design.

The broker uses a bounded but simple protocol; malicious partial-message denial of
service, broad race/crash injection, full host-restart recovery and transactional
apply are not implemented here. No current CLI compatibility is established.
No credential broker is implemented or authorized.

Recommend Lead Architect review of this gate, then separately authorize the next
small Route-B contract/revocation-and-apply-journal step. Keep VM containment deferred
only within this tested scope; escalate if an actual backend cannot retain the same
authority boundary. Do not call ALIVE/REVOKED VERIFIED_QUIESCENCE.
