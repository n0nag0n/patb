# patb

**A filing cabinet for AI teammates.** You stop stuffing 150 rules into a Grok Bot profile. The bot looks up the one rule it needs.

If you run Grok Bot (or OpenClaw, Hermes, nanobot) and you keep repeating a rule like an email rule for “forward emails from Bob to Joe” — and the bot still asks what to do with it  — this repo is for you.

## Why this exists

A bot’s profile is like working memory. It is tiny and unreliable once you put a novel in it.

What actually happens:

1. You teach a bot like an Inbox Curator how to handle invoices, bills, GitHub, retail stores, etc.
2. Those instructions live in the profile, or in a heartbeat prompt, or in three slightly different copies.
3. The model wades through the blob, drops a line, and you spend the next hour correcting it.

**patb** puts each decision in its own record on the bot’s computer. The profile stays a few lines: *before you act, run `patb`*. When a retail email shows up, the bot runs `patb search retail` and gets one paragraph: trash it, do not mention it. Github emails are a different lookup. invoice rules shouldn't load during Github mail.

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

Paste `patb core` into each agent profile. That is the OS. Do not grow it.

Shared-everyone rules go in `protocol.global`, not CORE and not the profile tail. Change them with `patb set` / `patb propose` on that key. Domain rules stay policies/protocols. Only the bots that do that work fetch them. Before a bot acts it runs `patb get protocol.global`; if the key is missing, it continues. Copy `vault.example` if you want the stub; an empty vault is still valid. Do not put USPS, HSA, or `mail.scan` in global.

Then two lines that are *this* Bot:

```
You are Inbox Curator. PATB_AGENT=agent.inbox
```

See `examples/`. After you `git pull` and upgrade patb, run `patb core --check` and replace the pasted block if it is stale.

### When you add a bot

A new bot's profile is empty until someone pastes CORE, so CORE cannot teach a bot that does not have CORE yet. The creator (human or front-door agent) does the paste. Do not put this checklist in CORE.

1. Backup the old profile if it already has rules.
2. Paste current `patb core` into that bot's profile. That is the OS. Do not grow it.
3. Two identity lines: `You are NAME. PATB_AGENT=agent.<slug>`
4. Standing rules go in `patb set` / `patb propose`, not the profile file.
5. Point each Grok routine at `patb get job.<name>`.
6. If you have a front-door/chief bot, give it `protocol.patb.onboard` (copy from `vault.example`) so it does this without being reminded.

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

### 5. First run: daily consolidate routine

`job.daily.consolidate` is `notify:exec` / `@daily` and only fires through `patb tick`, which needs OS crontab. Grok Bot has none, so a Grok routine is the clock.

Create one daily Grok routine at **8:00 AM local, all days.** The prompt is only:

```text
export PATH="$HOME/.local/bin:$PATH"
patb get job.daily.consolidate
follow only that body
```

Stay quiet unless there are hot candidates. Never edit CORE.

## Everyday use

| You want | You run / you tell the bot |
|---|---|
| The retail rule | `patb get email.retail` |
| “What do I do with Family Link emails?” | `patb search "family link"` |
| “What size were those tires on the Cadenza?” | `patb search "tire size cadenza"` (keywords, not the full sentence) |
| Shared everyone-rules | `patb get protocol.global` (a miss means continue) |
| Change everyone-rules | `patb set` / `patb propose` on `protocol.global` |
| Every silent-delete mail rule | `patb query --domain email --tag silent-delete` |
| Add or change a rule | `patb set …` or edit the markdown, then `patb` |
| Address, webhook, API key, password, or phone | `echo VALUE \| patb secret set NAME` then put `${NAME}` in the record. Retrieve with `patb get`. There is no `patb secret get` |
| What an agent should paste | `patb core` |

The bot may call `patb` many times in one task. That is the point: fetch this step, not the whole cabinet. Shared-everyone rules live in `protocol.global`, not CORE and not the profile. Domain rules stay policies/protocols; only the bots that do that work fetch them.

