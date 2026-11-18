# Follow-up files

Each milestone leaves a `docs/m<N>-followups.md`: its divergences from Coglossa, spec deviations,
rulings made during execution, and the work it parked under "Should fix soon" and "Later". The
autopilot steward reads these files for untracked work, so each one says which items a ticket
already tracks.

## Ticket keys

- An item that a CRL ticket tracks ends with ` — CRL-nn`, after any note already there. An item
  two tickets share ends with both (` — CRL-43, CRL-66`).
- Once the ticket is Done (both tickets, on a shared item), the item's problem text is struck
  through (`~~...~~`); the key and any note on how it was fixed stay unstruck. A strikethrough
  cannot cross a blank line, so on a long item it covers the first sentence or the part the
  ticket fixed.
- An item with no key is not tracked. Add the key when a ticket is filed for the item, and strike
  the item in the pull request that closes the ticket.
- Older notes stay as written: `— **closed in M17** (CRL-38)`, "Fixed by CRL-nn", and `BORG-nn`
  keys from before the CRL project. Items closed without a ticket ("fixed in the final wave",
  "verified 2026-10-18") carry no key.
- The "Divergences from Coglossa" sections are the list CRL-3 (the shared foundation package)
  will reconcile; their bullets carry no key.

Check: `grep -n 'CRL-' docs/m*-followups.md`.
