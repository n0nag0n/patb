---
key: protocol.mail.scan
kind: protocol
tier: locked
domain: email
summary: Classify each message, patb search, obey that one record.
approval: none
---

For each message, run `patb search "<sender> <subject>"`.
Follow only the body that comes back. Do not load other mail policies up front.
If search misses, skip the message and continue. Do not invent a key.
