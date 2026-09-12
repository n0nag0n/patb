# External tick as the clock (webhook only)

This file is the **webhook-tick clock** only. Use it **instead of** Grok-scheduled routines for these jobs — not stacked with them.

Grok Bot has no OS crontab. The tick runs on a Linux box (or you curl by hand). It POSTs to a Grok Bot webhook. The Bot wakes, CORE sees a payload `key`, and the Bot runs `patb get` on that key.

The other clock (Grok routines as the schedule) is [`examples/grok-routine.md`](grok-routine.md). Pick **one** clock per `job.*` key.

External check → webhook wake saves tokens vs waking the model on a timer to poll `patb due`.

## 1. Webhook secrets first

Do **not** set `notify: webhook` on a job until the webhook URL and key exist as patb secrets.

```bash
echo 'https://example.invalid/webhook/YOUR_ENDPOINT' | patb secret set AGENT_INBOX_WEBHOOK_URL
echo 'YOUR_WEBHOOK_TOKEN' | patb secret set AGENT_INBOX_WEBHOOK_KEY
```

Use placeholders like that — never commit real tokens, URLs, or keys. These are **patb** `${NAME}` secrets (`patb secret set` + expand via `patb get`). They are not Grok Bot **secret-request** (the product’s masked credential UI / env on the box).

## 2. Job (notify: webhook only after secrets exist)

```bash
patb set job.hourly.mail --kind job --schedule "0 * * * *" \
  --notify webhook \
  --agent agent.inbox \
  --webhook-url-secret AGENT_INBOX_WEBHOOK_URL \
  --webhook-key-secret AGENT_INBOX_WEBHOOK_KEY \
  --body "Run: patb get protocol.mail.scan
Follow only that record."
```

Or put the URL/key secret names on the agent record (`vault.example/agents/inbox.md`) and omit them on the job.

Create a **webhook** routine on the Grok Bot (not a scheduled Grok routine for this same key). Pause or delete any Grok-scheduled routine that used to clock this job.

## 3. What tick POSTs

`patb tick` POSTs JSON with the exact field name `key`:

```json
{"key":"job.hourly.mail"}
```

When a key secret exists, tick sets both headers:

- `Authorization: Bearer <token>`
- `X-Automation-Key: <token>`

The Bot wakes. CORE: if the payload has a `key` (JSON body `{"key":"job.…"}`), run `patb get <key>` and follow only that body.

## 4. Run tick (Linux crontab, or curl)

On a machine that **has** crontab (not the Grok Bot box):

```bash
./install.sh --yes --cron
```

That installs `* * * * * patb tick`. Tick is Python only — no model. When the job is due it POSTs. Webhook URLs must be public `https` (no redirects, no localhost).

Manual curl (placeholders only — never a real token):

```bash
curl -sS -X POST "$GROK_WEBHOOK_URL" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $GROK_WEBHOOK_KEY" \
  -H "X-Automation-Key: $GROK_WEBHOOK_KEY" \
  -d '{"key":"job.hourly.mail"}'
```

`notify: exec` jobs (`job.daily.consolidate`) still need OS crontab to fire through tick. On Grok Bot, keep consolidate as a Grok routine — see [`examples/grok-routine.md`](grok-routine.md).
