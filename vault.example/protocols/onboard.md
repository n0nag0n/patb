---
key: protocol.patb.onboard
kind: protocol
tier: locked
summary: When you create a new bot, put it on patb immediately.
approval: none
---

When you create a new agent: backup its profile if it already has rules. Paste `patb core` into the profile. That is the OS. Do not grow it.

Two lines: You are NAME. PATB_AGENT=agent.<slug>.

CORE already runs `patb get protocol.global` (everyone-rules; miss = continue). Point the new bot at that; do not paste voice or everyone-rules into CORE or the profile file.

Move standing rules with `patb set` / `patb propose`, not the profile file. Do not put standing or dated rule bullets in Grok memory (Grok memory is soft prefs and ephemeral notes only).

Point scheduled jobs at `job.*` keys (`patb get job.<name>`). Pick one clock per job: Grok routine or external webhook tick, not both.

Do not put this checklist in CORE. The new agent has no CORE until you paste it. This checklist does not live in CORE.

Do not dump the catalog into the new profile.
