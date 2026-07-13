from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OCRLine:
    text: str
    confidence: float
    box: tuple[tuple[float, float], ...] | None = None
    in_item_panel: bool = True
    has_greater_affix_marker: bool = False


@dataclass(frozen=True)
class AffixDefinition:
    pattern: re.Pattern[str]
    stat: str
    display_name: str
    unit: str
    operator: str


@dataclass(frozen=True)
class RegistryStatDefinition:
    stat: str
    aliases: tuple[str, ...]
    unit: str
    operator: str


SLOT_NAMES = {
    "戒指": "ring",
    "护符": "amulet",
    "项链": "amulet",
    "头盔": "helm",
    "胸甲": "chest",
    "手套": "gloves",
    "裤子": "pants",
    "靴子": "boots",
    "鞋子": "boots",
    "图腾": "totem",
    "斧": "weapon",
    "锤": "weapon",
    "剑": "weapon",
    "杖": "weapon",
}

RARITIES = {
    "传奇": "legendary",
    "暗金": "unique",
    "神话": "mythic",
    "稀有": "rare",
}

NAME_NOISE = {
    "已装备",
    "头部",
    "胸部",
    "手部",
    "腿部",
    "脚部",
    "颈部",
    "戒指",
    "主手",
    "副手",
}

NAME_SUFFIX_COMPLETIONS = {
    ("chest", "胸"): "甲",
    ("boots", "护"): "胫",
}

IGNORED_EXACT_LINES = {
    "已蜕变",
    "已变",
    "已擅变",
    "已蟑变",
    "账号绑定",
    "仅限",
    "装备唯一",
    "无法修改",
    "已制作",
}

MECHANIC_HINTS = (
    "伤害",
    "减免",
    "技能",
    "敌人",
    "攻击",
    "施放",
    "获得",
    "提高",
    "降低",
    "持续",
    "几率",
    "生命",
    "资源",
    "灵力",
    "屏障",
    "治疗",
    "形态",
    "刻印",
    "溢出",
)

STAT_PATTERNS = (
    AffixDefinition(
        re.compile(r"^\+?(?P<value>\d+(?:\.\d+)?)点?意力$"),
        "willpower",
        "意力",
        "flat",
        "add",
    ),
    AffixDefinition(
        re.compile(r"^[xX×](?P<value>\d+(?:\.\d+)?)%易伤伤害(?:增倍|增幅)$"),
        "vulnerable_damage_multiplier",
        "易伤伤害增倍",
        "percent",
        "multiply",
    ),
    AffixDefinition(
        re.compile(r"^[xX×](?P<value>\d+(?:\.\d+)?)%物理伤害(?:增倍|增幅)$"),
        "physical_damage_multiplier",
        "物理伤害增倍",
        "percent",
        "multiply",
    ),
    AffixDefinition(
        re.compile(r"^\+?(?P<value>\d+(?:\.\d+)?)%冷却时间缩减$"),
        "cooldown_reduction",
        "冷却时间缩减",
        "percent",
        "add",
    ),
)

IMPLICIT_PATTERNS = (
    AffixDefinition(
        re.compile(r"^(?P<value>\d+(?:\.\d+)?)所有抗性(?:（.*）|\(.*\))?$"),
        "all_resistance",
        "所有抗性",
        "flat",
        "add",
    ),
)


def _compact(text: str) -> str:
    return (
        re.sub(r"\s+", "", text)
        .replace("［", "[")
        .replace("］", "]")
        .replace("（", "(")
        .replace("）", ")")
        .replace("，", ",")
        .replace(",", "")
    )


def _split_roll_range(text: str) -> tuple[str, dict[str, float | str] | None]:
    compact = _compact(text)
    match = re.search(
        r"\+?\[(?P<minimum>\d+(?:\.\d+)?)-(?P<maximum>\d+(?:\.\d+)?)\](?P<unit>%?)$",
        compact,
    )
    if not match:
        return compact, None
    base = compact[: match.start()].rstrip("+")
    return base, {
        "minimum": float(match.group("minimum")),
        "maximum": float(match.group("maximum")),
        "unit": "percent" if match.group("unit") else "flat",
    }


def _with_roll_range(
    value: dict[str, Any], roll_range: dict[str, float | str] | None
) -> dict[str, Any]:
    if roll_range is not None:
        value["roll_range"] = roll_range
    return value


