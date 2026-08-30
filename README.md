# patb

**A filing cabinet for AI teammates.** You stop stuffing 150 rules into a Grok Bot profile. The bot looks up the one rule it needs.

If you run Grok Bot (or OpenClaw, Hermes, nanobot) and you keep repeating “always trash USPS, never mention it” — and the bot still mentions it — this repo is for you.

## Why this exists

A bot’s profile is like working memory. It is tiny and unreliable once you put a novel in it.

What actually happens:

1. You teach Inbox Curator how to handle USPS, Family Link, Wordfence, bills, GitHub, Telegram.
2. Those instructions live in the profile, or in a heartbeat prompt, or in three slightly different copies.
3. The model wades through the blob, drops a line, and you spend the next hour correcting it.

**patb** puts each decision in its own record on the bot’s computer. The profile stays a few lines: *before you act, run `patb`*. When a USPS email shows up, the bot runs `patb search usps` and gets one paragraph: trash it, do not mention it. Family Link is a different lookup. GitHub rules never load during mail.

Same idea as a person who does not recite their tax history every morning. They know the cabinet exists, and they open the right folder.

## Grok Bot: setup

Grok Bot’s cloud computer **has no OS crontab**. Do not pass `--cron`. Do not add a routine that runs every minute and asks `patb due`. That puts the model back on the clock, which is the failure this tool is meant to avoid.

Your **existing Grok routines are the clock.** Each one should fetch one job and stop.

### 1. Install the CLI on the Bot computer

In a Bot conversation that can use the computer:

```bash
git clone https://github.com/<you>/patb.git
cd patb
./install.sh --yes --home /workspace/patb
export PATH="$HOME/.local/bin:$PATH"
patb
```

Python 3.9+, no pip. Data lives in `/workspace/patb` when `/workspace` exists, otherwise `~/.patb`.

### 2. Paste CORE into every Bot

```bash
patb core
```

Put that block in each Bot’s profile (Edit Profile → description). Then two lines that are *this* Bot:

```
You are Inbox Curator. PATB_AGENT=agent.inbox
```

See `examples/`. After you `git pull` and upgrade patb, run `patb core --check` and replace the pasted block if it is stale.

### 3. Store a rule

```bash
patb set email.usps --kind policy --domain email \
  --alias usps --alias "informed delivery" --tag silent-delete \
  --body "Trash USPS Informed Delivery. Do not mention it in the pulse or Telegram."
```

Or add a markdown file under `/workspace/patb/vault/policies/` and run `patb reindex`.

Try it: `patb get email.usps` or `patb search "informed delivery"`.

Add aliases for how you actually ask (`tire size`, `my car`), not only the official name. Search wants 2–4 keywords. A pasted sentence still hits if those phrases are on the record.

### 4. Point each Grok routine at one job

Keep the schedules you already use (hourly mail, telegram, briefing, …). Change the **prompt** so the routine does not contain the procedure. The procedure lives in patb.

```text
Run this command and follow only the body it prints:

  patb get job.hourly.mail

Do not load other policies. Do not summarize the catalog.
If patb is missing: export PATH="$HOME/.local/bin:$PATH"
```

Save the job itself once:

```bash
patb set job.hourly.mail --kind job --schedule "0 * * * *" \
  --body "Run: patb get protocol.mail.scan
Follow only that record. For each message, patb search the sender/subject, then obey that one result."
```

Copy-paste templates: [`examples/grok-routine.md`](examples/grok-routine.md).

One Grok routine ↔ one `job.*` key. Same times as today. The model wakes because **Grok** scheduled it, then reads **one** file.

## Everyday use

| You want | You run / you tell the bot |
|---|---|
| The USPS rule | `patb get email.usps` |
| “What do I do with Family Link?” | `patb search "family link"` |
| “What size were those tires on the Cadenza?” | `patb search "tire size cadenza"` (keywords, not the full sentence) |
| Every silent-delete mail rule | `patb query --domain email --tag silent-delete` |
| Add or change a rule | `patb set …` or edit the markdown, then `patb` |
| Address, webhook, API key | `echo VALUE \| patb secret set NAME` then put `${NAME}` in the record |
| What an agent should paste | `patb core` |

The bot may call `patb` many times in one task. That is the point: fetch this step, not the whole cabinet.

## Linux / OpenClaw / a box with crontab

On a normal Linux user account, `patb tick` can be the clock (Python only — no model). Idle minutes cost nothing; when a job is due it can POST a webhook or run a command.

```bash
./install.sh --yes --cron
```

Grok Bot’s computer cannot do this. Skip `--cron` there.

Webhook wake (optional, later): store the Bot’s routine URL and sender key with `patb secret set`. Tick then knocks on that Bot only when work is due. Not required for the Grok-routine setup above.

## What gets stored where

Each decision is **one record** (key + the text the bot should obey).

- **Markdown** under `$PATB_HOME/vault/` is what you commit to a **private** git repo. Survives the computer dying.
- **SQLite** (`$PATB_HOME/index.sqlite`) is the live index `get`/`search`/`query` hit. Rebuilt with `patb reindex`. Do not commit it.
- **Secrets** (`$PATB_HOME/secrets.env`) never go in git. Records may say `${HOME_ADDRESS}`; `patb get` fills it in.

`protocol` = how to do a class of work (scan mail). `policy` = what to do with one thing (USPS). `job` = what a scheduled routine should load. Shared across all Bots on the computer. Working notes and “what happened Tuesday” can be tagged to one Bot (`PATB_AGENT`).

Locked policies do not fade. A bill you pay once a year must not fall out because it was rarely looked up.

## Commands

| Command | What it does |
|---|---|
| `patb` | Command map |
| `patb get KEY` | One decision (exact key, then alias) |
| `patb search "…"` | 2–4 keywords, then aliases inside the phrase |
| `patb query --domain email --tag silent-delete` | Several rows, still narrow |
| `patb set` / `propose` / `accept` | Write a record; candidates need you to accept |
| `patb secret set NAME` | Value on stdin. No dump command |
| `patb reindex` | Vault → sqlite |
| `patb dump` / `import` | JSONL backup (no secret values) |
| `patb core` | Versioned profile block |
| `patb due` / `tick` | Linux clock (not Grok Bot) |
| `patb audit` | Fail if tokens leaked into markdown |
| `patb consolidate` | Rank old notes down; never edits CORE |

`--json` for machines. `--home` / `PATB_HOME` if you are not using the default directory.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The name is a Pinky and the Brain joke for humans. Agents only ever see the command `patb`.
