#!/usr/bin/env python3
"""
normal_otomon_body_scale.py
────────────────────────────────────────────────────────────────
批量将 Otomon BasicParam 的 _BodyScale 还原为指定值（默认 1.0），
并按体型比例调整骑乘相机 AttachOfs。

实现说明:
  使用 PyREUser3 的 repack JSON 格式解析和封包 .user.3，避免手写二进制
  游标解析造成字段错位。repack 格式保留完整实例表和引用关系，适合原地修改。

扫描规则:
  {natives}/STM/GameDesign/Otomon/Ot*/**/CommonData/*_BasicParam.user.3
  {natives}/STM/GameDesign/Otomon/Ot*/**/CameraData/WOt*_CameraParam.user.3

用法示例:
  python normal_otomon_body_scale.py \\
      --natives src/data/unpak/natives \\
      --output  ./out \\
      --scale   1.0
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pyreuser3 import REUser3Converter

# ─── 常量 ──────────────────────────────────────────────────────────────────────
USR_MAGIC = 0x00525355
RSZ_MAGIC = 0x005A5352
SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
RSZ_SCHEMA_PATH = DATA_DIR / "rszmhst3.json"
IL2CPP_DUMP_PATH = DATA_DIR / "il2cpp_dump.json"


@dataclass
class PatchResult:
    status: str  # patched=已修改, no_match=未命中, error=处理失败
    message: str = ""


class PatchNoMatch(Exception):
    """用于中断 patch_file 写入，同时把 no_match 结果带回调用方。"""


class CachedREUser3Converter(REUser3Converter):
    """仍使用 PyREUser3.patch_file，只缓存大型元数据初始化。"""

    def __init__(self, schema_path: Path, il2cpp_dump_path: Path):
        super().__init__(
            schema_path=schema_path,
            il2cpp_dump_path=il2cpp_dump_path,
            user_magic=USR_MAGIC,
            rsz_magic=RSZ_MAGIC,
        )
        self._cached_repack_exporter = None
        self._cached_packer = None

    def _repack_exporter(self):
        if self._cached_repack_exporter is None:
            exporter = self._new_exporter(Path.cwd(), Path.cwd(), [])
            self._prepare_exporter_metadata(exporter)
            self._cached_repack_exporter = exporter
        return self._cached_repack_exporter

    def parse_pack_file(self, user3_path: str | Path) -> dict[str, Any]:
        return self._repack_exporter()._parse_user3_pack(Path(user3_path))

    def pack(self, data: Any) -> bytes:
        if self._cached_packer is None:
            self._cached_packer = self._new_packer(None)
        return self._cached_packer.pack(data)


# ─── repack JSON 工具函数 ─────────────────────────────────────────────────────
def _iter_instances(data: dict[str, Any]):
    instances = data.get("_instances")
    if not isinstance(instances, dict):
        return
    for key in sorted(instances.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
        entry = instances.get(key)
        if not isinstance(entry, dict):
            continue
        fields = entry.get("fields")
        if not isinstance(fields, dict):
            fields = {}
        try:
            idx = int(key)
        except ValueError:
            continue
        yield idx, entry, fields


def _instance_by_id(data: dict[str, Any], idx: int) -> dict[str, Any] | None:
    instances = data.get("_instances")
    if not isinstance(instances, dict):
        return None
    entry = instances.get(str(idx))
    return entry if isinstance(entry, dict) else None


def _ref_instance_id(value: Any) -> int | None:
    if isinstance(value, dict):
        raw = value.get("ref_instance_id")
    else:
        raw = value
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int) and raw > 0:
        return raw
    return None


def _truthy_bool_or_int(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    return False


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v if math.isfinite(v) else None
    return None


def _patch_file_repack(
        src_path: Path,
        dst_path: Path,
        user3: CachedREUser3Converter,
        dry_run: bool,
        patch_data: Callable[[dict[str, Any], bool], PatchResult],
        error_prefix: str,
) -> PatchResult:
    """封装 PyREUser3.patch_file，并保留 dry-run / no_match 语义。"""
    try:
        if dry_run:
            data = user3.parse_pack_file(src_path)
            return patch_data(data, True)

        def callback(data: dict[str, Any], _source_path: Path) -> None:
            result = patch_data(data, False)
            if result.status == "no_match":
                raise PatchNoMatch(result.message)
            if result.status == "error":
                raise RuntimeError(result.message)
            return None

        user3.patch_file(src_path, dst_path, callback)
    except PatchNoMatch as e:
        return PatchResult("no_match", str(e))
    except Exception as e:
        msg = f"{error_prefix}: {e}"
        print(f"  [ERROR] {msg}")
        return PatchResult("error", msg)

    return PatchResult("patched")


# ─── 核心：处理单个 user.3 文件的 _BodyScale ──────────────────────────────────
def _patch_body_scale_data(
        data: dict[str, Any],
        scale: float,
        dry_run: bool,
) -> PatchResult:
    targets: list[tuple[int, dict[str, Any], float]] = []
    for idx, _entry, fields in _iter_instances(data) or []:
        old = _finite_number(fields.get("_BodyScale"))
        if old is not None:
            targets.append((idx, fields, old))

    if not targets:
        msg = "未找到 _BodyScale 字段"
        print(f"  [WARN]  {msg}，跳过")
        return PatchResult("no_match", msg)

    for idx, fields, old in targets:
        if not dry_run:
            fields["_BodyScale"] = float(scale)
        print(
            f"  PATCH  [{idx}]._BodyScale  "
            f"(repack)  {old:.6g} → {scale:.6g}"
            + ("  [DRY RUN]" if dry_run else "")
        )

    return PatchResult("patched")


def patch_body_scale(
        src_path: Path,
        dst_path: Path,
        user3: CachedREUser3Converter,
        scale: float,
        dry_run: bool,
) -> PatchResult:
    """解析 src_path 的 repack 实例表，将所有 _BodyScale 数值改为 scale。"""
    return _patch_file_repack(
        src_path,
        dst_path,
        user3,
        dry_run,
        lambda data, is_dry_run: _patch_body_scale_data(data, scale, is_dry_run),
        "解析失败",
    )


def read_body_scale(src_path: Path, user3: CachedREUser3Converter) -> float | None:
    """读取单个 BasicParam.user.3 中第一个 _BodyScale 值。"""
    try:
        data = user3.parse_pack_file(src_path)
    except Exception:
        return None

    for _idx, _entry, fields in _iter_instances(data) or []:
        v = _finite_number(fields.get("_BodyScale"))
        if v is not None:
            return v
    return None


def _calc_applied_ratio(
        scale: float, original_scale: float | None, k: float = 0.5
) -> tuple[float, float]:
    """根据目标体型与原始体型，计算平滑后的缩放倍率。"""
    base_ratio = scale
    if (
            original_scale is not None
            and math.isfinite(original_scale)
            and abs(original_scale) > 1e-8
    ):
        base_ratio = scale / original_scale
    applied_ratio = 1.0 + (base_ratio - 1.0) * k
    return base_ratio, applied_ratio


def _patch_attach_ofs(
        fields: dict[str, Any],
        instance_idx: int,
        scale_ratio: float,
        dry_run: bool,
        prefix: str,
) -> bool:
    attach_name = "AttachOfs" if "AttachOfs" in fields else "_AttachOfs"
    attach = fields.get(attach_name)
    if not isinstance(attach, list):
        return False

    patched = False
    for arr_i in range(min(3, len(attach))):
        old = _finite_number(attach[arr_i])
        if old is None:
            continue
        new_val = round(old * scale_ratio, 4) if old != 0 else 0.0
        if not dry_run:
            attach[arr_i] = new_val
        patched = True
        print(
            f"  {prefix} [{instance_idx}].{attach_name}[{arr_i}]  "
            f"(repack)  {old:.6g} → {new_val:.6g}"
            + ("  [DRY RUN]" if dry_run else "")
        )
    return patched


def _patch_camera_data(
        data: dict[str, Any],
        scale: float,
        dry_run: bool,
        original_scale: float | None = None,
) -> PatchResult:
    camera_scale_k = 0.5
    base_ratio, scale_ratio = _calc_applied_ratio(scale, original_scale, camera_scale_k)

    patched_any = False
    appdefault_count = 0
    ride_count = 0
    ride_candidate_instances = 0
    arg_resolved_count = 0
    attach_field_count = 0
    attach_readable_count = 0
    patched_targets: set[int] = set()

    for _idx, entry, fields in _iter_instances(data) or []:
        if entry.get("_class") != "app.cCameraParamData_AppDefault":
            continue
        appdefault_count += 1

        has_ride_candidate = "_IsRide" in fields
        if has_ride_candidate:
            ride_candidate_instances += 1
        if not _truthy_bool_or_int(fields.get("_IsRide")):
            continue
        ride_count += 1

        target_idx = _ref_instance_id(fields.get("_CameraParamArgument"))
        if target_idx is None or target_idx in patched_targets:
            continue
        target = _instance_by_id(data, target_idx)
        if not target or target.get("_class") != "app.cCameraParamArgThirdPerson":
            continue
        target_fields = target.get("fields")
        if not isinstance(target_fields, dict):
            continue

        arg_resolved_count += 1
        if "AttachOfs" in target_fields or "_AttachOfs" in target_fields:
            attach_field_count += 1
        if _patch_attach_ofs(
                target_fields, target_idx, scale_ratio, dry_run, "PATCH CAM"
        ):
            patched_any = True
            attach_readable_count += 1
            patched_targets.add(target_idx)

    fallback_thirdperson_count = 0
    if not patched_any:
        for idx, entry, fields in _iter_instances(data) or []:
            if entry.get("_class") != "app.cCameraParamArgThirdPerson":
                continue
            if "AttachOfs" in fields or "_AttachOfs" in fields:
                attach_field_count += 1
            if _patch_attach_ofs(fields, idx, scale_ratio, dry_run, "PATCH CAMF"):
                patched_any = True
                attach_readable_count += 1
                fallback_thirdperson_count += 1

    if patched_any:
        if fallback_thirdperson_count > 0:
            print(
                f"  [INFO] 指针链未命中，已启用 ThirdPerson 实例兜底: "
                f"{fallback_thirdperson_count} 条"
            )
        if original_scale is not None and math.isfinite(original_scale):
            print(
                f"  [INFO] Camera 缩放比(平滑): "
                f"base={scale:.6g}/{original_scale:.6g}={base_ratio:.6g}, "
                f"k={camera_scale_k:.3g}, applied={scale_ratio:.6g}"
            )
        return PatchResult("patched")

    if appdefault_count == 0:
        return PatchResult("no_match", "未找到 app.cCameraParamData_AppDefault 实例")
    if ride_count == 0 and ride_candidate_instances > 0:
        return PatchResult("no_match", "存在 CameraParamData，但 _IsRide 读值全非1")
    if arg_resolved_count == 0:
        return PatchResult(
            "no_match", "Ride 条目存在，但未解析到有效 _CameraParamArgument"
        )
    if attach_field_count == 0:
        return PatchResult("no_match", "已解析到 ThirdPerson，但未找到 AttachOfs 字段")
    if attach_readable_count == 0:
        return PatchResult("no_match", "AttachOfs 存在，但值越界或不可读")
    return PatchResult("no_match", "未命中可修改的 AttachOfs")


def patch_camera_param(
        src_path: Path,
        dst_path: Path,
        user3: CachedREUser3Converter,
        scale: float,
        dry_run: bool,
        original_scale: float | None = None,
) -> PatchResult:
    """修改 WOt*_CameraParam.user.3 中 Ride Camera 的 AttachOfs。"""
    return _patch_file_repack(
        src_path,
        dst_path,
        user3,
        dry_run,
        lambda data, is_dry_run: _patch_camera_data(
            data,
            scale,
            is_dry_run,
            original_scale=original_scale,
        ),
        "CameraParam 解析失败",
    )


# ─── 扫描入口 ──────────────────────────────────────────────────────────────────
def scan_and_patch(
        natives_dir: Path,
        output_dir: Path,
        user3: CachedREUser3Converter,
        scale: float,
        dry_run: bool,
        apply_enemy_scale: bool = False,
        json_dir: str = "",
) -> None:
    """
    扫描 natives_dir/STM/GameDesign/Otomon/Ot*/**/CommonData/*_BasicParam.user.3
    并批量 patch。
    """
    otomon_root = natives_dir / "STM" / "GameDesign" / "Otomon"
    if not otomon_root.is_dir():
        print(f"[ERROR] 目录不存在: {otomon_root}")
        sys.exit(1)

    ot_dirs = sorted(
        d for d in otomon_root.iterdir() if d.is_dir() and re.match(r"^Ot", d.name)
    )
    if not ot_dirs:
        print(f"[WARN] 未找到任何 Ot* 目录: {otomon_root}")
        return

    print(f"发现 {len(ot_dirs)} 个 Ot* 目录，开始扫描…\n")

    processed = skipped = errors = 0
    body_nomatch = 0
    cam_nomatch = 0

    for ot_dir in ot_dirs:
        current_scale = scale
        if apply_enemy_scale and json_dir:
            em_name = ot_dir.name.replace("Ot", "Em")
            base_enemy_dir = Path(json_dir) / "natives" / "STM" / "GameDesign" / "Enemy"
            search_pattern = (
                    base_enemy_dir
                    / em_name
                    / "**"
                    / "CommonData"
                    / f"{em_name}_BasicParam.user.3.json"
            )
            matches = glob.glob(str(search_pattern), recursive=True)
            if matches:
                try:
                    with open(matches[0], "r", encoding="utf-8") as f:
                        enemy_data = json.load(f)
                    enemy_scale = enemy_data[0]["app.user_data.EnemyBasicParam"][
                        "_WorldBodyScale"
                    ]
                    current_scale = round(current_scale + (enemy_scale - 1.0), 4)
                except (IndexError, KeyError, FileNotFoundError, json.JSONDecodeError):
                    pass

        param_files = sorted(
            p
            for p in ot_dir.rglob("*_BasicParam.user.3")
            if p.parent.name == "CommonData"
        )
        camera_files = sorted(
            p
            for p in ot_dir.rglob("WOt*_CameraParam.user.3")
            if p.parent.name == "CameraData"
        )

        original_scale_by_variant: dict[Path, float] = {}
        for basic_path in param_files:
            variant = basic_path.parent.parent.relative_to(ot_dir)
            original = read_body_scale(basic_path, user3)
            if original is not None and variant not in original_scale_by_variant:
                original_scale_by_variant[variant] = original

        if not param_files and not camera_files:
            skipped += 1
            continue

        for src_path in param_files:
            rel_display = src_path.relative_to(ot_dir)
            rel = src_path.relative_to(natives_dir)
            dst_path = output_dir / "natives" / rel

            print(f"[{ot_dir.name}]  {rel_display}")
            result = patch_body_scale(src_path, dst_path, user3, current_scale, dry_run)
            if result.status == "patched":
                processed += 1
                if not dry_run:
                    print(f"  → 已写入: {dst_path}")
            elif result.status == "no_match":
                body_nomatch += 1
            else:
                errors += 1

        for src_path in camera_files:
            rel_display = src_path.relative_to(ot_dir)
            rel = src_path.relative_to(natives_dir)
            dst_path = output_dir / "natives" / rel
            variant = src_path.parent.parent.relative_to(ot_dir)
            original_scale = original_scale_by_variant.get(variant)

            print(f"[{ot_dir.name}]  {rel_display}")
            result = patch_camera_param(
                src_path,
                dst_path,
                user3,
                current_scale,
                dry_run,
                original_scale=original_scale,
            )
            if result.status == "patched":
                processed += 1
                if not dry_run:
                    print(f"  → 已写入: {dst_path}")
            elif result.status == "no_match":
                cam_nomatch += 1
                print(f"  [MISS] CameraParam 未修改: {result.message}")
            else:
                errors += 1

    print(f"\n{'─' * 60}")
    print(
        f"完成  处理: {processed}  跳过目录: {skipped}  "
        f"BodyScale未命中: {body_nomatch}  Camera未命中: {cam_nomatch}  错误: {errors}"
    )
    if dry_run:
        print("（DRY RUN 模式，未写入任何文件）")


# ─── CLI ───────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(
        description="批量将 Otomon BasicParam _BodyScale 设为指定值",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "--natives",
        required=True,
        metavar="DIR",
        help="游戏 natives 目录路径（内含 STM/GameDesign/Otomon/Ot*/…）",
    )
    ap.add_argument(
        "--output",
        required=True,
        metavar="DIR",
        help="输出根目录，文件将写入 {output}/natives/STM/GameDesign/Otomon/…",
    )
    ap.add_argument(
        "--scale",
        type=float,
        default=1.0,
        metavar="FLOAT",
        help="_BodyScale 目标值（默认: 1.0）",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="预览模式：只打印将要执行的操作，不写入文件",
    )
    ap.add_argument(
        "--apply-enemy-scale",
        action="store_true",
        help="是否叠加敌人原始体型到基础 scale（需提供 JSON 数据）",
    )
    ap.add_argument(
        "--json-dir",
        default="src/data/json",
        metavar="DIR",
        help="JSON 数据根目录（应包含 Enums_Internal.json 与 natives 目录）",
    )
    args = ap.parse_args()

    schema_path = RSZ_SCHEMA_PATH
    if not schema_path.is_file():
        print(f"[ERROR] RSZ 模板不存在: {schema_path}")
        sys.exit(1)

    il2cpp_dump_path = IL2CPP_DUMP_PATH
    if not il2cpp_dump_path.is_file():
        print(f"[ERROR] il2cpp_dump.json 不存在: {il2cpp_dump_path}")
        sys.exit(1)

    natives_dir = Path(args.natives)
    if not natives_dir.is_dir():
        print(f"[ERROR] natives 目录不存在: {natives_dir}")
        sys.exit(1)

    output_dir = Path(args.output)

    print(f"RSZ 模板 : {schema_path}")
    print(f"IL2CPP   : {il2cpp_dump_path}")
    print(f"natives  : {natives_dir}")
    print(f"输出目录 : {output_dir / 'natives'}")
    print(f"_BodyScale: {args.scale}")
    if args.dry_run:
        print("模式     : DRY RUN（预览，不写文件）")
    print()

    try:
        user3 = CachedREUser3Converter(schema_path, il2cpp_dump_path)
    except Exception as e:
        print(f"[ERROR] 初始化 PyREUser3 失败: {e}")
        sys.exit(1)

    scan_and_patch(
        natives_dir,
        output_dir,
        user3,
        args.scale,
        args.dry_run,
        args.apply_enemy_scale,
        args.json_dir,
    )


if __name__ == "__main__":
    main()
