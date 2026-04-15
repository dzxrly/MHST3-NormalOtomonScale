#!/usr/bin/env python3
"""
normal_otomon_body_scale.py
────────────────────────────────────────────────────────────────
批量将 Otomon BasicParam 的 _BodyScale 还原为指定值（默认 1.0）。

扫描规则:
  {natives}/STM/GameDesign/Otomon/Ot*/**/CommonData/*_BasicParam.user.3
  （递归匹配 Ot* 下所有子目录中的 CommonData，涵盖 00/01/02/XX 等变体）

用法示例:
  # 最简用法（自动查找 rszmhst3.json，输出到 ./out/）
  python normal_otomon_body_scale.py \\
      --natives D:/game/natives \\
      --output  ./out

  # 指定 RSZ 模板 + 自定义体型缩放值
  python normal_otomon_body_scale.py \\
      --rsz     D:/tools/rszmhst3.json \\
      --natives D:/game/natives \\
      --output  ./out \\
      --scale   0.9

  # 只预览，不写入文件
  python normal_otomon_body_scale.py \\
      --natives D:/game/natives \\
      --output  ./out \\
      --dry-run

输出目录结构（保持 natives/ 以下的相对路径不变）:
  {output}/natives/STM/GameDesign/Otomon/Ot0160/XX/CommonData/Ot0160_BasicParam.user.3
  {output}/natives/STM/GameDesign/Otomon/Ot0162/XX/CommonData/Ot0162_BasicParam.user.3
  ...
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

# ─── 常量 ──────────────────────────────────────────────────────────────────────
USR_MAGIC = 0x00525355
RSZ_MAGIC = 0x005A5352

_SCALAR_SIZES: dict[str, int] = {
    "Bool": 1, "S8": 1, "U8": 1,
    "S16": 2, "U16": 2,
    "S32": 4, "U32": 4, "F32": 4, "Enum": 4, "Sfix": 4,
    "S64": 8, "U64": 8, "F64": 8,
    "Object": 4, "UserData": 4,
    "Guid": 16, "GameObjectRef": 16, "Uri": 16,
    "Float2": 8,  "Vec2": 8,
    "Float3": 12, "Vec3": 12, "Position": 12,
    "Float4": 16, "Vec4": 16, "Quaternion": 16, "Color": 16,
    "AABB": 24, "Capsule": 32, "OBB": 52, "Mat3": 36, "Mat4": 64,
}

_VEC_COMPS: dict[str, int] = {
    "Float2": 2, "Vec2": 2,
    "Float3": 3, "Vec3": 3, "Position": 3,
    "Float4": 4, "Vec4": 4, "Quaternion": 4, "Color": 4,
    "AABB": 6, "Capsule": 8, "OBB": 13, "Mat3": 9, "Mat4": 16,
}


# ─── 工具函数 ──────────────────────────────────────────────────────────────────
def _align(pos: int, a: int) -> int:
    if a <= 1:
        return pos
    return (pos + a - 1) & ~(a - 1)


def _murmur3_32(data: bytes, seed: int = 0xFFFFFFFF) -> int:
    c1, c2 = 0xCC9E2D51, 0x1B873593
    h1 = seed & 0xFFFFFFFF
    length = len(data)
    rounded_end = length & ~0x3

    for i in range(0, rounded_end, 4):
        k1 = int.from_bytes(data[i: i + 4], "little")
        k1 = (k1 * c1) & 0xFFFFFFFF
        k1 = ((k1 << 15) | (k1 >> 17)) & 0xFFFFFFFF
        k1 = (k1 * c2) & 0xFFFFFFFF
        h1 ^= k1
        h1 = ((h1 << 13) | (h1 >> 19)) & 0xFFFFFFFF
        h1 = (h1 * 5 + 0xE6546B64) & 0xFFFFFFFF

    k1 = 0
    tail = data[rounded_end:]
    if len(tail) == 3:
        k1 ^= tail[2] << 16
    if len(tail) >= 2:
        k1 ^= tail[1] << 8
    if len(tail) >= 1:
        k1 ^= tail[0]
        k1 = (k1 * c1) & 0xFFFFFFFF
        k1 = ((k1 << 15) | (k1 >> 17)) & 0xFFFFFFFF
        k1 = (k1 * c2) & 0xFFFFFFFF
        h1 ^= k1

    h1 ^= length
    h1 ^= h1 >> 16
    h1 = (h1 * 0x85EBCA6B) & 0xFFFFFFFF
    h1 ^= h1 >> 13
    h1 = (h1 * 0xC2B2AE35) & 0xFFFFFFFF
    h1 ^= h1 >> 16
    return h1 & 0xFFFFFFFF


# ─── 类型数据库 ────────────────────────────────────────────────────────────────
@dataclass
class FieldDef:
    name: str
    field_type: str
    original_type: str
    size: int
    align: int
    is_array: bool


@dataclass
class ClassDef:
    name: str
    crc: int
    fields: list[FieldDef]


class TypeDB:
    """从 rszmhst3.json 加载类型定义。"""

    def __init__(self, classes: dict[int, ClassDef]):
        self.classes = classes
        self.name_to_hash: dict[str, int] = {c.name: h for h, c in classes.items()}

    @classmethod
    def load(cls, json_path: Path) -> "TypeDB":
        with json_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        classes: dict[int, ClassDef] = {}
        for key, value in raw.items():
            try:
                class_hash = int(key, 16)
            except ValueError:
                continue
            fields: list[FieldDef] = []
            for field in value.get("fields", []):
                fields.append(FieldDef(
                    name=field.get("name", ""),
                    field_type=field.get("type", "Data"),
                    original_type=field.get("original_type", ""),
                    size=int(field.get("size", 0)),
                    align=int(field.get("align", 1)),
                    is_array=bool(field.get("array", False)),
                ))
            crc_raw = value.get("crc", "0")
            crc = int(crc_raw, 16) if isinstance(crc_raw, str) else int(crc_raw)
            classes[class_hash] = ClassDef(
                name=value.get("name", ""), crc=crc, fields=fields,
            )
        return cls(classes)

    def get_class(self, class_hash: int) -> ClassDef | None:
        return self.classes.get(class_hash)

    def resolve_struct_hash(self, original_type: str) -> int | None:
        if not original_type:
            return None
        known = self.name_to_hash.get(original_type)
        if known is not None:
            return known
        maybe = _murmur3_32(original_type.encode("utf-8"), seed=0xFFFFFFFF)
        if maybe in self.classes:
            return maybe
        return None


# ─── 字段记录 ──────────────────────────────────────────────────────────────────
@dataclass
class FieldRecord:
    instance_idx: int
    class_name:   str
    field_name:   str
    field_type:   str
    byte_offset:  int
    field_size:   int
    array_index:  int | None

    def read_f32(self, buf: bytearray) -> float:
        return struct.unpack_from("<f", buf, self.byte_offset)[0]

    def write_f32(self, buf: bytearray, value: float) -> None:
        struct.pack_into("<f", buf, self.byte_offset, value)


# ─── .user.3 解析器 ────────────────────────────────────────────────────────────
class User3Parser:
    def __init__(self, data: bytes, typedb: TypeDB):
        self.buf = bytearray(data)
        self.typedb = typedb
        self.records: list[FieldRecord] = []

    def _u32(self, pos: int) -> int:
        return struct.unpack_from("<I", self.buf, pos)[0]

    def _i32(self, pos: int) -> int:
        return struct.unpack_from("<i", self.buf, pos)[0]

    def _u64(self, pos: int) -> int:
        return struct.unpack_from("<Q", self.buf, pos)[0]

    def _i64(self, pos: int) -> int:
        return struct.unpack_from("<q", self.buf, pos)[0]

    def parse(self) -> None:
        if self._u32(0) != USR_MAGIC:
            raise ValueError(f"不是 user 文件 (magic={self._u32(0):#010x})")
        rs = self._u64(32)
        if self._u32(rs) != RSZ_MAGIC:
            raise ValueError(f"RSZ magic 不匹配 ({self._u32(rs):#010x})")

        inst_count = self._i32(rs + 12)
        inst_off   = self._i64(rs + 24)
        dat_off    = self._i64(rs + 32)

        inst_hashes: list[int] = []
        for i in range(inst_count):
            inst_hashes.append(self._u32(rs + inst_off + i * 8))

        cursor = rs + dat_off
        for idx, h in enumerate(inst_hashes):
            if idx == 0:
                continue
            cls = self.typedb.get_class(h)
            if cls is None or not cls.fields:
                continue
            first = cls.fields[0]
            cursor = _align(cursor, 4 if first.is_array else max(first.align, 1))
            cursor = self._parse_instance(cursor, idx, cls)

    def _parse_instance(self, cursor: int, idx: int, cls: ClassDef) -> int:
        for fld in cls.fields:
            cursor = _align(cursor, 4 if fld.is_array else max(fld.align, 1))
            cursor = self._parse_field(cursor, idx, cls.name, fld, None)
        return cursor

    def _parse_field(self, cursor: int, idx: int, class_name: str,
                     fld: FieldDef, arr_index_override: int | None) -> int:
        if fld.is_array:
            if cursor + 4 > len(self.buf):
                return cursor
            count = struct.unpack_from("<I", self.buf, cursor)[0]
            cursor += 4
            if count > 500_000:
                return cursor
            for arr_i in range(count):
                cursor = _align(cursor, max(fld.align, 1))
                cursor = self._parse_scalar(cursor, idx, class_name, fld, arr_i)
            return cursor
        return self._parse_scalar(cursor, idx, class_name, fld, arr_index_override)

    def _parse_scalar(self, cursor: int, idx: int, class_name: str,
                      fld: FieldDef, arr_index: int | None) -> int:
        t = fld.field_type
        size = _SCALAR_SIZES.get(t, -1)

        if t in ("String", "Resource"):
            cursor = _align(cursor, 4)
            if cursor + 4 > len(self.buf):
                return cursor
            length = struct.unpack_from("<I", self.buf, cursor)[0]
            if length > 2_000_000:
                return cursor
            return cursor + 4 + length * 2

        if t == "C8":
            cursor = _align(cursor, 4)
            if cursor + 4 > len(self.buf):
                return cursor
            length = struct.unpack_from("<I", self.buf, cursor)[0]
            if length > 2_000_000:
                return cursor
            return cursor + 4 + length

        if t in ("Object", "UserData"):
            return cursor + 4
        if t in ("Guid", "GameObjectRef", "Uri"):
            return cursor + 16

        if t == "Struct":
            sh = self.typedb.resolve_struct_hash(fld.original_type)
            if sh is not None:
                sub_cls = self.typedb.get_class(sh)
                if sub_cls is not None:
                    start = cursor
                    for sf in sub_cls.fields:
                        cursor = _align(cursor, 4 if sf.is_array else max(sf.align, 1))
                        sub_fld = FieldDef(
                            name=f"{fld.name}.{sf.name}",
                            field_type=sf.field_type,
                            original_type=sf.original_type,
                            size=sf.size, align=sf.align, is_array=sf.is_array,
                        )
                        cursor = self._parse_field(cursor, idx, class_name, sub_fld, None)
                    parsed = cursor - start
                    if fld.size > parsed:
                        cursor += fld.size - parsed
                    return cursor
            return cursor + max(fld.size, 0)

        if size < 0:
            return cursor + max(fld.size, 0)
        if cursor + size > len(self.buf):
            return cursor + size

        fname = fld.name or "unnamed"

        if t in _VEC_COMPS:
            n = _VEC_COMPS[t]
            for ci in range(n):
                off = cursor + ci * 4
                if off + 4 > len(self.buf):
                    break
                comp_name = (
                    f"{fname}[{ci}]" if arr_index is None
                    else f"{fname}[{arr_index}][{ci}]"
                )
                self.records.append(FieldRecord(
                    instance_idx=idx, class_name=class_name,
                    field_name=comp_name, field_type="F32",
                    byte_offset=off, field_size=4, array_index=None,
                ))
            return cursor + size

        self.records.append(FieldRecord(
            instance_idx=idx, class_name=class_name,
            field_name=fname, field_type=t,
            byte_offset=cursor, field_size=size, array_index=arr_index,
        ))
        return cursor + size


# ─── RSZ 模板自动查找 ──────────────────────────────────────────────────────────
def _find_schema() -> Path | None:
    candidates = [
        Path(__file__).resolve().parent / "rszmhst3.json",
        Path.cwd() / "rszmhst3.json",
    ]
    p = Path(__file__).resolve().parent
    for _ in range(4):
        p = p.parent
        candidates.append(p / "rszmhst3.json")
    for c in candidates:
        if c.is_file():
            return c
    return None


# ─── 核心：patch 单个 user.3 文件的 _BodyScale ─────────────────────────────────
def patch_body_scale(
    src_path: Path,
    dst_path: Path,
    typedb: TypeDB,
    scale: float,
    dry_run: bool,
) -> bool:
    """
    解析 src_path，将所有名为 _BodyScale 的 F32 字段改为 scale，
    写入 dst_path（dry_run 时仅打印，不写文件）。
    返回 True 表示找到并处理了字段，False 表示未找到目标字段。
    """
    try:
        parser = User3Parser(src_path.read_bytes(), typedb)
        parser.parse()
    except Exception as e:
        print(f"  [ERROR] 解析失败: {e}")
        return False

    targets = [r for r in parser.records if r.field_name == "_BodyScale"]
    if not targets:
        print(f"  [WARN]  未找到 _BodyScale 字段，跳过")
        return False

    for rec in targets:
        old = rec.read_f32(parser.buf)
        if not dry_run:
            rec.write_f32(parser.buf, scale)
        new = scale
        print(f"  PATCH  [{rec.instance_idx}]._BodyScale  "
              f"(F32 @ {rec.byte_offset:#010x})  {old:.6g} → {new:.6g}"
              + ("  [DRY RUN]" if dry_run else ""))

    if not dry_run:
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        dst_path.write_bytes(bytes(parser.buf))

    return True


# ─── 扫描入口 ──────────────────────────────────────────────────────────────────
def scan_and_patch(
    natives_dir: Path,
    output_dir: Path,
    typedb: TypeDB,
    scale: float,
    dry_run: bool,
) -> None:
    """
    扫描 natives_dir/STM/GameDesign/Otomon/Ot*/**/CommonData/*_BasicParam.user.3
    并批量 patch。
    """
    otomon_root = natives_dir / "STM" / "GameDesign" / "Otomon"
    if not otomon_root.is_dir():
        print(f"[ERROR] 目录不存在: {otomon_root}")
        sys.exit(1)

    # 找出所有以 Ot 开头的子目录（忽略 CommonData 等公共目录）
    ot_dirs = sorted(
        d for d in otomon_root.iterdir()
        if d.is_dir() and re.match(r"^Ot", d.name)
    )
    if not ot_dirs:
        print(f"[WARN] 未找到任何 Ot* 目录: {otomon_root}")
        return

    print(f"发现 {len(ot_dirs)} 个 Ot* 目录，开始扫描…\n")

    processed = skipped = errors = 0

    for ot_dir in ot_dirs:
        # 递归匹配所有 **/CommonData/*_BasicParam.user.3
        param_files = sorted(
            p for p in ot_dir.rglob("*_BasicParam.user.3")
            if p.parent.name == "CommonData"
        )
        if not param_files:
            skipped += 1
            continue

        for src_path in param_files:
            # 显示相对于 Ot* 目录的路径，便于识别是哪个变体（00/01/02/XX 等）
            rel_display = src_path.relative_to(ot_dir)
            # 输出保持 natives/ 以下完整相对路径
            rel = src_path.relative_to(natives_dir)
            dst_path = output_dir / "natives" / rel

            print(f"[{ot_dir.name}]  {rel_display}")
            ok = patch_body_scale(src_path, dst_path, typedb, scale, dry_run)
            if ok:
                processed += 1
                if not dry_run:
                    print(f"  → 已写入: {dst_path}")
            else:
                errors += 1

    print(f"\n{'─'*60}")
    print(f"完成  处理: {processed}  跳过(无匹配 BasicParam): {skipped}  错误: {errors}")
    if dry_run:
        print("（DRY RUN 模式，未写入任何文件）")


# ─── CLI ───────────────────────────────────────────────────────────────────────
def main() -> None:
    auto_schema = _find_schema()

    ap = argparse.ArgumentParser(
        description="批量将 Otomon BasicParam _BodyScale 设为指定值",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "--rsz", "--schema", dest="schema",
        default=str(auto_schema) if auto_schema else None,
        metavar="RSZ_JSON",
        help=(
            "rszmhst3.json（RSZ 类型模板）路径"
            + (f"（自动找到: {auto_schema}）" if auto_schema else
               "（未自动找到，需手动指定）")
        ),
    )
    ap.add_argument(
        "--natives", required=True, metavar="DIR",
        help="游戏 natives 目录路径（内含 STM/GameDesign/Otomon/Ot*/…）",
    )
    ap.add_argument(
        "--output", required=True, metavar="DIR",
        help="输出根目录，文件将写入 {output}/natives/STM/GameDesign/Otomon/…",
    )
    ap.add_argument(
        "--scale", type=float, default=1.0, metavar="FLOAT",
        help="_BodyScale 目标值（默认: 1.0）",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="预览模式：只打印将要执行的操作，不写入文件",
    )
    args = ap.parse_args()

    if not args.schema:
        print("[ERROR] 未找到 rszmhst3.json，请用 --rsz 手动指定 RSZ 模板路径。")
        sys.exit(1)

    schema_path = Path(args.schema)
    if not schema_path.is_file():
        print(f"[ERROR] RSZ 模板不存在: {schema_path}")
        sys.exit(1)

    natives_dir = Path(args.natives)
    if not natives_dir.is_dir():
        print(f"[ERROR] natives 目录不存在: {natives_dir}")
        sys.exit(1)

    output_dir = Path(args.output)

    print(f"RSZ 模板 : {schema_path}")
    print(f"natives  : {natives_dir}")
    print(f"输出目录 : {output_dir / 'natives'}")
    print(f"_BodyScale: {args.scale}")
    if args.dry_run:
        print("模式     : DRY RUN（预览，不写文件）")
    print()

    typedb = TypeDB.load(schema_path)
    scan_and_patch(natives_dir, output_dir, typedb, args.scale, args.dry_run)


if __name__ == "__main__":
    main()
