# Druid Data Advisor Repository Instructions

## Scope

These instructions apply to the entire repository.

- Keep the default build fixed to D2Core `bd=1ZsP&var=9` unless the user explicitly changes it.
- Treat `data/user/current.json` as the single source of truth for the currently equipped character.
- Treat files under `data/user/candidates/` as unconfirmed candidates; a comparison must not equip them.
- Use `season13-buckets-v1` for current damage work. `legacy-independent-v0` is only for reproducing old approximate ledgers.

## Command entrypoint

Prefer the installed Skill launcher so the command works independently of the current directory:

```bash
"${CODEX_HOME:-$HOME/.codex}/skills/d4-druid-advisor/scripts/run_advisor.py" <arguments>
```

From the repository on Windows, `.venv\Scripts\d4advisor.exe <arguments>` is the equivalent local entrypoint.

## Common commands

```bash
# Ruleset and fixed build
d4advisor version status

# Equipment OCR
d4advisor ocr IMAGE --output data/user/candidates/item.json
d4advisor ocr-batch IMAGE... \
  --output-dir data/user/candidates/batch \
  --require-complete

# Generic panel/Occultist text OCR
d4advisor ocr-text IMAGE --output data/inbox/panel.json
d4advisor ocr-text-batch IMAGE... --output-dir data/inbox/panel-batch

# Character snapshot
d4advisor profile init
d4advisor profile show
d4advisor profile merge data/inbox/character-fields.json
d4advisor profile set-item --slot ring_2 --item-json data/user/candidates/item.json
d4advisor profile fingerprint
d4advisor profile render

# Fast snapshot-based item replacement
d4advisor calc compare-item \
  --slot ring_2 \
  --candidate data/user/candidates/new-ring.json \
  --event shred

# Full-model fallback and other calculations
d4advisor calc damage-event --input data/inbox/damage-ledger.json
d4advisor calc compare --input data/inbox/comparison.json
d4advisor calc audit-panel --input data/inbox/panel-audit.json
d4advisor calc enchant --input data/inbox/enchantment-options.json \
  --output data/inbox/enchantment-result.json
d4advisor calc chain-attacks --probability 0.33 --max-extra 4
d4advisor calc ehp --life 10000 --reductions 0.2 0.3
```

## Standard workflow

### 1. Synchronize and gate the ruleset

1. Before editing code, run `git fetch` and safely integrate the tracked remote branch, preferably with `git pull --rebase`.
2. Before damage analysis, run `version status`.
3. When `refresh_required=false`, reuse the locked ruleset and do not browse again.
4. When it is true or the screenshot build conflicts with the lock, refresh from official Blizzard sources and the matching `DiabloTools/d4data` build before calculating.
5. Load `data/reference/fixed-build.json`; do not silently switch the fixed build or variant.

### 2. Ingest screenshots through OCR first

1. Batch equipment screenshots with `ocr-batch`; batch panel screenshots with `ocr-text-batch` so the OCR engine initializes only once.
2. Inspect generated JSON, `batch-manifest.json`, confidence values, unresolved lines, and `review.required` before opening any screenshot.
3. Do not inspect an image merely because flavor text, binding text, or other non-numeric metadata was ignored.
4. Open only the specific image with a missing critical value, impossible value, unresolved numeric line that can change the result, or `review.required=true`.
5. Never replace the user's actual rolls with planner-perfect rolls.

### 3. Update the equipped snapshot only after confirmation

1. Keep OCR candidates separate until the user explicitly confirms they are currently equipped.
2. For a confirmed complete equipment batch, rerun `ocr-batch` with `--equip --require-complete`; all items must validate before the single atomic profile write.
3. Do not use `--allow-review` unless every blocking field was checked.
4. Merge only user-confirmed panel values and analyses.
5. After an authorized profile write, ensure `data/user/snapshot.html` is regenerated and return its absolute path to the user.

### 4. Compare equipment with snapshot replacement first

