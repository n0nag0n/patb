patb CORE 0.1.1
You have the `patb` CLI. Before you act, query it.
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
To store an address, webhook, API key, or password: `patb secret set NAME` (value on stdin),
then put ${NAME} in the record. Never write the raw value into markdown or chat.
