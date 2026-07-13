from __future__ import annotations

import html
import json
import re
from pathlib import Path, PureWindowsPath
from typing import Any

from .profile_fingerprint import character_fingerprint


SLOTS = (
    ("helm", "头盔"),
    ("chest", "胸甲"),
    ("gloves", "手套"),
    ("pants", "裤子"),
    ("boots", "靴子"),
    ("amulet", "项链"),
    ("ring_1", "戒指 1"),
    ("ring_2", "戒指 2"),
    ("weapon", "主手"),
    ("totem", "副手"),
)

STAT_GROUPS = (
    (
        "进攻",
        (
            ("weapon_damage", "武器伤害", "number"),
            ("willpower", "意力", "number"),
            ("crit_chance", "暴击率", "percent"),
            ("vulnerable_damage_multiplier", "易伤倍率", "percent"),
            ("attack_speed_bonus", "攻速加成", "percent"),
            ("cooldown_reduction", "冷却缩减", "percent"),
        ),
    ),
    (
        "资源与生存",
        (
            ("resource_generation", "资源生成", "percent"),
            ("max_resource", "资源上限", "number"),
            ("max_life", "最大生命", "number"),
            ("armor", "护甲", "number"),
            ("all_resistance", "所有抗性", "percent"),
            ("damage_reduction", "综合减伤", "percent"),
            ("fortify", "强固", "number"),
            ("barrier", "屏障", "number"),
        ),
    ),
    (
        "元素抗性",
        (
            ("resistances.fire", "火焰抗性", "percent"),
            ("resistances.cold", "冰霜抗性", "percent"),
            ("resistances.lightning", "闪电抗性", "percent"),
            ("resistances.poison", "毒素抗性", "percent"),
            ("resistances.shadow", "暗影抗性", "percent"),
        ),
    ),
)


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _public_snapshot_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _public_snapshot_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_public_snapshot_value(child) for child in value]
    if isinstance(value, str):
        if value.startswith("/"):
            value = Path(value).name
        elif re.match(r"^[A-Za-z]:[\\/]", value):
            value = PureWindowsPath(value).name
        return re.sub(r"wxid_[A-Za-z0-9_]+", "[已隐藏]", value)
    return value


def _format_number(value: Any, kind: str = "number") -> str:
    if value is None:
        return '<span class="missing">待补充</span>'
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return _escape(value)
    if kind == "percent":
        return f"{value * 100:,.2f}%"
    return f"{value:,.2f}"


def _display_or_missing(value: Any) -> Any:
    return "待补充" if value is None or value == "" else value


