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

## Panel audit

Pass `stats` and scenario-specific `rules` to `calc audit-panel`:

```json
{
  "ruleset": "3.1.0.72592",
  "scenario": "高层常态",
  "confidence": 0.9,
  "stats": {"crit_chance": 0.92, "armor": 9000},
  "rules": {
    "metrics": {
      "crit_chance": {"target": 0.9, "cap": 1.0, "priority": 2, "category": "offense"},
      "armor": {"target": 10000, "priority": 3, "category": "survival"}
    },
    "marginal_options": [
      {"id": "vulnerable", "current_factor": 1.5, "new_factor": 1.68}
    ]
  }
}
```

Derive targets from the locked ruleset and chosen combat scenario. Do not treat a generic target as a universal cap. The calculator returns a dimensionless relative gap times the declared priority; use it as an audit ordering aid, not as a universal damage/survival score. Put attack-speed, cooldown, or resource thresholds under `rules.breakpoints`; an option may provide `projected_stats` to expose whether it crosses a tier.

`marginal_options.current_factor/new_factor` must describe the complete before/after outcome after
the replaced affix is removed, so their ratio includes opportunity cost. They are total output
factors, not raw damage-reduction percentages. Put actual
damage reduction in the A/B defense state so the EHP formula handles it. If an option's semantics
are not known, label it unknown instead of converting a factor gain into “damage reduction.”

## Completeness decision

Calculate directly when all plausible missing values leave the A/B intervals disjoint. Request data when an unknown cap, breakpoint, uptime, or defense value makes the intervals overlap. State damage-only conclusions when survival data is absent.
