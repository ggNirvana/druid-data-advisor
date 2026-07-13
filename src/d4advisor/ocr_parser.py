from __future__ import annotations

import re
from dataclasses import dataclass
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

STAT_PATTERNS = (
    AffixDefinition(re.compile(r"^\+?(?P<value>\d+(?:\.\d+)?)点?意力$"), "willpower", "意力", "flat", "add"),
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
    return re.sub(r"\s+", "", text).replace("［", "[").replace("］", "]")


def _parse_affix(line: OCRLine, patterns: tuple[AffixDefinition, ...]) -> dict[str, Any] | None:
    text = _compact(line.text)
    for definition in patterns:
        match = definition.pattern.match(text)
        if match:
            return {
                "stat": definition.stat,
                "display_name": definition.display_name,
                "value": float(match.group("value")),
                "unit": definition.unit,
                "operator": definition.operator,
                "is_greater_affix": line.has_greater_affix_marker,
                "confidence": round(line.confidence, 4),
                "raw_text": line.text,
            }
    return None


def parse_item_lines(lines: list[OCRLine], source_image: str | Path | None = None) -> dict[str, Any]:
    active_lines = [line for line in lines if line.in_item_panel and line.text.strip()]
    item: dict[str, Any] = {
        "schema_version": 1,
        "name": None,
        "slot": None,
        "rarity": None,
        "ancestral": False,
        "item_power": None,
        "greater_affix_count": 0,
        "implicit_affixes": [],
        "affixes": [],
        "power": None,
        "required_level": None,
        "expansion": None,
        "minimum_confidence": round(min((line.confidence for line in active_lines), default=0.0), 4),
        "source": {"image": str(source_image) if source_image else None},
        "unparsed_lines": [],
        "ocr_lines": [
            {"text": line.text, "confidence": round(line.confidence, 4)} for line in active_lines
        ],
    }

    for line in active_lines:
        text = _compact(line.text)

        if "物品强度" in text:
            match = re.search(r"(\d+)物品强度", text)
            if match:
                item["item_power"] = int(match.group(1))
                continue

        if any(rarity_name in text for rarity_name in RARITIES):
            item["ancestral"] = "先祖" in text
            item["rarity"] = next(value for key, value in RARITIES.items() if key in text)
            item["slot"] = next((value for key, value in SLOT_NAMES.items() if key in text), item["slot"])
            continue

        implicit = _parse_affix(line, IMPLICIT_PATTERNS)
        if implicit:
            implicit["is_greater_affix"] = False
            item["implicit_affixes"].append(implicit)
            continue

        affix = _parse_affix(line, STAT_PATTERNS)
        if affix:
            item["affixes"].append(affix)
            continue

        required_level = re.match(r"^需要等级[:：](\d+)$", text)
        if required_level:
            item["required_level"] = int(required_level.group(1))
            continue

        expansion = re.match(r"^[《〈](.+?)[》〉]物品$", text)
        if expansion:
            item["expansion"] = expansion.group(1)
            continue

        power = re.match(r"^你的(.+?)(\d+(?:\.\d+)?)(?:\[(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\])?。?$", text)
        if power:
            values = [float(power.group(2))]
            values.extend(float(value) for value in power.groups()[2:] if value is not None)
            item["power"] = {
                "description": line.text,
                "values": values,
                "confidence": round(line.confidence, 4),
            }
            continue

        if item["name"] is None and not re.search(r"\d", text):
            item["name"] = line.text.strip()
            item["slot"] = next((value for key, value in SLOT_NAMES.items() if key in text), item["slot"])
            continue

        item["unparsed_lines"].append(line.text)

    item["greater_affix_count"] = sum(affix["is_greater_affix"] for affix in item["affixes"])
    required_fields = ("name", "slot", "rarity", "item_power")
    missing_fields = [field for field in required_fields if item[field] is None]
    review_reasons = []
    if missing_fields:
        review_reasons.append(f"缺少字段: {', '.join(missing_fields)}")
    if item["minimum_confidence"] < 0.90:
        review_reasons.append("最低OCR置信度低于90%")
    if item["unparsed_lines"]:
        review_reasons.append("存在未解析文本")
    item["review"] = {
        "required": bool(review_reasons),
        "reasons": review_reasons,
        "greater_affix_detection": "image_marker",
    }
    return item