def _nested_value(payload: dict[str, Any], path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _summary_lines(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        lines: list[str] = []
        for entry in value:
            lines.extend(_summary_lines(entry))
        return lines
    if isinstance(value, dict):
        if "rank" in value:
            maximum = f'/{value["max_rank"]}' if value.get("max_rank") is not None else ""
            return [f'等级 {value["rank"]}{maximum}']
        label = value.get("display_name") or value.get("name") or value.get("stat")
        amount = value.get("value")
        if label is not None:
            suffix = "%" if value.get("unit") == "percent" else ""
            return [f"{label} {amount}{suffix}" if amount is not None else str(label)]
        return [f"{key}: {entry}" for key, entry in value.items()]
    return [str(value)]


def _load_template(template_path: str | Path | None) -> str:
    if template_path is None:
        template_path = (
            Path(__file__).resolve().parents[2]
            / "skills"
            / "d4-druid-advisor"
            / "assets"
            / "snapshot-template.html"
        )
    return Path(template_path).read_text(encoding="utf-8")


def _equipment_html(equipment: dict[str, Any]) -> str:
    cards = []
    for slot, label in SLOTS:
        item = equipment.get(slot)
        if item is None:
            cards.append(
                f'<article class="item"><h3>{_escape(label)}</h3>'
                '<div class="missing">待补充</div></article>'
            )
            continue
        affixes = []
        for affix in item.get("implicit_affixes", []) + item.get("affixes", []):
            ga_class = " ga" if affix.get("is_greater_affix") else ""
            prefix = "★ " if affix.get("is_greater_affix") else ""
            display = affix.get("display_name") or affix.get("raw_text") or "未知词条"
            value = affix.get("value")
            unit = "%" if affix.get("unit") == "percent" else ""
            affixes.append(
                f'<div class="affix{ga_class}">{prefix}{_escape(display)} '
                f'{_escape(value) if value is not None else "待补充"}{unit}</div>'
            )
        power = item.get("power")
        if isinstance(power, dict) and power.get("description"):
            affixes.append(f'<div class="affix"><span class="tag">能力</span> {_escape(power["description"])}</div>')
        for heading, key in (
            ("回火", "tempering"),
            ("精铸", "masterworking"),
            ("附魔", "enchantment"),
        ):
            for summary in _summary_lines(item.get(key)):
                affixes.append(
                    f'<div class="affix"><span class="tag">{heading}</span> {_escape(summary)}</div>'
                )
        cards.append(
            f'<article class="item"><h3>{_escape(label)} · {_escape(_display_or_missing(item.get("name")))}</h3>'
            f'<div class="muted">物品强度 {_escape(_display_or_missing(item.get("item_power")))}</div>'
            + "".join(affixes)
            + "</article>"
        )
    return "".join(cards)


def _metric_cards(stats: dict[str, Any], definitions: tuple[tuple[str, str, str], ...]) -> str:
    return "".join(
        '<div class="metric">'
        f'<div class="label">{_escape(label)}</div>'
        f'<div class="value">{_format_number(_nested_value(stats, key), kind)}</div>'
        "</div>"
        for key, label, kind in definitions
    )


def _analysis_html(analysis: dict[str, Any]) -> str:
    damage = analysis.get("damage", {})
    defense = analysis.get("defense", {})
    definitions = (
        (damage.get("expected_single_hit"), "最大单击期望"),
        (damage.get("theoretical_single_hit"), "理论单击上限"),
        (damage.get("sustained_dps"), "持续 DPS"),
        (defense.get("physical_ehp"), "物理 EHP"),
        (defense.get("elemental_ehp"), "元素 EHP"),
    )
    return "".join(
        '<div class="metric">'
        f'<div class="label">{_escape(label)}</div>'
        f'<div class="value">{_format_number(value)}</div>'
        "</div>"
        for value, label in definitions
    )


def _issues_html(analysis: dict[str, Any]) -> str:
    issues = analysis.get("shortfalls") or analysis.get("top_issues") or []
    if not issues:
        return '<div class="missing">待完成面板分析</div>'
    return "".join(
        '<div class="issue">'
        f'<strong>{_escape(issue.get("name", issue.get("metric", "未命名短板")))}</strong>'
        f'<span class="severity">{_escape(issue.get("severity", issue.get("status", "待评估")))}</span>'
        f'<span>{_escape(issue.get("recommendation", "待生成建议"))}</span>'
        "</div>"
        for issue in issues[:3]
    )


def _recommendations_html(analysis: dict[str, Any]) -> str:
    recommendations = analysis.get("recommendations", {})
    sections = (
        ("伤害优先", recommendations.get("damage_priority")),
        ("高层生存优先", recommendations.get("survival_priority")),
        ("推荐回火", recommendations.get("tempering")),
        ("推荐精铸", recommendations.get("masterworking")),
        ("推荐附魔", recommendations.get("enchanting")),
    )
    rendered = []
    for heading, value in sections:
        lines = _summary_lines(value)
        if not lines:
            continue
        rendered.append(
            '<div class="issue recommendation">'
            f'<strong>{_escape(heading)}</strong>'
            f'<span>{_escape("；".join(lines))}</span>'
            "</div>"
        )
    return "".join(rendered) or '<div class="missing">待完成人物面板分析</div>'


def _roll_value_text(value: Any) -> str:
    if not isinstance(value, dict) or isinstance(value.get("value"), bool):
        return "待补充"
    amount = value.get("value")
    if not isinstance(amount, (int, float)):
        return "待补充"
    unit = "%" if value.get("unit") == "percent" else f' {value.get("unit", "")}'
    return f"{amount:g}{unit}"


def _delta_percent_text(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "待计算"
    return f"{value:+.2f}%"


def _enchantment_option_evidence_html(
    option: dict[str, Any], baseline_breakpoints: dict[str, Any]
) -> str:
    exchange = option.get("affix_exchange", {})
    lost = exchange.get("lost", {}) if isinstance(exchange, dict) else {}
    evidence = []
    if isinstance(lost, dict):
        evidence.append(
            f'旧词条 {lost.get("stat", "待补充")} {_roll_value_text(lost)}'
        )

    outcome_labels = {
        "expected_single_hit": "最大单击期望",
        "sustained_dps": "持续 DPS",
        "physical_ehp": "物理 EHP",
        "elemental_ehp": "元素 EHP",
    }
    outcomes = option.get("outcomes", {})
    if isinstance(outcomes, dict):
        for metric, outcome in outcomes.items():
            if not isinstance(outcome, dict):
                continue
            deltas = " / ".join(
                _delta_percent_text(outcome.get(f"{bound}_delta_percent"))
                for bound in ("minimum", "expected", "maximum")
            )
            evidence.append(f'{outcome_labels.get(metric, metric)}：{deltas}')

    breakpoint_labels = {
        "attack_speed": "攻速档位",
        "cooldown": "冷却档位",
        "resource": "资源档位",
    }
    breakpoints = option.get("breakpoints", {})
    if isinstance(breakpoints, dict):
        names = {
            name
            for bound in ("minimum", "expected", "maximum")
            for name in (
                breakpoints.get(bound, {}).keys()
                if isinstance(breakpoints.get(bound), dict)
                else []
            )
        }
        for name in sorted(names):
            baseline_tier = baseline_breakpoints.get(name, {}).get("tier")
            tiers = []
            for bound in ("minimum", "expected", "maximum"):
                state = breakpoints.get(bound, {}).get(name, {})
                tier = state.get("tier") if isinstance(state, dict) else None
                tiers.append("待补充" if tier is None else str(tier))
            current_tier = "待补充" if baseline_tier is None else str(baseline_tier)
            evidence.append(
                f'{breakpoint_labels.get(name, name)}：当前 {current_tier} → '
                f'最低 {tiers[0]} / 规划 {tiers[1]} / 最高 {tiers[2]}'
            )

    return "".join(f'<span>{_escape(line)}</span>' for line in evidence)


def _enchantment_analysis_html(
    analysis: dict[str, Any], current_ruleset: str | None, current_profile_fingerprint: str
) -> str:
    enchantment = analysis.get("enchantment")
    if not isinstance(enchantment, dict):
        return '<div class="missing">待生成附魔建议</div>'
    rankings = enchantment.get("rankings")
    options = enchantment.get("options")
    if not isinstance(rankings, dict):
        return '<div class="missing">附魔分析缺少排名数据</div>'
    analysis_ruleset = enchantment.get("ruleset", "待补充")
    scenario = enchantment.get("scenario", "待补充")
    common_confidence = enchantment.get("confidence")
    confidence_text = (
        f"{common_confidence * 100:.0f}%"
        if isinstance(common_confidence, (int, float)) and not isinstance(common_confidence, bool)
        else "待评估"
    )
    metadata = (
        '<div class="issue recommendation">'
        f'<strong>分析规则 {_escape(analysis_ruleset)}</strong>'
        f'<span>场景 {_escape(scenario)} · 共同置信度 {confidence_text}</span>'
        "</div>"
    )
    if current_ruleset and analysis_ruleset != current_ruleset:
        metadata += (
            '<div class="issue"><strong>需重新计算</strong>'
            '<span class="severity">已过期</span>'
            '<span>分析规则与当前快照不一致</span></div>'
        )
    if enchantment.get("profile_fingerprint") != current_profile_fingerprint:
        metadata += (
            '<div class="issue"><strong>需重新计算</strong>'
            '<span class="severity">人物已变更</span>'
            '<span>装备或面板与分析基线不一致</span></div>'
        )
    options_by_id = {
        option.get("id"): option
        for option in options or []
        if isinstance(option, dict) and isinstance(option.get("id"), str)
    }
    baseline_breakpoints = enchantment.get("baseline_breakpoints", {})
    if not isinstance(baseline_breakpoints, dict):
        baseline_breakpoints = {}
    objective_labels = {
        "damage_priority": "伤害优先",
        "survival_priority": "高层生存优先",
    }
    sections = []
    for objective, entries in rankings.items():
        if not isinstance(entries, list) or not entries:
            continue
        rows = []
        for rank, entry in enumerate(entries[:3], start=1):
            if not isinstance(entry, dict):
                continue
            option = options_by_id.get(entry.get("id"), {})
            exchange = option.get("affix_exchange", {}) if isinstance(option, dict) else {}
            gained = exchange.get("gained", {}) if isinstance(exchange, dict) else {}
            roll_text = ""
            if isinstance(gained, dict) and all(
                isinstance(gained.get(bound), (int, float))
                and not isinstance(gained.get(bound), bool)
                for bound in ("minimum", "expected", "maximum")
            ):
                unit = "%" if gained.get("unit") == "percent" else f' {gained.get("unit", "")}'
                roll_text = (
                    f' · 目标范围 {gained["minimum"]:g}–'
                    f'{gained["maximum"]:g}{unit}'
                    f'（规划点 {gained["expected"]:g}{unit}）'
                )
            score = entry.get("score_expected")
            score_text = (
                f"{score:+.2f}%"
                if isinstance(score, (int, float)) and not isinstance(score, bool)
                else "待计算"
            )
            confidence = entry.get("confidence")
            candidate_confidence = (
                f"{confidence * 100:.0f}%"
                if isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
                else "待评估"
            )
            tradeoffs = entry.get("tradeoffs")
            tradeoff_text = (
                f' · 代价 {", ".join(str(value) for value in tradeoffs)}'
                if isinstance(tradeoffs, list) and tradeoffs
                else ""
            )
            rows.append(
                '<div class="issue recommendation">'
                f'<strong>#{rank} {_escape(entry.get("id", "未命名方案"))}</strong>'
                f'<span>{_escape(entry.get("replace_stat", "待补充"))} → '
                f'{_escape(entry.get("target_stat", "待补充"))}{_escape(roll_text)}</span>'
                f'<span>综合收益 {score_text} · 置信度 {candidate_confidence}'
                f'{_escape(tradeoff_text)}</span>'
                + _enchantment_option_evidence_html(
                    option if isinstance(option, dict) else {}, baseline_breakpoints
                )
                + "</div>"
            )
        if rows:
            sections.append(
                f'<h3>{_escape(objective_labels.get(objective, objective))}</h3>' + "".join(rows)
            )
    return metadata + (
        "".join(sections) or '<div class="missing">附魔分析暂无可用候选</div>'
    )


def render_character_snapshot(
    profile: dict[str, Any],
    output_path: str | Path,
    version_lock: dict[str, Any] | None = None,
    fixed_build: dict[str, Any] | None = None,
    template_path: str | Path | None = None,
) -> Path:
    """Generate a self-contained, read-only character snapshot page."""
    current_profile_fingerprint = character_fingerprint(profile)
    profile = _public_snapshot_value(profile)
    version_lock = version_lock or {}
    fixed_build = fixed_build or {}
    stats = profile.get("stats", {})
    equipment = profile.get("equipment", {})
    analysis = profile.get("analysis", {})
    season = version_lock.get("season", {})
    ruleset = version_lock.get("ruleset", {})
    build = fixed_build.get("build", profile.get("build_ref", {}))
    current_ruleset = None
    if ruleset.get("version") is not None and ruleset.get("build") is not None:
        current_ruleset = f'{ruleset["version"]}.{ruleset["build"]}'

    required_stats = [key for _, definitions in STAT_GROUPS for key, _, _ in definitions]
    complete_fields = sum(_nested_value(stats, key) is not None for key in required_stats) + sum(
        equipment.get(slot) is not None for slot, _ in SLOTS
    )
    total_fields = len(required_stats) + len(SLOTS)
    completeness = complete_fields / total_fields * 100 if total_fields else 0

    stat_sections = "".join(
        '<section class="panel">'
        f'<h2>{_escape(title)}</h2><div class="metrics">{_metric_cards(stats, definitions)}</div>'
        "</section>"
        for title, definitions in STAT_GROUPS
    )
    content = (
        '<header class="hero">'
        '<div class="eyebrow">DIABLO IV · DRUID ADVISOR</div>'
        f'<h1>{_escape(profile.get("profile_id", "德鲁伊人物快照"))}</h1>'
        '<div class="chips">'
        f'<span class="chip">S{_escape(season.get("number", "待补充"))} {_escape(season.get("name", ""))}</span>'
        f'<span class="chip">规则 {_escape(ruleset.get("version", "待补充"))} · Build {_escape(ruleset.get("build", "待补充"))}</span>'
        f'<span class="chip">BD {_escape(build.get("id", build.get("build_id", "待补充")))} / var={_escape(build.get("variant", "待补充"))}</span>'
        f'<span class="chip">同步 {_escape(profile.get("updated_at", "待补充"))}</span>'
        "</div>"
        f'<div class="muted">数据完整度 {completeness:.1f}%</div>'
        f'<div class="progress"><span style="width:{completeness:.1f}%"></span></div>'
        "</header>"
        '<div class="grid">'
        + stat_sections
        + '<section class="panel wide"><h2>装备</h2><div class="items">'
        + _equipment_html(equipment)
        + "</div></section>"
        + '<section class="panel wide"><h2>计算摘要</h2><div class="metrics">'
        + _analysis_html(analysis)
        + "</div></section>"
        + '<section class="panel wide"><h2>当前前三项短板</h2><div class="issues">'
        + _issues_html(analysis)
        + "</div></section>"
        + '<section class="panel wide"><h2>回火、精铸与附魔建议</h2><div class="issues">'
        + _recommendations_html(analysis)
        + "</div></section>"
        + '<section class="panel wide"><h2>最近附魔分析</h2><div class="issues">'
        + _enchantment_analysis_html(
            analysis, current_ruleset, current_profile_fingerprint
        )
        + "</div></section>"
        + '<section class="panel wide"><details><summary>查看内嵌角色JSON</summary>'
        + f'<pre>{_escape(json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True))}</pre>'
        + "</details></section></div>"
    )

    embedded_json = (
        json.dumps(profile, ensure_ascii=False, sort_keys=True, allow_nan=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
    )
    page = (
        _load_template(template_path)
        .replace("{{TITLE}}", _escape("D4 德鲁伊人物快照"))
        .replace("{{CONTENT}}", content)
        .replace("{{DATA_JSON}}", embedded_json)
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(page, encoding="utf-8")
    temporary.replace(output)
    return output
