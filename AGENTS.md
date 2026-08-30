# AGENTS.md

patb is a filing cabinet for AI teammates. A bot profile stays a few lines (`patb core` plus who this bot is). Standing instructions live as one record each. Before acting, a bot looks up the current step instead of loading the whole catalog.

This file is for people and coding agents working **on this repository**. It is not CORE. CORE (`CORE.md`, printed by `patb core`) is what operators paste into Grok / OpenClaw / similar bot profiles.

## Layout

- `src/patb/` — the CLI. Python 3.9+, **stdlib only**, no pip, no PyYAML.
- `tests/` — `unittest`. Run: `PYTHONPATH=src python3 -m unittest discover -s tests -v`
- `CORE.md` — versioned OS block bots paste. Must match baked `CORE_TEXT` in `src/patb/core.py`.
- `vault.example/` — seed records (optional `protocol.global`, household pattern, jobs).
- `install.sh` — clone-local wrapper onto `PATH`; optional user crontab for `patb tick`.
- `examples/` — profile tails and Grok-routine prompts.

Data on a machine (not this git tree):

| Path | Role |
|---|---|
| `$PATB_HOME/vault/` | Markdown source of truth. Commit to a **private** git repo. |
| `$PATB_HOME/index.sqlite` | Live index. Rebuild with `patb reindex`. Do not commit. |
| `$PATB_HOME/secrets.env` | `KEY=value`, mode `0600`. Never commit. No dump command. |

`PATB_HOME` is `/workspace/patb` when `/workspace` is writable (Grok Bot), else `~/.patb`. Override with `--home` / `PATB_HOME`. Home is mode `0700`; `vault/private/` is `0700`.

## Record kinds

`protocol` how to do a class of work · `policy` what to do with one thing · `job` what a scheduled routine loads · `agent` / `identity` · `working` live notes · `episodic` cooled working · `candidate` proposed, needs `patb accept`.

`protocol.global` is optional everyone-rules. `patb get protocol.global` miss means continue; do not invent it. Domain work stays in domain records. **Standing protocols are how. The live list of people or things is working notes you search** — do not stuff a roster into a protocol body.

Keys look like `email.usps`, `protocol.global`, `working.example.household`. Letters, digits, dot, underscore, hyphen only.

## How bots use the CLI

- Fetch one step: `patb get KEY` (exact key or alias). This is the only retrieve that expands `${NAME}`.
- Find a record: `patb search "two to four keywords"` or `patb query --domain … --tag …`.
- Write: `patb set` / `patb propose` / `patb accept`. Do not append standing rules to CORE or the agent profile file.
- Secrets: `echo VALUE | patb secret set NAME`, then put `${NAME}` in the record.
- Grok Bot has no OS crontab. Each Grok routine’s prompt is `patb get job.<name>` and follow only that body.
- Linux / OpenClaw: `patb tick` from user crontab fires due jobs (webhook or allowlisted exec).

## CORE version bump

When CORE text or the package version changes, update **all** of:

1. `src/patb/__init__.py` — `__version__` and `CORE_VERSION`
2. `CORE.md` (banner `patb CORE x.y.z` plus the body)
3. `src/patb/core.py` `CORE_TEXT` (stays in lockstep; `test_core_md_matches_baked_text` enforces this)
4. `vault.example/CORE.md`
5. Tests that assert the banner string

Do not grow CORE. Standing rules go in `patb set` / `patb propose`. Leave room in the version line; do not rebase older CORE sentences when adding a new patch.

## Invariants (do not undo)

These are product rules, not a separate security doc. Later changes must keep them:

- **Never add `patb secret get`** (or list / dump of values). Search already leaks the *name*. Retrieve is `patb get` on the record that contains `${NAME}`.
- `patb search` and `patb query` never expand secrets, even with `--full`.
- `patb get` expands `${NAME}` and warns if a known secret is named without a placeholder. Do not teach bots to open `secrets.env`.
- Print a secret in chat only when the human asked for that value.
- Record keys stay `[a-zA-Z0-9][a-zA-Z0-9._-]*`. Writes resolve under the vault; no `..`, no extra slashes, no symlink escape.
- `notify: exec` is only `patb consolidate` (or `reindex`, `audit`, `due`, `core`) with no extra argv. No pipes, no other binaries. Example job `job.daily.consolidate` must keep working.
- Webhook URLs are `https`, no redirects, no loopback / link-local / private / metadata hosts. Tokens stay in `secrets.env`.
- `patb dump` emits placeholders, never secret values, and omits `sensitivity: private` unless `--include-private`.
- `patb audit` fails closed on leaked tokens, world-readable `PATB_HOME` / `secrets.env` / sqlite, and disallowed exec jobs.
- `--agent` / `PATB_AGENT` is a local label, not authentication. Anyone with a shell on the box can pass another agent. CORE is the control for bots; do not pretend it is a kernel.

Do not commit `secrets.env`, `vault/private/`, or sqlite / WAL files.

## Style

Match neighboring code: stdlib, small modules, restricted frontmatter (no nested YAML), parameterized SQL, tests in `unittest` with a temp `PATB_HOME`. Do not add dependencies.
