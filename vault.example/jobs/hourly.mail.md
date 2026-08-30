---
key: job.hourly.mail
kind: job
tier: locked
domain: cron
schedule: "0 * * * *"
agent: agent.inbox
notify: webhook
summary: Wake Inbox Curator to run protocol.mail.scan
approval: none
---

Run `patb get protocol.mail.scan` and follow only that record.
Do not load other mail policies up front.