@lru_cache(maxsize=1)
def _load_registry() -> tuple[RegistryStatDefinition, ...]:
    path = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "reference"
        / "stat-definitions.json"
    )
    if not path.exists():
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        RegistryStatDefinition(
            stat=stat,
            aliases=tuple(_compact(alias) for alias in definition["aliases_zh_cn"]),
            unit=definition["default_unit"],
            operator=definition["default_operator"],
        )
        for stat, definition in payload.get("stats", {}).items()
    )


def _parse_registry_affix(line: OCRLine) -> dict[str, Any] | None:
    text, roll_range = _split_roll_range(line.text)
    match = re.match(
        r"^(?P<prefix>[+xX×]?)(?P<value>\d+(?:\.\d+)?)(?P<percent>%?)(?:点|级)?(?P<label>.+?)$",
        text,
    )
    if not match:
        return None
    label = match.group("label").removeprefix("至")
    for definition in _load_registry():
        if label not in definition.aliases:
            continue
        prefix = match.group("prefix")
        has_percent = bool(match.group("percent"))
        is_multiplier_prefix = prefix in {"x", "X", "×"}
        syntax_is_valid = (
            definition.operator == "multiply" and is_multiplier_prefix and has_percent
        ) or (
            definition.operator != "multiply"
            and not is_multiplier_prefix
            and has_percent == (definition.unit == "percent")
        )
        if not syntax_is_valid:
            return None
        return _with_roll_range(
            {
                "stat": definition.stat,
                "display_name": label,
                "value": float(match.group("value")),
                "unit": "percent" if has_percent else definition.unit,
                "operator": definition.operator,
                "is_greater_affix": line.has_greater_affix_marker,
                "confidence": round(line.confidence, 4),
                "raw_text": line.text,
            },
            roll_range,
        )
    return None


def _parse_affix(
    line: OCRLine, patterns: tuple[AffixDefinition, ...]
) -> dict[str, Any] | None:
    text, roll_range = _split_roll_range(line.text)
    for definition in patterns:
        match = definition.pattern.match(text)
        if match:
            return _with_roll_range(
                {
                    "stat": definition.stat,
                    "display_name": definition.display_name,
                    "value": float(match.group("value")),
                    "unit": definition.unit,
                    "operator": definition.operator,
                    "is_greater_affix": line.has_greater_affix_marker,
                    "confidence": round(line.confidence, 4),
                    "raw_text": line.text,
                },
                roll_range,
            )
    return None


def _parse_implicit(line: OCRLine) -> dict[str, Any] | None:
    text = _compact(line.text)
    patterns = (
        (r"^(?P<value>\d+)护甲值$", "armor", "基础护甲值", "flat"),
        (r"^(?P<value>\d+)每秒伤害$", "weapon_dps", "每秒伤害", "flat"),
        (
            r"^[—\-一]?每次命中伤害\[(?P<value>\d+)-(?P<maximum>\d+)\]$",
            "hit_damage",
            "每次命中伤害",
            "flat",
        ),
        (
            r"^[—\-一]?每秒攻击次数\(快\)[:：]?(?P<value>\d+(?:\.\d+)?)$",
            "attacks_per_second",
            "每秒攻击次数（快）",
            "rating",
        ),
    )
    for pattern, stat, display_name, unit in patterns:
        match = re.match(pattern, text)
        if not match:
            continue
        result: dict[str, Any] = {
            "stat": stat,
            "display_name": display_name,
            "value": float(match.group("value")),
            "unit": unit,
            "operator": "add",
            "is_greater_affix": False,
            "confidence": round(line.confidence, 4),
            "raw_text": line.text,
        }
        if match.groupdict().get("maximum") is not None:
            result["maximum"] = float(match.group("maximum"))
        return result
    implicit = _parse_affix(line, IMPLICIT_PATTERNS)
    if implicit:
        implicit["is_greater_affix"] = False
    return implicit


def _parse_quality(line: OCRLine) -> dict[str, Any] | None:
    text = _compact(line.text)
    match = re.match(r"^(?P<rank>\d+).*?\+(?P<bonus>\d+).*?品质$", text)
    if not match:
        return None
    return {
        "rank": int(match.group("rank")),
        "bonus": int(match.group("bonus")),
        "confidence": round(line.confidence, 4),
        "raw_text": line.text,
    }


def _is_ignored_metadata(text: str) -> bool:
    compact = _compact(text)
    return (
        compact in IGNORED_EXACT_LINES
        or compact.startswith(("出售价格", "耐久度", "需要等级"))
        or compact.endswith("物品")
        or compact.startswith(("“", '"', "《", "——", "一一"))
    )


