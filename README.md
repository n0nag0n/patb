# patb

Agents forget rules that live in a giant prompt. patb is a small CLI: the agent runs `patb get` / `search` / `query` and gets one decision. The rest stays on disk. Clone, `./install.sh`, paste `CORE.md` into every agent.

Pinky and the Brain is the project name. **Agents are told to run `patb`, never “Brain.”**

## Install

Needs Python 3.9+ (stdlib only — no pip).

```bash
git clone <this-repo> && cd patb && ./install.sh
export PATH="$HOME/.local/bin:$PATH"   # this session, if install printed it
patb
```

On a Grok Bot computer, data defaults to `/workspace/patb` when `/workspace` exists. Everywhere else, `~/.patb`. Override with `--home` or `PATB_HOME`.

Flags (no prompts — for an agent installing itself):

```bash
./install.sh --yes --cron --home /workspace/patb
```

`--cron` adds `* * * * * patb tick` to the user crontab. `tick` is Python, not a model. Idle minutes cost no tokens.

## What goes in the agent profile

`patb core` prints a versioned block. Paste it into **every** bot. Then two extra lines per bot:

```
You are Inbox Curator. PATB_AGENT=agent.inbox
```

See `examples/`. After `git pull` / upgrade: `patb core --check` and replace the pasted block if it is stale.

The profile is the standing self. Mail rules, GitHub rules, identity, other bots: **looked up**.

## Commands

| Command | What it does |
|---|---|
| `patb` | How to use the tool |
| `patb get KEY` | One body (secrets expanded). Exact key, then alias |
| `patb search "family link"` | Alias, then keywords. Ranked. Cold episodic hidden |
| `patb query --domain email --tag silent-delete` | Narrow relational filter |
| `patb due` / `patb tick` | Dry-run / fire due jobs |
| `patb set` / `propose` / `accept` | Write sqlite + markdown; candidates → locked |
| `patb secret set NAME` | Value on **stdin**. No dump command |
| `patb reindex` | Vault → sqlite (also auto if the index is stale) |
| `patb dump` / `import` | JSONL belt. Secrets are not in the dump |
| `patb consolidate` | Daily memory moves. Never edits CORE |
| `patb cron install` | Minute crontab for `tick` |
| `patb audit` | Fail if webhook URLs / tokens leaked into git files |
| `patb relate A B --circle family` | Roster links |

`--json` on most commands for machines. `--agent` or `PATB_AGENT` scopes per-bot working/episodic memory. Policies, protocols, and jobs are shared.

You may call `patb` many times in one task. Fetch only the current step.

## One record, two copies

A decision is one record: key, kind, body, aliases, tags, schedule, …

- **SQLite** (`$PATB_HOME/index.sqlite`) is what `get`/`search`/`query`/`tick` hit. Gitignore it.
- **Markdown** under `$PATB_HOME/vault/` is the git copy of the same row. Clone the vault, run `patb` (or `reindex`), the db fills itself.

Do not edit sqlite by hand. `patb set` writes both. Editing a `.md` and running `patb` reindexes.

Kinds: `protocol` (how), `policy` (what), `job` (when + which agent), `agent`, `identity`, `working` / `episodic` (per bot), `candidate`.

## Cron and Grok Bot webhooks

Do **not** run an LLM every minute to ask if work exists.

1. OS crontab calls `patb tick`.
2. If nothing is due, tick exits. No HTTP.
3. If a job is due, tick POSTs `{"key":"job.hourly.mail"}` to that **agent’s** webhook (`Authorization: Bearer`, sender key from secrets). One dispatcher routine per bot — not one Grok routine per job.
4. The bot runs `patb get` on that key and follows the body.

Webhook URL and sender key: `echo URL | patb secret set AGENT_INBOX_WEBHOOK_URL`. The agent markdown only stores the secret *name*.

`notify: exec` runs a local command instead (OpenClaw / Hermes). `PATB_JOB_KEY` is in the environment.

Overlapping ticks no-op (`flock`). Last-run is stamped before the POST (at most once per window).

## Secrets and PII

| | Git? |
|---|---|
| Policies with no PII | Yes |
| `${HOME_ADDRESS}` in a record | Yes (placeholder) |
| `secrets.env` values | **Never** |
| `vault/private/` | gitignored |

`patb get` expands `${NAME}` for that record only. There is no `patb secret dump`. If a bot can run a shell as the same Unix user, it can still `cat` the file — we do not pretend otherwise. CORE forbids it; the file is mode 0600; the CLI refuses webhook URLs and bearer tokens in markdown.

## Memory

Locked protocols/policies/jobs never decay (a yearly HSA rule must not LRU away).

Per-bot `working` / `episodic` can fade from **default search**. `patb consolidate` (nightly job) demotes cold working → episodic and lists hot candidates for you to `accept`. It never writes CORE.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
