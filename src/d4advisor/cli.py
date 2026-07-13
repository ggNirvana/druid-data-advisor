from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .calculations import effective_health, expected_chained_attacks, stack_damage_reductions
from .ocr_engine import recognize_item_image
from .ocr_parser import parse_item_lines
from .profile_store import CharacterStore
from .versioning import version_lock_status


DEFAULT_PROFILE_ROOT = Path("data/user")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="d4advisor", description="暗黑破坏神 IV 德鲁伊本地顾问工具")
    subcommands = parser.add_subparsers(dest="command", required=True)

    ocr = subcommands.add_parser("ocr", help="将装备截图识别成结构化 JSON")
    ocr.add_argument("image")
    ocr.add_argument("--output", "-o", required=True)

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

    calc = subcommands.add_parser("calc", help="运行可复用的基础计算")
    calc_commands = calc.add_subparsers(dest="calc_command", required=True)
    chain = calc_commands.add_parser("chain-attacks")
    chain.add_argument("--probability", type=float, required=True)
    chain.add_argument("--max-extra", type=int, required=True)
    ehp = calc_commands.add_parser("ehp")
    ehp.add_argument("--life", type=float, required=True)
    ehp.add_argument("--barrier", type=float, default=0)
    ehp.add_argument("--reductions", type=float, nargs="*", default=[])

    version = subcommands.add_parser("version", help="检查本地规则缓存是否仍有效")
    version_commands = version.add_subparsers(dest="version_command", required=True)
    status = version_commands.add_parser("status")
    status.add_argument("--lock", default="data/reference/version-lock.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "ocr":
        lines, metadata = recognize_item_image(args.image)
        item = parse_item_lines(lines, source_image=Path(args.image).name)
        item["source"]["ocr"] = metadata
        _write_json(Path(args.output), item)
        print(json.dumps(item, ensure_ascii=False, indent=2, sort_keys=True))
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
        else:
            result = store.set_item(
                args.slot,
                _read_json(args.item_json),
                source=Path(args.source_image).name if args.source_image else None,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.command == "version":
        print(json.dumps(version_lock_status(args.lock), ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.calc_command == "chain-attacks":
        result = expected_chained_attacks(args.probability, args.max_extra)
        print(json.dumps({"expected_total_attacks": result}, ensure_ascii=False))
        return 0

    reduction = stack_damage_reductions(args.reductions)
    result = {
        "stacked_damage_reduction": reduction,
        "effective_health": effective_health(args.life + args.barrier, reduction),
    }
    print(json.dumps(result, ensure_ascii=False))
    return 0
