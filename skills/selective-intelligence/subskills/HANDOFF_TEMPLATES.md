# AI Handoff Templates (for non-developer teams)

Use only the templates for Council roles that were actually selected. Ordinary Lean work needs none of them.

## 1) Intake -> Planner handoff

```
INTAKE PACKET
1) outcome:
2) where this project belongs (brand/product):
3) what is definitely true:
4) what is assumed:
5) user limits (money / privacy / time / legal / approvals):
6) next_skill: si-planner
```

## 2) Planner -> Worker handoff

```
PLANNER CHECKPOINT
1) outcome statement (one short sentence):
2) 1-2-3 plan:
3) required user actions (if any):
4) known risks and blocked decisions:
5) file/code areas to touch:
6) success check (how to know this slice is done):
7) next_skill: si-worker
```

## 3) Worker -> Objector handoff

```
WORKER RESULT
1) changed files:
2) what behavior now works:
3) what was skipped (and why):
4) quick proof:
5) next_skill: si-objector
```

## 4) Queue-Manager -> Objector handoff

```
QUEUE MANAGER SNAPSHOT
1) queue_id:
2) decision: continue / interrupt / complete
3) reason (if interrupt):
4) owner/branch/status mismatch checked:
5) next_skill: si-objector (continue) or si-planner (interrupt)
```

## 5) Objector -> Aligner handoff

```
OBJECTOR FINDINGS
1) finding list (id, place, issue, severity):
2) proof for each finding:
3) severity = block / improve / style:
4) recommendation:
5) next_skill: si-aligner
```

## 6) Aligner -> Verifier handoff

```
ALIGNMENT RECORD
1) status: aligned / provisionally_aligned / blocked / partial
2) open findings:
3) required fixes (if any):
4) decision reason:
5) next_skill: si-verifier (or si-worker if blocked)
```

## 7) Verifier final packet

```
VERIFIER HANDOFF
1) done or not done:
2) what changed:
3) proof:
4) what a human must do next:
5) short user summary (plain language):
```

Keep each packet short. If a section is unknown, write "unknown" instead of guessing.
