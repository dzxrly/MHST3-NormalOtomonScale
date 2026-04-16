#!/usr/bin/env python3
"""
tmp_patch_ot125.py
临时脚本：仅处理 Ot0125 的 BasicParam / CameraParam。

用途：
- 快速验证 Ot0125 的 _BodyScale 与 Camera AttachOfs 改写是否正确
- 复用 normal_otomon_body_scale.py 当前解析与改写逻辑
"""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

from normal_otomon_body_scale import (
    TypeDB,
    patch_body_scale,
    patch_camera_param,
    read_body_scale,
)


def _calc_ot125_scale(
    base_scale: float, json_dir: str, apply_enemy_scale: bool
) -> float:
    if not apply_enemy_scale:
        return base_scale

    em_name = "Em0125"
    base_enemy_dir = Path(json_dir) / "natives" / "STM" / "GameDesign"

    patterns = [
        base_enemy_dir
        / em_name
        / "**"
        / "CommonData"
        / f"{em_name}_BasicParam.user.3.json",
        base_enemy_dir
        / "**"
        / em_name
        / "**"
        / "CommonData"
        / f"{em_name}_BasicParam.user.3.json",
    ]

    for pattern in patterns:
        matches = [Path(p) for p in glob.glob(str(pattern), recursive=True)]
        if not matches:
            continue
        try:
            with matches[0].open("r", encoding="utf-8") as f:
                enemy_data = json.load(f)
            enemy_scale = enemy_data[0]["app.user_data.EnemyBasicParam"][
                "_WorldBodyScale"
            ]
            return round(base_scale + (enemy_scale - 1.0), 4)
        except Exception:
            continue

    return base_scale


def main() -> None:
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    temp_root = project_root / ".temp"
    default_rsz = script_dir / "data" / "rszmhst3.json"
    default_natives = script_dir / "data" / "unpak" / "natives"
    default_output_name = "out_ot125"
    default_il2cpp = script_dir / "data" / "il2cpp_subset.json"
    default_json_dir = script_dir / "data" / "json"

    ap = argparse.ArgumentParser(description="临时脚本：仅处理 Ot0125")
    ap.add_argument(
        "--rsz",
        default=str(default_rsz),
        help=f"rszmhst3.json 路径（默认: {default_rsz}）",
    )
    ap.add_argument(
        "--natives",
        default=str(default_natives),
        help=f"natives 根目录（默认: {default_natives}）",
    )
    ap.add_argument(
        "--output",
        default=default_output_name,
        help=f"输出目录名称（固定写入 .temp 下，默认: {default_output_name}）",
    )
    ap.add_argument("--scale", type=float, default=1.0, help="基础 scale（默认 1.0）")
    ap.add_argument(
        "--il2cpp-map",
        default=str(default_il2cpp) if default_il2cpp.exists() else "",
        help="il2cpp_subset.json 路径（可选）",
    )
    ap.add_argument(
        "--apply-enemy-scale", action="store_true", help="按敌人原始体型修正 scale"
    )
    ap.add_argument(
        "--json-dir",
        default=str(default_json_dir),
        help=f"enemy json 根目录（默认: {default_json_dir}）",
    )
    ap.add_argument("--dry-run", action="store_true", help="仅预览，不写文件")
    args = ap.parse_args()

    schema_path = Path(args.rsz)
    natives_dir = Path(args.natives)
    temp_root.mkdir(parents=True, exist_ok=True)

    requested_output = Path(args.output)
    if requested_output.is_absolute():
        output_dir = temp_root / requested_output.name
    else:
        output_dir = temp_root / requested_output
    ot_dir = natives_dir / "STM" / "GameDesign" / "Otomon" / "Ot0125"

    if not schema_path.is_file():
        raise SystemExit(f"[ERROR] RSZ 模板不存在: {schema_path}")
    if not ot_dir.is_dir():
        raise SystemExit(f"[ERROR] 目录不存在: {ot_dir}")

    il2cpp_map = None
    if args.il2cpp_map:
        il2cpp_path = Path(args.il2cpp_map)
        if il2cpp_path.exists():
            print(f"加载 IL2CPP 继承树 : {il2cpp_path}")
            with il2cpp_path.open("r", encoding="utf-8") as f:
                il2cpp_map = json.load(f)
        else:
            print(f"[WARN] 指定的 il2cpp map 不存在，将忽略: {il2cpp_path}")

    typedb = TypeDB.load(schema_path, il2cpp_map)
    current_scale = _calc_ot125_scale(args.scale, args.json_dir, args.apply_enemy_scale)

    print(f"目标目录 : {ot_dir}")
    print(f"输出目录 : {output_dir}")
    print(f"_BodyScale: {current_scale}")
    if args.dry_run:
        print("模式     : DRY RUN（预览，不写文件）")

    basic_files = sorted(
        p for p in ot_dir.rglob("*_BasicParam.user.3") if p.parent.name == "CommonData"
    )
    camera_files = sorted(
        p
        for p in ot_dir.rglob("WOt*_CameraParam.user.3")
        if p.parent.name == "CameraData"
    )
    if not basic_files and not camera_files:
        raise SystemExit("[WARN] Ot0125 下未找到可处理的 BasicParam / CameraParam 文件")

    patched = 0
    nomatch = 0
    errors = 0
    original_scale_by_variant: dict[Path, float] = {}

    for basic_path in basic_files:
        variant = basic_path.parent.parent.relative_to(ot_dir)
        original = read_body_scale(basic_path, typedb)
        if original is not None and variant not in original_scale_by_variant:
            original_scale_by_variant[variant] = original

    for src_path in basic_files:
        rel = src_path.relative_to(natives_dir)
        dst_path = output_dir / "natives" / rel
        print(f"[Ot0125]  {src_path.relative_to(ot_dir)}")
        result = patch_body_scale(
            src_path, dst_path, typedb, current_scale, args.dry_run
        )
        if result.status == "patched":
            patched += 1
            if not args.dry_run:
                print(f"  → 已写入: {dst_path}")
        elif result.status == "no_match":
            nomatch += 1
            print(f"  [MISS] {result.message}")
        else:
            errors += 1

    for src_path in camera_files:
        rel = src_path.relative_to(natives_dir)
        dst_path = output_dir / "natives" / rel
        variant = src_path.parent.parent.relative_to(ot_dir)
        original_scale = original_scale_by_variant.get(variant)
        print(f"[Ot0125]  {src_path.relative_to(ot_dir)}")
        result = patch_camera_param(
            src_path,
            dst_path,
            typedb,
            current_scale,
            args.dry_run,
            original_scale=original_scale,
        )
        if result.status == "patched":
            patched += 1
            if not args.dry_run:
                print(f"  → 已写入: {dst_path}")
        elif result.status == "no_match":
            nomatch += 1
            print(f"  [MISS] {result.message}")
        else:
            errors += 1

    print("\n" + "─" * 60)
    print(f"完成  处理: {patched}  未命中: {nomatch}  错误: {errors}")
    if args.dry_run:
        print("（DRY RUN 模式，未写入任何文件）")


if __name__ == "__main__":
    main()
