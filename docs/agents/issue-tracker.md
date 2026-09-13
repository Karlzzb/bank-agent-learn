# Issue tracker: GitHub Issues

Issues and specs for this repo live as GitHub Issues on `Karlzzb/bank-agent-learn`.

## Conventions

- One feature per issue; large efforts use a parent spec issue linked from child implementation issues.
- A spec issue's body follows the spec template (Problem Statement / Solution / User Stories / Implementation Decisions / Testing Decisions / Out of Scope / Further Notes).
- Triage state is recorded with labels (see `triage-labels.md`); every issue carries exactly one triage label.
- Discussion happens in issue comments, not in local files.

## When a skill says "publish to the issue tracker"

Create a GitHub issue with `gh issue create --repo Karlzzb/bank-agent-learn`.
Apply the appropriate triage label at creation time.

## When a skill says "fetch the relevant ticket"

Read the issue with `gh issue view <number> --repo Karlzzb/bank-agent-learn --comments`.
The user will normally pass the issue number directly.

## Wayfinding operations

Used by `/wayfinder`.

- **Map**: the parent spec issue body holds Notes / Decisions-so-far / Fog.
- **Child ticket**: one GitHub issue per ticket, linked from the parent; a `Type:` line in the body records the ticket type (`research`/`prototype`/`grilling`/`task`).
- **Blocking**: recorded as `Blocked by: #N, #N` lines in the issue body. A ticket is unblocked when every issue it lists is closed.
- **Frontier**: list open issues with `gh issue list --repo Karlzzb/bank-agent-learn`, filter to unblocked and unassigned; lowest number wins.
- **Claim**: self-assign the issue (`gh issue edit <number> --add-assignee @me`) before any work.
- **Resolve**: post the answer as an issue comment, close the issue, then append a context pointer (gist + issue link) to the parent issue's Decisions-so-far section.
