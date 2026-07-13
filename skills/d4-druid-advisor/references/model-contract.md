# 计算模型契约

## 伤害事件账本

Pass JSON with these fields to `calc damage-event`:

```json
{
  "ruleset": "3.1.0.72592",
  "scenario": "满增益首领",
  "event": "Shred largest hit",
  "weapon_damage": 1000,
  "skill_coefficient": 1.5,
  "additive_bonus": 2.0,
  "multipliers": [
    {"id": "storm_shepherd", "factor": 1.6, "uptime": 0.9, "confidence": 1.0}
  ],
  "crit": {"chance": 0.9, "factor": 3.5},
  "vulnerable": {"uptime": 1.0, "factor": 1.8},
  "repeat": {"probability": 0.33, "max_extra_attacks": 4},
  "casts_per_second": 2.0,
  "resource_uptime": 0.95,
  "confidence": 0.9
}
```

- Express probabilities/uptimes as `0..1`.
- Express independent multipliers as total factors (`1.18`, not `18`).
- Express `additive_bonus` as bonus over base (`2.0` means `+200%`).
- Use one ledger per scenario and damage event.
- `ruleset`, `scenario`, and `event` are required. `weapon_damage` is the canonical source field;
  the legacy `base_damage` alias is accepted only for existing ledgers.
- Set `eligible` to `false` when an independent, critical, or vulnerable condition cannot legally
  occur. Zero uptime/chance is treated as ineligible for the theoretical ceiling.
- Derive theoretical single-hit from the same legal sources at full coverage; do not add repeat attacks.

## A/B comparison

Pass matching ledgers and defense states to `calc compare`:

```json
{
  "scenarios": {
    "steady": {"a": {}, "b": {}},
    "boss_full_buff": {"a": {}, "b": {}}
  },
  "defense": {
    "physical": {
      "a": {"life": 10000, "barrier": 0, "reductions": [0.2]},
      "b": {"life": 11000, "barrier": 0, "reductions": [0.2]}
    }
  },
  "breakpoints": {
    "attack_speed": {"a": 0.95, "b": 1.05, "thresholds": [0.5, 1.0]}
  }
}
```

Build both sides from source-level stats. Do not add the candidate to a town panel that still contains the equipped item. Keep scenario conditions identical.

## Enchantment analysis

Pass complete before/after outcomes to `calc enchant`; every option must remove the old affix before
adding the proposed roll:

```json
{
  "ruleset": "3.1.0.72592",
  "scenario": "高层常态",
  "profile_fingerprint": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "confidence": 0.9,
  "stats": {"attack_speed_bonus": 0.48},
  "breakpoints": {
    "attack_speed": {"metric": "attack_speed_bonus", "thresholds": [0.25, 0.5]}
  },
  "objectives": {
    "damage_priority": {"weights": {"expected_single_hit": 1.0}},
    "survival_priority": {"weights": {"expected_single_hit": 0.3, "physical_ehp": 0.7}}
  },
  "options": [{
    "id": "ring_2_cdr_to_life",
    "slot": "ring_2",
    "replace_stat": "cooldown_reduction",
    "target_stat": "max_life",
    "replace_roll": {"value": 10, "unit": "percent"},
    "target_roll": {
      "minimum": 800,
      "expected": 1000,
      "maximum": 1200,
      "unit": "flat"
    },
    "outcomes": {
      "expected_single_hit": {
        "current": 100000,
        "after": {"minimum": 98000, "expected": 99000, "maximum": 100000}
      },
      "physical_ehp": {
        "current": 20000,
        "after": {"minimum": 21000, "expected": 21500, "maximum": 22000}
      }
    },
    "after_stats": {
      "minimum": {"attack_speed_bonus": 0.48},
      "expected": {"attack_speed_bonus": 0.48},
      "maximum": {"attack_speed_bonus": 0.48}
    }
  }]
}
```

- `after.expected` is a declared planning point. Call it an RNG expectation only when the roll
  distribution is calibrated; otherwise state the midpoint assumption.
