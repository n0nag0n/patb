patb CORE 0.1.5
You have the `patb` CLI. Before you act, `patb get protocol.global`. If it misses, continue. Then query for this task.
You may run patb as many times as this task needs. Fetch only the current step.
Do not guess keys. Do not dump the catalog. Do not read secrets.env or index.sqlite.
If patb is missing: export PATH="$HOME/.local/bin:$PATH"

Look up with `patb search` and 2-4 keywords, not the whole utterance.
Good: patb search "tire size cadenza"  Bad: the full sentence.
If it misses, try fewer words. Do not invent a key.

When a record or the situation needs a human choice, present a numbered list.
Numbers must be unique in that message. Wait.

Obey the record's approval field.
If a webhook payload has a "key", run `patb get <key>` and follow only that body.
To store an address, webhook, API key, password, or phone: `patb secret set NAME` (value on stdin),
then put ${NAME} in the record. Never write the raw value into markdown or chat.
Retrieve is `patb get` on that record, which expands ${NAME}. There is no `patb secret get`.
If get does not print the value, the record is missing ${NAME}; fix the record.
Do not read secrets.env. Print a secret in chat only when the human asked for that value.

Standing protocols are how to do the work. For who or what exists now, patb search working records first; do not treat a protocol body as the live roster.

When a standing rule changes, run `patb propose` or `patb set` on that key.
Do not append it to CORE or to the agent profile file.
