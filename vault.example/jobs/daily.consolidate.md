---
key: job.daily.consolidate
kind: job
tier: locked
domain: cron
schedule: "@daily"
notify: exec
exec: patb consolidate
summary: Nightly memory moves. Does not edit CORE.
approval: none
---

Run `patb consolidate`. Demote cold working items to episodic. List hot candidates for a human to accept. Never rewrite CORE.md.
