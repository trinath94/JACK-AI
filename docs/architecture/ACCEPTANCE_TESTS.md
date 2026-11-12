# JACK AI — Acceptance Test Plan

Deliverable 7 of Section 30. Each Section 28 scenario has preconditions, steps, pass criteria
and the evidence that must be captured. Scenarios run on a clean Windows 11 x64 VM
(and Windows 10 22H2 for A, H, J) using the installed MSI, never a dev build.

| ID | Scenario | Preconditions | Pass criteria | Evidence | Earliest milestone |
|---|---|---|---|---|---|
| A | Wake word | Mic configured, wake word on | "Jack" activates within 1 s; indicator → listening; spoken command transcribed; FA rate ≤ 1 per 8 h of mixed TV/speech audio; miss rate ≤ 5 % over 100 utterances, 3 speakers | Screen recording, wake-word evaluation report | M3 |
| B | Website development | Anthropic API or Claude Code configured | Asks requirements one at a time; creates project; builds site; tests pass; deployment plan prepared (not executed) | Task timeline export, test report, repo diff | M11 |
| C | Existing app upgrade | GitHub connected; repo with uncommitted changes | Uncommitted work preserved (stash or worktree); new branch; tests run; PR opened; no force-push | `git reflog`, PR URL, test report | M11 |
| D | Ubuntu diagnosis | SSH profile with verified host key | Connects as deploy user; collects CPU/mem/disk/services/logs; findings cite command output | Diagnostics report with raw outputs | M10 |
| E | Production deploy | Staging verified | Shows target host, release id, backup status, plan; waits for approval; deploys; health + external URL verified; rollback available | Deployment report, approval audit row | M13 |
| F | Logo generation | Image provider configured | Collects brand details; calls provider; saves chosen asset; cost recorded | Asset file + usage record | M14 |
| G | Self-upgrade | JACK source repo connected | Isolated branch build; tests; signed package; approval before install; health after; rollback works | Update log, signature check | M16 |
| H | Interruption | Long-running task | Pause → state persisted; resume continues from last completed step; cancel leaves no partial deploy | Task events table | M6 |
| I | Unauthorized production op | Task in ASSISTED mode | Production action rejected; `audit_events` row with outcome=`denied`; chain verifies | Audit export | M7 (partial M1: unauthenticated API calls rejected + audited) |
| J | Windows restart | Task mid-execution | After reboot, task visible; idempotent steps resume; non-idempotent step flagged `needs_review` | Task events before/after | M6 |

## Milestone 1 acceptance (automated)

1. Service refuses to start bound to a non-loopback host.
2. Unauthenticated request to any `/v1/*` route → 401 and an audit row.
3. Wrong `Host` header → 421.
4. WebSocket without auth frame closes with 4401 within 5 s; with auth receives `hello` + health.
5. Task create → list → transition along a valid path; invalid transition → 409.
6. Audit chain verifies; manual tampering is detected.
7. Secrets matching known patterns are redacted from log output.
8. Rust supervisor: starts service, obtains liveness, restarts it after it is killed.
9. Frontend: renders health from a mocked backend; typechecks; production build succeeds.
10. Windows CI job produces unsigned NSIS and MSI artifacts.
