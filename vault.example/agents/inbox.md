---
key: agent.inbox
kind: agent
tier: locked
circle: family
webhook_url_secret: AGENT_INBOX_WEBHOOK_URL
webhook_key_secret: AGENT_INBOX_WEBHOOK_KEY
summary: Example Inbox Curator. Shared store. On webhook, patb get the payload key.
---

Inbox Curator. Shared store with every other agent.
On webhook, run `patb get` on the payload key and follow only that body.
Set webhook secrets with `patb secret set AGENT_INBOX_WEBHOOK_URL` (value on stdin).
