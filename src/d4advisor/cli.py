from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .advisor_engine import (
    analyze_enchantment_options,
    audit_panel,
    calculate_damage_event,
    compare_loadouts,
)
from .calculations import (
    effective_health,
    expected_chained_attacks,
    stack_damage_reductions,
)
from .ocr_engine import create_ocr_engine, recognize_item_image
from .ocr_parser import parse_item_lines
from .profile_store import CharacterStore
from .snapshot_compare import EVENT_PRESETS, compare_snapshot_item
from .versioning import version_lock_status

DEFAULT_PROFILE_ROOT = Path("data/user")
DEFAULT_VERSION_LOCK = Path("data/reference/version-lock.json")
COMPLETE_EQUIPMENT_SLOTS = {
    "helm",
    "chest",
    "gloves",
    "pants",
    "boots",
    "amulet",
    "ring_1",
    "ring_2",
    "weapon",
    "totem",
}


def _encode_json(value: Any) -> str:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )


def _write_json_text(path: Path, encoded: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded, encoding="utf-8")
    os.replace(temporary, path)


def _read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _emit_json(value: Any, output: str | None = None) -> None:
    encoded = _encode_json(value)
    if output:
        _write_json_text(Path(output), encoded)
    print(encoded, end="")


def _locked_ruleset_id() -> str:
    status = version_lock_status(DEFAULT_VERSION_LOCK)
    if status["refresh_required"]:
        raise ValueError(
            "version lock is expired; refresh the ruleset before calculating"
        )
    ruleset = status["ruleset"]
    return f'{ruleset["version"]}.{ruleset["build"]}'