def _looks_like_mechanic(text: str) -> bool:
    compact = _compact(text)
    return any(hint in compact for hint in MECHANIC_HINTS)


def _looks_like_unparsed_data(text: str) -> bool:
    compact = _compact(text)
    return bool(re.search(r"\d", compact)) or compact.startswith(("+", "x", "X", "×"))


def _extract_name(
    lines: list[OCRLine], rarity_index: int | None, slot: str | None
) -> tuple[str | None, list[int], list[str]]:
    stop = rarity_index if rarity_index is not None else len(lines)
    equipped_indexes = [
        index
        for index, line in enumerate(lines[:stop])
        if _compact(line.text) == "已装备"
    ]
    start = equipped_indexes[-1] + 1 if equipped_indexes else 0
    parts: list[str] = []
    indexes: list[int] = []
    for index in range(start, stop):
        line = lines[index]
        compact = _compact(line.text)
        if (
            not compact
            or compact in NAME_NOISE
            or re.search(r"\d", compact)
            or (len(compact) == 1 and not re.search(r"[\u4e00-\u9fff]", compact))
        ):
            continue
        parts.append(compact)
        indexes.append(index)
    if not parts:
        return None, [], []
    name = re.sub(r"[#·|]+$", "", "".join(parts))
    corrections: list[str] = []
    if slot is not None:
        for (completion_slot, suffix), addition in NAME_SUFFIX_COMPLETIONS.items():
            if slot == completion_slot and name.endswith(suffix):
                name += addition
                corrections.append(f"根据{slot}槽位补全名称尾字：{suffix}{addition}")
                break
    return name, indexes, corrections


