---
name: d4-druid-advisor
description: Analyze Diablo IV Druid equipment and character data for the fixed D2Core build 1ZsP variant 9. Use when the user provides Druid equipment or panel screenshots, asks which item is better with exact numeric deltas, wants expected and theoretical maximum single-hit damage, needs character-panel weakness analysis, or wants enchanting, tempering, and masterworking recommendations that account for high-tier survivability.
---

# D4 德鲁伊装备顾问

Use the repository data and deterministic calculators to do arithmetic; retain judgement about game conditions, missing inputs, and recommendations.

## Locate the project

Resolve this skill directory through symlinks. Treat its repository root as three parents above
`scripts/run_advisor.py`. The current working directory does not matter; run atomic commands through
the installed Skill launcher:

```bash
"${CODEX_HOME:-$HOME/.codex}/skills/d4-druid-advisor/scripts/run_advisor.py" <d4advisor arguments>
```

## Gate on the ruleset

1. Run `version status` before damage analysis.
2. Reuse the locked ruleset while `refresh_required` is false; do not browse again.
3. When it is true or the screenshot build disagrees, refresh from official Blizzard sources and the matching d4data build before calculating.
4. Load `data/reference/fixed-build.json`. Keep `bd=1ZsP&var=9` fixed unless the user explicitly changes the build.

## Ingest inputs

1. Prefer one batch for multiple screenshots. The OCR engine is reused and ring slots are assigned in
   input order:

   ```bash
   "${CODEX_HOME:-$HOME/.codex}/skills/d4-druid-advisor/scripts/run_advisor.py" \
     ocr-batch IMAGE... \
     --output-dir data/user/candidates/batch \
     --require-complete
   ```

2. Inspect `batch-manifest.json` and the generated JSON text first. Do not open screenshots merely
   because flavor text, account-binding text, or other non-numeric metadata was ignored. Open only
   the specific image whose result has `review.required=true`, a missing critical field, an
   impossible value, or an unresolved numeric line that could affect the result.
3. Keep candidates separate. After the user explicitly confirms the batch is currently equipped,
   rerun with `--equip --require-complete`; this validates every item first and writes all slots in
   one atomic profile update. Do not use `--allow-review` unless the blocking fields were checked.
4. Use single-image `ocr IMAGE --output FILE` only for incremental candidates or targeted retries.
5. For multiple character-panel or Occultist screenshots, run `ocr-text-batch IMAGE... --output-dir
   DIR`. Inspect the JSON text before any image. Reuse `ocr-text` only for one targeted retry.
6. Reuse `data/user/current.json`. Ask only for fields whose uncertainty could reverse the result.
7. Never substitute planner-perfect rolls for the user's actual values.

## Choose the workflow

### Compare equipment

Read [references/model-contract.md](references/model-contract.md). Build A and B ledgers from the same character baseline, removing A before adding B. Include steady combat, full-buff boss, expected damage per Shred cast, sustained DPS when rotation inputs exist, and physical/elemental EHP.

Run `calc compare --input FILE`. Interpret breakpoints and survivability; the script supplies arithmetic, not the final recommendation. If missing attack-speed, cooldown, resource, armor, resistance, or life data can flip the winner, request only those fields.

### Calculate maximum single hit

Build ledgers for every plausible eligible single event, then run `calc damage-event --input FILE`
for each and select the actual maximum. If coefficients for another plausible event are missing,
name the selected event and label the result as a bound rather than claiming a global maximum. Report both:

- `expected_single_hit`: probability-weighted crit, vulnerable, and condition coverage;
- `theoretical_single_hit`: one event with every legal condition active.

Keep `expected_damage_per_cast` separate. Never present Waxing Gibbous repeated attacks as one damage number.

### Audit a character panel

Construct version- and scenario-specific targets, then run `calc audit-panel --input FILE`. Rank objective gaps, overcaps, breakpoints, and marginal factor gains. Apply judgement to recommend the top three weaknesses, tempering, and masterworking targets. Give both damage-first and high-tier-survival paths; prefer survival when damage already exceeds the survivable ceiling.

Treat armor and resistances as diminishing-returns ratings in the current ruleset. Store the raw
rating and the in-game tooltip's resulting reduction separately. Audit `armor_damage_reduction`
against the displayed 90% cap; never use 10,000 or another fixed armor rating as a universal cap.
Do not automatically treat the cap as the build target. Derive a scenario target separately, and do
not project rating changes into reduction without a matching ruleset conversion curve or a new
in-game tooltip observation.

### Recommend equipment enchantments

1. Load `data/reference/enchantment-rules.json`. When its candidate pool is not cached for the
   locked ruleset, request the smallest missing evidence: a screenshot of the Occultist's complete
   “可能属性” list with the item and roll ranges visible. Run `ocr-text IMAGE --output FILE`, then
   verify only low-confidence candidates that could change the ranking. Never infer legality from
   the generic stat alias registry.
2. Identify the one affix the locked ruleset legally allows the user to replace. Never treat an
   implicit, aspect, unique power, temper, or locked affix as an enchantment target.
3. Run `profile fingerprint` and put the returned SHA-256 value in `profile_fingerprint`. For each
   legal replacement, remove the existing affix first and rebuild the complete character
   outcome at the candidate's minimum, declared expected, and maximum roll. Record `replace_roll`
   and `target_roll` so the lost stat and offered range remain auditable.
4. Include expected single hit, sustained DPS when available, physical/elemental EHP, and projected
   attack-speed, cooldown, resource, armor, resistance, or critical breakpoints that can change the
   recommendation. Supply complete `after_stats` for all three roll bounds; never overlay a partial
   candidate onto the current stats because that can retain the removed affix.
5. Run `calc enchant --input FILE`. Report both damage-first and high-tier-survival rankings, roll
   ranges, lost-stat opportunity cost, confidence, and any breakpoint crossed or lost.
6. Save the advisory result with `profile save-enchantment-analysis --input RESULT_FILE` when the
   user wants the snapshot updated. This only updates analysis and never changes equipped items.
7. Do not write the proposed enchantment into current equipment until the user confirms the actual
   in-game result. If the enchanted/locked marker is unclear, request only that item's detail view.

## Persist and render

Merge only user-confirmed panel data and analysis into the profile. A read-only comparison or an
unconfirmed candidate must not change it. Every authorized write regenerates
`data/user/snapshot.html`; `profile render` regenerates it manually. Return a clickable absolute
link to that page after an authorized profile update.

## Report with integrity

Follow [references/report-contract.md](references/report-contract.md). Always state ruleset, scenario, source inputs, exact absolute/percentage deltas, and confidence. “Exact” means reproducible within the declared model. Use bounds for hidden or uncalibrated mechanics; never invent a single value.

Convert displayed percentage multipliers at the input boundary: `x18%` becomes the total factor
`1.18`. Never pass the displayed `18` as a factor. Preserve the displayed roll and converted factor
in the report so the arithmetic is auditable.
