---
name: d4-druid-advisor
description: Analyze Diablo IV Druid equipment and character data for the fixed D2Core build 1ZsP variant 9. Use when the user provides Druid equipment or panel screenshots, asks which item is better with exact numeric deltas, wants expected and theoretical maximum single-hit damage, needs character-panel weakness analysis, or wants tempering and masterworking recommendations that account for high-tier survivability.
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

1. Run `ocr IMAGE --output data/user/candidates/NAME.json` for every equipment screenshot.
2. Check `review.required`, low-confidence fields, and `unparsed_lines`. Read the image only for unresolved fields that matter.
3. Keep candidates separate. Use `profile set-item` only after the user confirms an item is equipped.
4. Reuse `data/user/current.json`. Ask only for fields whose uncertainty could reverse the result.
5. Never substitute planner-perfect rolls for the user's actual values.

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