Use `calc compare-item` for supported Shred replacements. Its required order is:

1. Load and calculate the current snapshot.
2. Clone the snapshot in memory.
3. Remove the entire equipped item from the selected slot.
4. Insert the complete candidate item.
5. Rebuild derived panel values and every named multiplier bucket from all sources.
6. Recalculate the same event and scenario.
7. Return current/candidate values, exact deltas or bounds, component changes, warnings, and blocking reasons.

Never add candidate affixes to a panel that still contains the old item. A read-only comparison must not mutate `current.json`.

If `blocking_reasons` is empty, use the atomic result directly. Read `skills/d4-druid-advisor/references/model-contract.md` and `docs/season13-damage-formula.md`, then build full A/B ledgers only when the atom reports an unsupported event, unknown changed power, changed additive-damage affix, weapon-set base-damage change, or skill-rank coefficient change.

### 5. Report damage with declared precision

- Report `expected_single_hit` separately from the full-buff theoretical critical/vulnerable hit.
- Keep expected damage per cast and sustained DPS separate from a single hit.
- Repeated attacks are separate events; never combine them into one displayed hit.
- If the snapshot lacks the true additive pool, skill coefficient, enemy factor, condition uptime, or another required input, return a strict bound or a missing-input result instead of guessing.
- Ask only for the smallest field or screenshot capable of resolving a decision.

### 6. Audit panels and enchantments

- Treat armor and resistance as diminishing-return ratings. Audit the displayed armor damage reduction against its current 90% cap; never use a fixed armor rating such as 10,000 as a universal cap.
- For enchantments, load `data/reference/enchantment-rules.json`. If the pool is not cached, use the complete in-game Occultist “可能属性” list as the legality source.
- Run `profile fingerprint` immediately before an enchantment analysis.
- Remove the old affix before adding each minimum/declared-expected/maximum replacement roll.
- Save enchantment analysis only when the user wants it persisted; never mark a proposed enchantment as equipped before the user confirms the in-game result.

## Damage correctness invariants

- Same-name multiplier affixes add inside their bucket before buckets multiply.
- `critical_damage_multiplier` belongs to the critical bucket.
- `vulnerable_damage_multiplier` belongs to the vulnerable bucket.
- `damage_multiplier` plus only the physical/elemental/weapon-gem multipliers eligible for the event belong to the all-damage bucket.
- Only verified independent powers belong to `standalone_multipliers`.
- Convert a displayed same-bucket `x31%` to bonus `0.31`; convert a verified independent `31%[x]` power to factor `1.31`.
- Do not use the character panel's top composite Critical/Vulnerable/element value as the additive pool. Use the hover tooltip's bottom item/Paragon additive value.
- Preserve hidden-precision uncertainty for rounded displayed affixes.
- “Exact” means reproducible for the declared ruleset, event, state, and inputs; it does not imply knowledge of unpublished server precision or bugs.

## Validation before delivery

Run checks proportional to the change. For source or Skill workflow changes, use at least:

```bash
python -m compileall -q src
python -m pytest -q
python "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-creator/scripts/quick_validate.py" \
  skills/d4-druid-advisor
git diff --check
```

- On Windows, set `PYTHONUTF8=1` when `quick_validate.py` would otherwise read UTF-8 Markdown with the legacy locale.
- Run a representative CLI smoke calculation for any changed calculator or command.
- Do not add or push test source directories, fixtures, test data, or test-only helpers unless the user explicitly requests them.
- Validate every edited text file as strict UTF-8 and keep Chinese text as readable UTF-8 literals rather than `\uXXXX` escapes.

## Git delivery

- Before committing, inspect `git status` and exclude ignored files, `.env` files, credentials, caches, generated OCR scratch data, and other non-committable artifacts.
- Include all other current committable workspace changes when the user asks for a commit.
- Push the resulting commit to the tracked remote branch; if no upstream exists, set it during the first push.
