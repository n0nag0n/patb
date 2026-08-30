# Grok Bot routines as the clock

Grok Bot has no OS crontab. `patb tick` will not install. Your Grok **routines** keep the same times they have today. Each routine’s entire prompt should be “fetch this one job.”

Do **not** add a routine that runs every minute (or every hour) with `patb due`. That wakes the model just to ask the clock.

## 1. Save the job in patb

```bash
patb set job.hourly.mail --kind job \
  --summary "Hourly mail pulse" \
  --body "Run: patb get protocol.mail.scan
Follow only that record.
For each message: patb search \"<sender> <subject>\", then obey that one body.
If search misses, skip the message. Do not invent a key."
```

Repeat for each pulse you already run (`job.hourly.telegram`, `job.daily.briefing`, …).

## 2. Routine prompt (paste this, change the key)

```text
Run this command and follow only the body it prints:

  patb get job.hourly.mail

Do not load other policies. Do not dump the catalog.
If the command is missing:
  export PATH="$HOME/.local/bin:$PATH"
  export PATB_HOME=/workspace/patb
```

Set the schedule in the Grok UI to whatever you already use (hourly, 8am, …).

## Daily consolidate (Grok Bot)

Required on first run. `job.daily.consolidate` is `notify:exec` / `@daily` and only fires through `patb tick`, which needs OS crontab. Grok Bot has none, so a Grok routine is the clock.

Schedule: **8:00 AM local, all days.**

Paste this as the entire prompt:

```text
export PATH="$HOME/.local/bin:$PATH"
patb get job.daily.consolidate
follow only that body
```

Stay quiet unless there are hot candidates. Never edit CORE.

## 3. Profile (once per Bot)

A newly created bot is not on patb until CORE is pasted.

`patb core`, then:

```text
You are Inbox Curator. PATB_AGENT=agent.inbox
```

Mail rules, GitHub rules, and identity are **not** in the profile. They are `patb get` / `patb search` from the job or from the conversation.
