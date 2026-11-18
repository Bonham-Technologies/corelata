# Autopilot: local rules for this repository

This file belongs to this repository. `bin/vendor-claude-setup` in bonham-ops created it
once and never changes it, so rules here survive every refresh of the vendored policy.
It loads in every session, like `.claude/rules/autopilot.md`.

Where this file conflicts with the autopilot policy (`.claude/rules/autopilot.md` and the
role files in `.claude/autopilot/`), this file wins, except for the hard rules
(**Always**) and the `ap-owner-merge` criteria, which it can only make stricter.

Put each rule under a heading that names the policy section it changes, such as
`## Ticket classes`, `## Steward` or `## Builder, step 2`, and say whether it adds to
that section or replaces part of it. A rule that applies only to one role is still read
by every role, so name the role.

No local rules yet.