def _require_locked_ruleset(actual: Any, expected: str, context: str) -> None:
    if actual != expected:
        raise ValueError(f"{context} ruleset must match locked ruleset {expected}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="d4advisor", description="暗黑破坏神 IV 德鲁伊本地顾问工具"
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    ocr = subcommands.add_parser("ocr", help="将装备截图识别成结构化 JSON")
    ocr.add_argument("image")
    ocr.add_argument("--output", "-o", required=True)
    ocr_batch = subcommands.add_parser(
        "ocr-batch", help="批量识别装备截图，可在全部通过关键校验后原子写入人物档案"
    )
    ocr_batch.add_argument("images", nargs="+")
    ocr_batch.add_argument("--output-dir", default="data/user/candidates")
    ocr_batch.add_argument("--manifest")
    ocr_batch.add_argument("--equip", action="store_true")
    ocr_batch.add_argument("--require-complete", action="store_true")
    ocr_batch.add_argument("--allow-review", action="store_true")
    ocr_batch.add_argument("--root", default=str(DEFAULT_PROFILE_ROOT))
    ocr_text = subcommands.add_parser("ocr-text", help="识别附魔候选等界面原始文本")
    ocr_text.add_argument("image")
    ocr_text.add_argument("--output", "-o", required=True)
    ocr_text_batch = subcommands.add_parser(
        "ocr-text-batch", help="复用同一个 OCR 引擎批量识别界面原始文本"
    )
    ocr_text_batch.add_argument("images", nargs="+")
    ocr_text_batch.add_argument("--output-dir", required=True)
    ocr_text_batch.add_argument("--manifest")

    profile = subcommands.add_parser("profile", help="维护用户角色快照")
    profile_commands = profile.add_subparsers(dest="profile_command", required=True)
    init = profile_commands.add_parser("init")
    init.add_argument("--root", default=str(DEFAULT_PROFILE_ROOT))
    init.add_argument("--profile-id", default="nirvana-druid-s14")
    show = profile_commands.add_parser("show")
    show.add_argument("--root", default=str(DEFAULT_PROFILE_ROOT))
    merge = profile_commands.add_parser("merge")
    merge.add_argument("json_file")
    merge.add_argument("--root", default=str(DEFAULT_PROFILE_ROOT))
    set_item = profile_commands.add_parser("set-item")
    set_item.add_argument("--slot", required=True)
    set_item.add_argument("--item-json", required=True)
    set_item.add_argument("--source-image")
    set_item.add_argument("--root", default=str(DEFAULT_PROFILE_ROOT))
    render = profile_commands.add_parser("render")
    render.add_argument("--output")
    render.add_argument("--root", default=str(DEFAULT_PROFILE_ROOT))
    fingerprint = profile_commands.add_parser(
        "fingerprint", help="输出当前装备与面板计算指纹"
    )
    fingerprint.add_argument("--root", default=str(DEFAULT_PROFILE_ROOT))
    save_enchantment = profile_commands.add_parser(
        "save-enchantment-analysis",
        help="保存附魔建议分析，不修改当前穿戴装备",
    )
    save_enchantment.add_argument("--input", required=True)
    save_enchantment.add_argument("--root", default=str(DEFAULT_PROFILE_ROOT))

    calc = subcommands.add_parser("calc", help="运行可复用的基础计算")
    calc_commands = calc.add_subparsers(dest="calc_command", required=True)
    chain = calc_commands.add_parser("chain-attacks")
    chain.add_argument("--probability", type=float, required=True)
    chain.add_argument("--max-extra", type=int, required=True)
    ehp = calc_commands.add_parser("ehp")
    ehp.add_argument("--life", type=float, required=True)
    ehp.add_argument("--barrier", type=float, default=0)
    ehp.add_argument("--reductions", type=float, nargs="*", default=[])
    damage_event = calc_commands.add_parser("damage-event")
    damage_event.add_argument("--input", required=True)
    damage_event.add_argument("--output")
    compare = calc_commands.add_parser("compare")
    compare.add_argument("--input", required=True)
    compare.add_argument("--output")
    compare_item = calc_commands.add_parser(
        "compare-item",
        help="从当前快照原子模拟整件装备替换并重算同一伤害事件",
    )
    compare_item.add_argument("--slot", required=True)
    compare_item.add_argument("--candidate", required=True)
    compare_item.add_argument("--event", choices=sorted(EVENT_PRESETS), default="shred")
    compare_item.add_argument("--root", default=str(DEFAULT_PROFILE_ROOT))
    compare_item.add_argument("--output")
    audit = calc_commands.add_parser("audit-panel")
    audit.add_argument("--input", required=True)
    audit.add_argument("--output")
    enchant = calc_commands.add_parser("enchant")
    enchant.add_argument("--input", required=True)
    enchant.add_argument("--output")

    version = subcommands.add_parser("version", help="检查本地规则缓存是否仍有效")
    version_commands = version.add_subparsers(dest="version_command", required=True)
    status = version_commands.add_parser("status")
    status.add_argument("--lock", default=str(DEFAULT_VERSION_LOCK))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "ocr":
        lines, metadata = recognize_item_image(args.image)
        item = parse_item_lines(lines, source_image=Path(args.image).name)
        item["source"]["ocr"] = metadata
        _emit_json(item, args.output)
        return 0

    if args.command == "ocr-batch":
        engine = create_ocr_engine()
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        ring_number = 0
        items: dict[str, dict[str, Any]] = {}
        sources: dict[str, str] = {}
        entries: list[dict[str, Any]] = []
        batch_errors: list[str] = []

        for index, image_name in enumerate(args.images, start=1):
            image_path = Path(image_name)
            lines, metadata = recognize_item_image(image_path, engine=engine)
            item = parse_item_lines(lines, source_image=image_path.name)
            item["source"]["ocr"] = metadata

            parsed_slot = item.get("slot")
            equipment_slot: str | None
            if parsed_slot == "ring":
                ring_number += 1
                equipment_slot = f"ring_{ring_number}" if ring_number <= 2 else None
            elif parsed_slot in COMPLETE_EQUIPMENT_SLOTS:
                equipment_slot = parsed_slot
            else:
                equipment_slot = None

            if equipment_slot is None:
                output_stem = f"unresolved-{index:02d}"
                batch_errors.append(f"{image_path.name}: 无法映射装备槽位")
            else:
                output_stem = equipment_slot
                if equipment_slot in items:
                    batch_errors.append(
                        f"{image_path.name}: 重复装备槽位 {equipment_slot}"
                    )
                else:
                    items[equipment_slot] = item
                    sources[equipment_slot] = image_path.name

            output_path = output_dir / f"{output_stem}.json"
            _write_json_text(output_path, _encode_json(item))
            entries.append(
                {
                    "source_image": image_path.name,
                    "equipment_slot": equipment_slot,
                    "item_json": output_path.name,
                    "name": item.get("name"),
                    "review": item.get("review", {}),
                    "unparsed_lines": item.get("unparsed_lines", []),
                }
            )

        detected_slots = set(items)
        missing_slots = sorted(COMPLETE_EQUIPMENT_SLOTS.difference(detected_slots))
        extra_slots = sorted(detected_slots.difference(COMPLETE_EQUIPMENT_SLOTS))
        if args.require_complete and (missing_slots or extra_slots):
            batch_errors.append(
                "完整装备校验失败："
                f"缺少 {', '.join(missing_slots) if missing_slots else '无'}；"
                f"多余 {', '.join(extra_slots) if extra_slots else '无'}"
            )

        review_entries = [
            entry for entry in entries if entry.get("review", {}).get("required")
        ]
        equipped = False
        snapshot: str | None = None
        if args.equip:
            if batch_errors:
                raise ValueError("；".join(batch_errors))
            if review_entries and not args.allow_review:
                blocking = ", ".join(
                    f'{entry["source_image"]}: {entry["review"].get("reasons", [])}'
                    for entry in review_entries
                )
                raise ValueError(
                    f"批量结果包含需要复核的关键字段，未写入人物档案：{blocking}"
                )
            store = CharacterStore(args.root)
            store.set_items(items, sources)
            equipped = True
            snapshot = "snapshot.html"

        manifest = {
            "schema_version": 1,
            "images": len(args.images),
            "detected_slots": sorted(detected_slots),
            "missing_slots": missing_slots,
            "errors": batch_errors,
            "review_required": len(review_entries),
            "equipped": equipped,
            "snapshot": snapshot,
            "items": entries,
        }
        manifest_path = (
            Path(args.manifest) if args.manifest else output_dir / "batch-manifest.json"
        )
        _emit_json(manifest, str(manifest_path))
        return 0

    if args.command == "ocr-text":
        lines, metadata = recognize_item_image(args.image)
        result = {
            "source_image": Path(args.image).name,
            "lines": [
                {
                    "text": line.text,
                    "confidence": line.confidence,
                    "box": line.box,
                    "in_item_panel": line.in_item_panel,
                }
                for line in lines
            ],
            "ocr": metadata,
        }
        _emit_json(result, args.output)
        return 0

    if args.command == "ocr-text-batch":
        engine = create_ocr_engine()
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        entries: list[dict[str, Any]] = []

        for index, image_name in enumerate(args.images, start=1):
            image_path = Path(image_name)
            lines, metadata = recognize_item_image(image_path, engine=engine)
            result = {
                "source_image": image_path.name,
                "lines": [
                    {
                        "text": line.text,
                        "confidence": line.confidence,
                        "box": line.box,
                        "in_item_panel": line.in_item_panel,
                    }
                    for line in lines
                ],
                "ocr": metadata,
            }
            output_path = output_dir / f"panel-{index:02d}.json"
            _write_json_text(output_path, _encode_json(result))
            entries.append(
                {
                    "source_image": image_path.name,
                    "ocr_json": output_path.name,
                    "line_count": len(lines),
                }
            )

        manifest = {
            "schema_version": 1,
            "images": len(entries),
            "items": entries,
        }
        manifest_path = (
            Path(args.manifest) if args.manifest else output_dir / "batch-manifest.json"
        )
        _emit_json(manifest, str(manifest_path))
        return 0

    if args.command == "profile":
        store = CharacterStore(args.root)
        if args.profile_command == "init":
            result = store.initialize(
                profile_id=args.profile_id,
                build_ref={
                    "provider": "d2core",
                    "build_id": "1ZsP",
                    "variant": 9,
                    "snapshot": "2026-07-13",
                },
            )
        elif args.profile_command == "show":
            result = store.load()
        elif args.profile_command == "merge":
            result = store.merge_character_fields(_read_json(args.json_file))
        elif args.profile_command == "render":
            output = store.render_snapshot(args.output)
            result = {"snapshot": str(output.resolve())}
        elif args.profile_command == "fingerprint":
            result = {"profile_fingerprint": store.current_fingerprint()}
        elif args.profile_command == "save-enchantment-analysis":
            analysis = _read_json(args.input)
            _require_locked_ruleset(
                analysis.get("ruleset"), _locked_ruleset_id(), "enchantment analysis"
            )
            result = store.set_enchantment_analysis(analysis)
        else:
            result = store.set_item(
                args.slot,
                _read_json(args.item_json),
                source=Path(args.source_image).name if args.source_image else None,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.command == "version":
        print(
            json.dumps(
                version_lock_status(args.lock),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.calc_command == "chain-attacks":
        result = expected_chained_attacks(args.probability, args.max_extra)
        print(json.dumps({"expected_total_attacks": result}, ensure_ascii=False))
        return 0

    if args.calc_command == "damage-event":
        payload = _read_json(args.input)
        _require_locked_ruleset(
            payload.get("ruleset"), _locked_ruleset_id(), "damage event"
        )
        result = calculate_damage_event(payload)
        _emit_json(result, args.output)
        return 0

    if args.calc_command == "compare":
        payload = _read_json(args.input)
        expected_ruleset = _locked_ruleset_id()
        for scenario_name, pair in payload.get("scenarios", {}).items():
            for side in ("a", "b"):
                _require_locked_ruleset(
                    pair.get(side, {}).get("ruleset"),
                    expected_ruleset,
                    f"scenario {scenario_name} side {side}",
                )
        result = compare_loadouts(payload)
        _emit_json(result, args.output)
        return 0

    if args.calc_command == "compare-item":
        store = CharacterStore(args.root)
        result = compare_snapshot_item(
            store.load(),
            slot=args.slot,
            candidate=_read_json(args.candidate),
            event_id=args.event,
            ruleset=_locked_ruleset_id(),
        )
        _emit_json(result, args.output)
        return 0

    if args.calc_command == "enchant":
        payload = _read_json(args.input)
        _require_locked_ruleset(
            payload.get("ruleset"), _locked_ruleset_id(), "enchantment analysis"
        )
        result = analyze_enchantment_options(payload)
        _emit_json(result, args.output)
        return 0

    if args.calc_command == "audit-panel":
        payload = _read_json(args.input)
        rules = dict(payload.get("rules", {}))
        for field in ("ruleset", "scenario", "confidence"):
            if field in payload:
                rules[field] = payload[field]
        _require_locked_ruleset(
            rules.get("ruleset"), _locked_ruleset_id(), "panel audit"
        )
        result = audit_panel(payload.get("stats", {}), rules)
        _emit_json(result, args.output)
        return 0

    reduction = stack_damage_reductions(args.reductions)
    result = {
        "stacked_damage_reduction": reduction,
        "effective_health": effective_health(args.life + args.barrier, reduction),
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0