- Objective weights are normalized by the calculator. Scores are weighted percentage changes, not
  hidden game ratings.
- Use `direction: "lower"` only for outcome metrics where a smaller final value is beneficial.
- Outcome keys `minimum`, `expected`, and `maximum` identify the target affix's three roll points;
  they do not promise ascending final metric values. A lower-is-better metric may legitimately
  produce descending results across those points.
- Preserve the full range when the offered enchantment roll is not known yet.
- `replace_roll` and `target_roll` preserve the game's displayed roll (`10` means `10%`). They are
  audit evidence, not multiplier factors. Convert them separately when rebuilding each outcome.
- Every option must use the same `current` and `direction` for a shared outcome metric. The
  calculator rejects mismatched baselines instead of ranking incomparable candidates.
- When breakpoints are declared, each option must provide `after_stats.minimum`, `.expected`, and
  `.maximum` with every breakpoint metric present. These are complete post-replacement breakpoint
  states, not overlays; use `0` when removing an affix leaves a known zero value and `null` only for
  a genuinely unknown value.
- Top-level `confidence` describes common evidence. Each candidate confidence is the lower of that
  common value and its own declared confidence; a weak unrelated candidate does not lower the
  reported common confidence for every other option.
- `profile save-enchantment-analysis --input RESULT_FILE` accepts the calculator result, validates
  candidate/ranking references, and stores it under analysis only. It never confirms or changes the
  equipped item's enchantment.
- Generate `profile_fingerprint` immediately before building candidates. The calculator carries it
  into the result; saving rejects a mismatched current character, and the snapshot marks an older
  result stale after equipment, stats, paragon overrides, or fixed-build identity changes.
- Candidate legality and roll ranges must come from a matching cached enchantment pool or the
  current item's in-game Occultist “可能属性” list. When
  `data/reference/enchantment-rules.json` reports `candidate_pool.status=not_cached`, that screenshot
  is a required input rather than an optional confidence improvement.

## Panel audit

Pass `stats` and scenario-specific `rules` to `calc audit-panel`:

```json
{
  "ruleset": "3.1.0.72592",
  "scenario": "高层常态",
  "confidence": 0.9,
  "stats": {
    "crit_chance": 0.92,
    "armor": 19296,
    "armor_damage_reduction": 0.712
  },
  "rules": {
    "metrics": {
      "crit_chance": {"target": 0.9, "cap": 1.0, "priority": 2, "category": "offense"},
      "armor_damage_reduction": {
        "target": 0.8,
        "cap": 0.9,
        "priority": 3,
        "category": "survival"
      }
    },
    "marginal_options": [
      {"id": "vulnerable", "current_factor": 1.5, "new_factor": 1.68}
    ]
  }
}
```

Derive targets from the locked ruleset and chosen combat scenario. Do not treat a generic target as a universal cap. The calculator returns a dimensionless relative gap times the declared priority; use it as an audit ordering aid, not as a universal damage/survival score. Put attack-speed, cooldown, or resource thresholds under `rules.breakpoints`; an option may provide `projected_stats` to expose whether it crosses a tier.

Armor is a diminishing-returns rating in the current ruleset. Preserve the displayed armor rating as
evidence, but audit the resulting displayed damage reduction against its 90% cap. Never substitute a
fixed rating such as 10,000 for the cap. A projected armor change needs a matching ruleset conversion
curve or a new in-game tooltip observation before converting rating into damage reduction. The cap is
not automatically the target; derive the target from the declared scenario.

`marginal_options.current_factor/new_factor` must describe the complete before/after outcome after
the replaced affix is removed, so their ratio includes opportunity cost. They are total output
factors, not raw damage-reduction percentages. Put actual
damage reduction in the A/B defense state so the EHP formula handles it. If an option's semantics
are not known, label it unknown instead of converting a factor gain into “damage reduction.”

## Completeness decision

Calculate directly when all plausible missing values leave the A/B intervals disjoint. Request data when an unknown cap, breakpoint, uptime, or defense value makes the intervals overlap. State damage-only conclusions when survival data is absent.