def parse_item_lines(
    lines: list[OCRLine], source_image: str | Path | None = None
) -> dict[str, Any]:
    active_lines = [line for line in lines if line.in_item_panel and line.text.strip()]
    rarity_index = next(
        (
            index
            for index, line in enumerate(active_lines)
            if any(rarity_name in _compact(line.text) for rarity_name in RARITIES)
        ),
        None,
    )
    rarity_line = active_lines[rarity_index] if rarity_index is not None else None
    rarity_text = _compact(rarity_line.text) if rarity_line is not None else ""
    rarity = next(
        (value for key, value in RARITIES.items() if key in rarity_text), None
    )
    slot = next(
        (value for key, value in SLOT_NAMES.items() if key in rarity_text), None
    )
    name, name_indexes, name_corrections = _extract_name(
        active_lines, rarity_index, slot
    )
    critical_confidences = [active_lines[index].confidence for index in name_indexes]
    if rarity_line is not None:
        critical_confidences.append(rarity_line.confidence)
    item: dict[str, Any] = {
        "schema_version": 1,
        "name": name,
        "slot": slot,
        "rarity": rarity,
        "ancestral": "先祖" in rarity_text,
        "item_power": None,
        "quality": None,
        "greater_affix_count": 0,
        "implicit_affixes": [],
        "affixes": [],
        "properties": [],
        "tempering": [],
        "masterworking": None,
        "power": None,
        "required_level": None,
        "expansion": None,
        "minimum_confidence": round(
            min((line.confidence for line in active_lines), default=0.0), 4
        ),
        "source": {"image": str(source_image) if source_image else None},
        "unparsed_lines": [],
        "ignored_lines": [],
        "name_corrections": name_corrections,
        "ocr_lines": [
            {
                "text": line.text,
                "confidence": round(line.confidence, 4),
                "has_greater_affix_marker": line.has_greater_affix_marker,
            }
            for line in active_lines
        ],
    }
    unresolved_lines: list[tuple[int, OCRLine]] = []
    parsed_affixes: list[tuple[int, dict[str, Any]]] = []
    used_indexes = set(name_indexes)
    if rarity_index is not None:
        used_indexes.add(rarity_index)
    equipped_indexes = [
        index
        for index, line in enumerate(active_lines)
        if _compact(line.text) == "已装备"
    ]
    equipped_index = equipped_indexes[-1] if equipped_indexes else None

    for index, line in enumerate(active_lines):
        if index in used_indexes:
            continue
        text = _compact(line.text)

        if equipped_index is not None and index <= equipped_index:
            item["ignored_lines"].append(line.text)
            continue

        if text in NAME_NOISE:
            item["ignored_lines"].append(line.text)
            continue

        if "物品强度" in text:
            match = re.search(r"(\d+)物品强度", text)
            if match:
                item["item_power"] = int(match.group(1))
                critical_confidences.append(line.confidence)
                continue

        if any(rarity_name in text for rarity_name in RARITIES):
            item["ignored_lines"].append(line.text)
            continue

        quality = _parse_quality(line)
        if quality:
            item["quality"] = quality
            continue

        implicit = _parse_implicit(line)
        if implicit:
            item["implicit_affixes"].append(implicit)
            continue

        affix = _parse_registry_affix(line) or _parse_affix(line, STAT_PATTERNS)
        if affix:
            item["affixes"].append(affix)
            parsed_affixes.append((index, affix))
            critical_confidences.append(line.confidence)
            continue

        if text == "不可摧毁":
            item["properties"].append("不可摧毁")
            continue

        required_level = re.match(r"^需要等级[:：](\d+)$", text)
        if required_level:
            item["required_level"] = int(required_level.group(1))
            continue

        expansion = re.match(r"^[《〈](.+?)[》〉]物品$", text)
        if expansion:
            item["expansion"] = expansion.group(1)
            continue
        if "憎恨之" in text and text.endswith("物品"):
            item["expansion"] = "憎恨之躯"
            continue

        tempering = re.match(r"^回火[:：]?(.+)$", text)
        if tempering:
            item["tempering"].append(
                {
                    "description": tempering.group(1),
                    "confidence": round(line.confidence, 4),
                    "raw_text": line.text,
                }
            )
            continue

        masterworking = re.match(
            r"^(?:精铸|精工)(?:等级)?[:：]?(\d+)(?:/(\d+))?$", text
        )
        if masterworking:
            item["masterworking"] = {
                "rank": int(masterworking.group(1)),
                "max_rank": (
                    int(masterworking.group(2)) if masterworking.group(2) else None
                ),
                "confidence": round(line.confidence, 4),
                "raw_text": line.text,
            }
            continue

        unresolved_lines.append((index, line))

    mechanic_indexes = {
        index for index, line in unresolved_lines if _looks_like_mechanic(line.text)
    }
    changed = True
    while changed:
        changed = False
        for index, line in unresolved_lines:
            if index in mechanic_indexes or not _looks_like_unparsed_data(line.text):
                continue
            if index - 1 in mechanic_indexes or index + 1 in mechanic_indexes:
                mechanic_indexes.add(index)
                changed = True

    mechanic_lines = [
        line for index, line in unresolved_lines if index in mechanic_indexes
    ]
    first_mechanic_index = min(mechanic_indexes, default=None)
    for index, affix in parsed_affixes:
        if first_mechanic_index is not None and index > first_mechanic_index:
            affix["is_greater_affix"] = False
            affix["greater_affix_evidence"] = "post_power_socket_or_bonus"
        elif affix["is_greater_affix"]:
            affix["greater_affix_evidence"] = "image_marker"
        elif "roll_range" not in affix and affix.get("stat") != "item_quality":
            affix["is_greater_affix"] = True
            affix["greater_affix_evidence"] = "no_roll_range_before_power"
    for index, line in unresolved_lines:
        if index in mechanic_indexes:
            continue
        if _is_ignored_metadata(line.text) or not _looks_like_unparsed_data(line.text):
            item["ignored_lines"].append(line.text)
        else:
            item["unparsed_lines"].append(line.text)

    if mechanic_lines:
        description = "".join(line.text.strip() for line in mechanic_lines)
        values = [
            float(value)
            for value in re.findall(r"\d+(?:\.\d+)?", _compact(description))
        ]
        item["power"] = {
            "description": description,
            "values": values,
            "confidence": round(min(line.confidence for line in mechanic_lines), 4),
        }

    item["greater_affix_count"] = sum(
        affix["is_greater_affix"] for affix in item["affixes"]
    )
    required_fields = ("name", "slot", "rarity", "item_power")
    missing_fields = [field for field in required_fields if item[field] is None]
    review_reasons = []
    if missing_fields:
        review_reasons.append(f"缺少字段: {', '.join(missing_fields)}")
    critical_confidence = round(min(critical_confidences, default=0.0), 4)
    item["critical_confidence"] = critical_confidence
    if critical_confidence < 0.75:
        review_reasons.append("关键字段OCR置信度低于75%")
    if not item["affixes"]:
        review_reasons.append("未解析到任何装备词条")
    if item["unparsed_lines"]:
        review_reasons.append("存在未解析的数值文本")
    item["review"] = {
        "required": bool(review_reasons),
        "reasons": review_reasons,
        "greater_affix_detection": "image_marker_and_roll_range_heuristic",
    }
    return item