## Linux / OpenClaw / a box with crontab

On a normal Linux user account, `patb tick` can be the clock (Python only — no model). Idle minutes cost nothing; when a job is due it can POST a webhook or run a command. Webhooks must be public `https` (no redirects, no localhost). `notify: exec` may only run `patb consolidate` (or `reindex`, `audit`, `due`, `core`) — no other binaries.

```bash
./install.sh --yes --cron
```

Grok Bot’s computer cannot do this. Skip `--cron` there.

Webhook wake (optional, later): store the Bot’s routine URL and sender key with `patb secret set`. Tick then knocks on that Bot only when work is due. Not required for the Grok-routine setup above.

## What gets stored where

Each decision is **one record** (key + the text the bot should obey).

- **Markdown** under `$PATB_HOME/vault/` is what you commit to a **private** git repo. Survives the computer dying.
- **SQLite** (`$PATB_HOME/index.sqlite`) is the live index `get`/`search`/`query` hit. Rebuilt with `patb reindex`. Do not commit it.
- **Secrets** (`$PATB_HOME/secrets.env`) never go in git. Mode `0600`. `$PATB_HOME` is `0700`. Store with `patb secret set NAME` (value on stdin), then put `${NAME}` in the record. `patb get` expands it. There is no `patb secret get`. Do not read `secrets.env`. `patb search` and `patb query` (including `--full`) leave `${NAME}` as a placeholder.

Pattern:

```bash
echo 'the-number' | patb secret set EXAMPLE_PHONE
```

Working record body:

```text
Phone: ${EXAMPLE_PHONE}
```

Anti-example (will not print the number):

```text
Phone is patb secret EXAMPLE_PHONE
```

`patb get` warns: this record names EXAMPLE_PHONE without `${EXAMPLE_PHONE}`, so get cannot print it; put the placeholder in the record; do not open secrets.env. Fix with `${EXAMPLE_PHONE}`. Print a secret in chat only when the human asked for that value.

`protocol` = how to do a class of work (scan mail, pick who to contact). `policy` = what to do with one thing (USPS). `job` = what a scheduled routine should load. Shared across all Bots on the computer. Working notes and “what happened Tuesday” can be tagged to one Bot (`PATB_AGENT`).

A standing protocol is how to pick people. It is not the live roster. Search working notes for the live list; the protocol is not the roster. `vault.example` ships `protocol.household.pick` plus one fake household in `working.example.household` (Cedar household; Phone: `${EXAMPLE_PHONE}`). Alias and tag the working note with the words you will search (a household member’s first name is a tag; FTS will miss a part-member otherwise).

Locked policies do not fade. A bill you pay once a year must not fall out because it was rarely looked up.

## Commands

| Command | What it does |
|---|---|
| `patb` | Command map |
| `patb get KEY` | One decision (exact key, then alias). Expands `${NAME}` |
| `patb search "…"` | 2–4 keywords, then aliases inside the phrase |
| `patb query --domain email --tag silent-delete` | Several rows, still narrow |
| `patb set` / `propose` / `accept` | Write a record; candidates need you to accept |
| `patb secret set NAME` | Value on stdin. Retrieve with `patb get` on the record that has `${NAME}`. No `patb secret get`, no dump of values |
| `patb reindex` | Vault → sqlite |
| `patb dump` / `import` | JSONL backup (placeholders; omits private unless `--include-private`) |
| `patb core` | Versioned profile block |
| `patb due` / `tick` | Linux clock (not Grok Bot) |
| `patb audit` | Fail if tokens leaked into markdown |
| `patb consolidate` | Rank old notes down; never edits CORE |

`--json` for machines. `--home` / `PATB_HOME` if you are not using the default directory.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

GitHub Actions runs that on pull requests and pushes to `master`, on Python 3.9–3.13. No pip.

The name is a Pinky and the Brain joke for humans. Classic cartoon I watched as a kid. Agents only ever see the command `patb`.
