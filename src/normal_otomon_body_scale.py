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
import glob
import json
import math
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

# ─── 常量 ──────────────────────────────────────────────────────────────────────
USR_MAGIC = 0x00525355
RSZ_MAGIC = 0x005A5352

_SCALAR_SIZES: dict[str, int] = {
    "Bool": 1,
    "S8": 1,
    "U8": 1,
    "S16": 2,
    "U16": 2,
    "S32": 4,
    "U32": 4,
    "F32": 4,
    "Enum": 4,
    "Sfix": 4,
    "S64": 8,
    "U64": 8,
    "F64": 8,
    "Object": 4,
    "UserData": 4,
    "Guid": 16,
    "GameObjectRef": 16,
    "Uri": 16,
    "Float2": 8,
    "Vec2": 8,
    "Float3": 16,  # RE 引擎中 via.vec3 与 via.Position 按 16 字节对齐
    "Vec3": 16,
    "Position": 16,
    "Float4": 16,
    "Vec4": 16,
    "Quaternion": 16,
    "Color": 16,
    "AABB": 24,
    "Capsule": 32,
    "OBB": 52,
    "Mat3": 36,
    "Mat4": 64,
}

_VEC_COMPS: dict[str, int] = {
    "Float2": 2,
    "Vec2": 2,
    "Float3": 3,
    "Vec3": 3,
    "Position": 3,
    "Float4": 4,
    "Vec4": 4,
    "Quaternion": 4,
    "Color": 4,
    "AABB": 6,
    "Capsule": 8,
    "OBB": 13,
    "Mat3": 9,
    "Mat4": 16,
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
        k1 = int.from_bytes(data[i : i + 4], "little")
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


@dataclass
class LayoutField:
    name: str
    field_type: str
    offset: int | None
    size: int | None
    align: int
    is_array: bool
    is_dynamic: bool


class TypeDB:
    """从 rszmhst3.json 加载类型定义。"""

    def __init__(self, classes: dict[int, ClassDef]):
        self.classes = classes
        self.name_to_hash: dict[str, int] = {c.name: h for h, c in classes.items()}
        self._layout_cache: dict[int, list[LayoutField]] = {}

    @classmethod
    def load(cls, json_path: Path, il2cpp_map: dict[str, str] = None) -> "TypeDB":
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
                fields.append(
                    FieldDef(
                        name=field.get("name", ""),
                        field_type=field.get("type", "Data"),
                        original_type=field.get("original_type", ""),
                        size=int(field.get("size", 0)),
                        align=int(field.get("align", 1)),
                        is_array=bool(field.get("array", False)),
                    )
                )
            crc_raw = value.get("crc", "0")
            crc = int(crc_raw, 16) if isinstance(crc_raw, str) else int(crc_raw)
            classes[class_hash] = ClassDef(
                name=value.get("name", ""),
                crc=crc,
                fields=fields,
            )

        instance = cls(classes)

        # 2. 如果提供了 il2cpp 继承关系映射，将所有基类的字段合并到子类中
        if il2cpp_map:
            # 预定义所有可解析类
            resolved_fields: dict[str, list[FieldDef]] = {}
            resolving_stack: set[str] = set()
            cycle_classes: set[str] = set()
            map_hits = 0
            map_misses = 0

            def get_all_fields(c_name: str) -> list[FieldDef]:
                if c_name in resolved_fields:
                    return resolved_fields[c_name]

                if c_name in resolving_stack:
                    # 防止坏映射导致继承环（例如 A->B, B->A）卡死。
                    cycle_classes.add(c_name)
                    return []

                resolving_stack.add(c_name)
                local_flds = []
                c_hash = instance.name_to_hash.get(c_name)
                if c_hash:
                    local_flds = instance.classes[c_hash].fields.copy()

                parent_name = il2cpp_map.get(c_name)
                if parent_name and parent_name != c_name:
                    nonlocal map_hits, map_misses
                    if parent_name in instance.name_to_hash:
                        map_hits += 1
                    else:
                        map_misses += 1
                    parent_flds = get_all_fields(parent_name)

                    # RE Engine 中基类字段在内存排布上位于子类之前。
                    # 但部分 RSZ（尤其 user_data）已将父类字段扁平展开到子类里，
                    # 若直接 parent + local 会导致字段重复并造成后续游标错位。
                    def _sig(f: FieldDef) -> tuple[str, str, str, int, int, bool]:
                        return (
                            f.name,
                            f.field_type,
                            f.original_type,
                            f.size,
                            f.align,
                            f.is_array,
                        )

                    max_overlap = min(len(parent_flds), len(local_flds))
                    overlap = 0
                    for k in range(max_overlap, 0, -1):
                        if [_sig(f) for f in parent_flds[-k:]] == [
                            _sig(f) for f in local_flds[:k]
                        ]:
                            overlap = k
                            break

                    resolved = parent_flds + local_flds[overlap:]
                else:
                    resolved = local_flds

                resolved_fields[c_name] = resolved
                resolving_stack.discard(c_name)
                return resolved

            # 应用所有的继承字段覆盖原本的 fields
            for cdef in instance.classes.values():
                cdef.fields = get_all_fields(cdef.name)

            if cycle_classes:
                sample = ", ".join(sorted(cycle_classes)[:5])
                print(
                    f"[WARN] IL2CPP 映射中检测到继承环，已跳过循环路径。"
                    f" classes={len(cycle_classes)} sample=[{sample}]"
                )
            print(f"IL2CPP 映射应用完成: 继承命中={map_hits}, 继承缺失={map_misses}")

        return instance

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

    def _field_fixed_size(
        self, fld: FieldDef, visited_structs: set[int] | None = None
    ) -> int | None:
        if fld.is_array:
            return None
        if fld.field_type in ("String", "Resource", "C8"):
            return None

        if fld.field_type == "Struct":
            if fld.size > 0:
                return fld.size
            sh = self.resolve_struct_hash(fld.original_type)
            if sh is None:
                return None
            return self._compute_class_fixed_size(sh, visited_structs)

        if fld.size > 0:
            return fld.size
        return _SCALAR_SIZES.get(fld.field_type)

    def _compute_class_fixed_size(
        self, class_hash: int, visited_structs: set[int] | None = None
    ) -> int | None:
        cls = self.get_class(class_hash)
        if cls is None:
            return None
        if visited_structs is None:
            visited_structs = set()
        if class_hash in visited_structs:
            return None

        visited_structs.add(class_hash)
        cursor = 0
        for fld in cls.fields:
            cursor = _align(cursor, 4 if fld.is_array else max(fld.align, 1))
            step = self._field_fixed_size(fld, visited_structs)
            if step is None or step < 0:
                visited_structs.remove(class_hash)
                return None
            cursor += step
        visited_structs.remove(class_hash)
        return cursor

    def get_class_layout(self, class_name: str) -> list[LayoutField]:
        class_hash = self.name_to_hash.get(class_name)
        if class_hash is None:
            return []
        if class_hash in self._layout_cache:
            return self._layout_cache[class_hash]

        cls = self.get_class(class_hash)
        if cls is None:
            return []

        cursor = 0
        dynamic_seen = False
        layout: list[LayoutField] = []

        for fld in cls.fields:
            align = 4 if fld.is_array else max(fld.align, 1)
            if not dynamic_seen:
                cursor = _align(cursor, align)
                field_offset: int | None = cursor
            else:
                field_offset = None

            step = self._field_fixed_size(fld)
            is_dynamic = step is None or step < 0

            layout.append(
                LayoutField(
                    name=fld.name or "unnamed",
                    field_type=fld.field_type,
                    offset=field_offset,
                    size=step if not is_dynamic else None,
                    align=align,
                    is_array=fld.is_array,
                    is_dynamic=is_dynamic,
                )
            )

            if dynamic_seen:
                continue
            if is_dynamic:
                dynamic_seen = True
            else:
                cursor += step

        self._layout_cache[class_hash] = layout
        return layout

    def get_expanded_offset_map(self, class_name: str) -> dict[str, list[int]]:
        """
        结合 RSZ + IL2CPP 推导 class 内字段偏移。
        对 Vec/Mat 等会同时展开字段分量（如 AttachOfs[0..2]）。
        """
        out: dict[str, list[int]] = {}
        for fld in self.get_class_layout(class_name):
            if fld.offset is None:
                continue
            out.setdefault(fld.name, []).append(fld.offset)
            comps = _VEC_COMPS.get(fld.field_type)
            if comps is None:
                continue
            max_comps = comps
            if fld.size is not None and fld.size >= 4:
                max_comps = min(max_comps, fld.size // 4)
            for i in range(max_comps):
                out.setdefault(f"{fld.name}[{i}]", []).append(fld.offset + i * 4)
        return out


# ─── 字段记录 ──────────────────────────────────────────────────────────────────
@dataclass
class FieldRecord:
    instance_idx: int
    class_name: str
    field_name: str
    field_type: str
    byte_offset: int
    field_size: int
    array_index: int | None

    def read_f32(self, buf: bytearray) -> float:
        return struct.unpack_from("<f", buf, self.byte_offset)[0]

    def write_f32(self, buf: bytearray, value: float) -> None:
        struct.pack_into("<f", buf, self.byte_offset, value)

    def read_u8(self, buf: bytearray) -> int:
        return struct.unpack_from("<B", buf, self.byte_offset)[0]

    def read_i32(self, buf: bytearray) -> int:
        return struct.unpack_from("<i", buf, self.byte_offset)[0]


@dataclass
class PatchResult:
    status: str  # patched=已修改, no_match=未命中, error=处理失败
    message: str = ""


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
        inst_off = self._i64(rs + 24)
        dat_off = self._i64(rs + 32)

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

    def _parse_field(
        self,
        cursor: int,
        idx: int,
        class_name: str,
        fld: FieldDef,
        arr_index_override: int | None,
    ) -> int:
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

    def _parse_scalar(
        self,
        cursor: int,
        idx: int,
        class_name: str,
        fld: FieldDef,
        arr_index: int | None,
    ) -> int:
        t = fld.field_type
        fallback_size = _SCALAR_SIZES.get(t, -1)
        # 优先信任 RSZ 模板中的 size，避免硬编码标量尺寸导致游标错位。
        # 例如某些 via.vec2 在 user.3 中按 16 字节布局（含 padding）。
        size = fld.size if fld.size > 0 else fallback_size

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
            self.records.append(
                FieldRecord(
                    instance_idx=idx,
                    class_name=class_name,
                    field_name=fld.name or "unnamed",
                    field_type=t,
                    byte_offset=cursor,
                    field_size=4,
                    array_index=arr_index,
                )
            )
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
                            size=sf.size,
                            align=sf.align,
                            is_array=sf.is_array,
                        )
                        cursor = self._parse_field(
                            cursor, idx, class_name, sub_fld, None
                        )
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
                    f"{fname}[{ci}]"
                    if arr_index is None
                    else f"{fname}[{arr_index}][{ci}]"
                )
                self.records.append(
                    FieldRecord(
                        instance_idx=idx,
                        class_name=class_name,
                        field_name=comp_name,
                        field_type="F32",
                        byte_offset=off,
                        field_size=4,
                        array_index=None,
                    )
                )
            return cursor + size

        self.records.append(
            FieldRecord(
                instance_idx=idx,
                class_name=class_name,
                field_name=fname,
                field_type=t,
                byte_offset=cursor,
                field_size=size,
                array_index=arr_index,
            )
        )
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


# ─── 核心：处理单个 user.3 文件的 _BodyScale ──────────────────────────────────
def patch_body_scale(
    src_path: Path,
    dst_path: Path,
    typedb: TypeDB,
    scale: float,
    dry_run: bool,
) -> PatchResult:
    """
    解析 src_path，将所有名为 _BodyScale 的 F32 字段改为 scale，
    写入 dst_path（dry_run 时仅打印，不写文件）。
    返回 True 表示找到并处理了字段，False 表示未找到目标字段。
    """
    try:
        parser = User3Parser(src_path.read_bytes(), typedb)
        parser.parse()
    except Exception as e:
        msg = f"解析失败: {e}"
        print(f"  [ERROR] {msg}")
        return PatchResult("error", msg)

    targets = [r for r in parser.records if r.field_name == "_BodyScale"]
    if not targets:
        msg = "未找到 _BodyScale 字段"
        print(f"  [WARN]  {msg}，跳过")
        return PatchResult("no_match", msg)

    for rec in targets:
        old = rec.read_f32(parser.buf)
        if not dry_run:
            rec.write_f32(parser.buf, scale)
        new = scale
        print(
            f"  PATCH  [{rec.instance_idx}]._BodyScale  "
            f"(F32 @ {rec.byte_offset:#010x})  {old:.6g} → {new:.6g}"
            + ("  [DRY RUN]" if dry_run else "")
        )

    if not dry_run:
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        dst_path.write_bytes(bytes(parser.buf))

    return PatchResult("patched")


def read_body_scale(src_path: Path, typedb: TypeDB) -> float | None:
    """读取单个 BasicParam.user.3 中第一个 _BodyScale 值。"""
    try:
        parser = User3Parser(src_path.read_bytes(), typedb)
        parser.parse()
    except Exception:
        return None

    for rec in parser.records:
        if rec.field_name != "_BodyScale":
            continue
        try:
            v = rec.read_f32(parser.buf)
        except struct.error:
            continue
        if math.isfinite(v):
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


def patch_camera_param(
    src_path: Path,
    dst_path: Path,
    typedb: TypeDB,
    scale: float,
    dry_run: bool,
    original_scale: float | None = None,
) -> PatchResult:
    """
    修改 WOt*_CameraParam.user.3 中 Ride Camera 的 AttachOfs。
    使用完全解析实例结构的方法（得益于修复后的 TypeDB），彻底安全的寻址
    """
    try:
        parser = User3Parser(src_path.read_bytes(), typedb)
        parser.parse()
    except Exception as e:
        msg = f"CameraParam 解析失败: {e}"
        print(f"  [ERROR] {msg}")
        return PatchResult("error", msg)

    def _safe_read_i32(rec: FieldRecord) -> int | None:
        try:
            return rec.read_i32(parser.buf)
        except struct.error:
            return None

    def _safe_read_u8(rec: FieldRecord) -> int | None:
        try:
            return rec.read_u8(parser.buf)
        except struct.error:
            return None

    def _safe_read_f32(rec: FieldRecord) -> float | None:
        try:
            v = rec.read_f32(parser.buf)
            if not math.isfinite(v):
                return None
            return v
        except struct.error:
            return None

    camera_scale_k = 0.5
    base_ratio, scale_ratio = _calc_applied_ratio(scale, original_scale, camera_scale_k)

    instances: dict[int, dict[str, FieldRecord]] = {}
    # 同名字段可能因继承链合并出现重复，保留所有候选避免覆盖后丢失正确记录。
    instances_multi: dict[int, dict[str, list[FieldRecord]]] = {}
    for r in parser.records:
        if r.instance_idx not in instances:
            instances[r.instance_idx] = {}
        if r.instance_idx not in instances_multi:
            instances_multi[r.instance_idx] = {}
        key = (
            r.field_name
            if r.array_index is None
            else f"{r.field_name}[{r.array_index}]"
        )
        instances[r.instance_idx][key] = r
        if key not in instances_multi[r.instance_idx]:
            instances_multi[r.instance_idx][key] = []
        instances_multi[r.instance_idx][key].append(r)

    camera_layout = typedb.get_expanded_offset_map("app.cCameraParamData_AppDefault")
    third_person_layout = typedb.get_expanded_offset_map(
        "app.cCameraParamArgThirdPerson"
    )
    base_cache: dict[tuple[int, str], int | None] = {}

    def _infer_instance_base(
        instance_idx: int, class_name: str, expected_map: dict[str, list[int]]
    ) -> int | None:
        cache_key = (instance_idx, class_name)
        if cache_key in base_cache:
            return base_cache[cache_key]

        fields_multi = instances_multi.get(instance_idx, {})
        scores: dict[int, int] = {}
        for key, recs in fields_multi.items():
            expected_offsets = expected_map.get(key, [])
            if not expected_offsets:
                continue
            for rec in recs:
                for exp in expected_offsets:
                    base = rec.byte_offset - exp
                    scores[base] = scores.get(base, 0) + 1

        best = None
        if scores:
            # 先取命中次数最多的基址；若并列，偏向较小地址（通常更接近实例起始）
            best = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        base_cache[cache_key] = best
        return best

    def _pick_by_expected_offset(
        candidates: list[FieldRecord],
        expected_offsets: list[int],
        instance_base: int | None,
    ) -> FieldRecord | None:
        if not candidates:
            return None
        if instance_base is None or not expected_offsets:
            return candidates[0]
        expected_set = set(expected_offsets)
        for rec in candidates:
            rel = rec.byte_offset - instance_base
            if rel in expected_set:
                return rec
        return candidates[0]

    patched_any = False
    appdefault_count = 0
    ride_count = 0
    ride_candidate_instances = 0
    arg_resolved_count = 0
    attach_field_count = 0
    attach_readable_count = 0
    fallback_thirdperson_count = 0

    for idx, fields in instances.items():
        if not fields:
            continue
        first_fld = next(iter(fields.values()))
        if first_fld.class_name != "app.cCameraParamData_AppDefault":
            continue
        appdefault_count += 1

        instance_base = _infer_instance_base(
            idx, "app.cCameraParamData_AppDefault", camera_layout
        )

        # 读取 _IsRide 进行骑乘判定
        is_ride_candidates = instances_multi.get(idx, {}).get("_IsRide", [])
        is_ride_expected = camera_layout.get("_IsRide", [])
        is_ride_pref = _pick_by_expected_offset(
            is_ride_candidates, is_ride_expected, instance_base
        )
        is_ride = False
        has_ride_candidate = bool(is_ride_candidates)
        if has_ride_candidate:
            ride_candidate_instances += 1
        for is_ride_fld in (
            [is_ride_pref] + is_ride_candidates if is_ride_pref else is_ride_candidates
        ):
            if is_ride_fld is None:
                continue
            v = _safe_read_u8(is_ride_fld)
            if v == 1:
                is_ride = True
                break
        if is_ride:
            ride_count += 1

        target_idx = None
        # 通过 _CameraParamArgument 指针读取具体相机参数实例 (cCameraParamArgThirdPerson)
        arg_candidates = instances_multi.get(idx, {}).get("_CameraParamArgument", [])
        arg_expected = camera_layout.get("_CameraParamArgument", [])
        arg_pref = _pick_by_expected_offset(arg_candidates, arg_expected, instance_base)
        arg_iter = [arg_pref] + arg_candidates if arg_pref else arg_candidates
        for arg_ptr_fld in arg_iter:
            if arg_ptr_fld is None:
                continue
            if arg_ptr_fld.field_type not in ("Object", "UserData"):
                continue
            ptr = _safe_read_i32(arg_ptr_fld)
            if ptr is None or ptr <= 0:
                continue
            if ptr not in instances:
                continue
            target_fields = instances[ptr]
            if not target_fields:
                continue
            target_first = next(iter(target_fields.values()))
            if target_first.class_name == "app.cCameraParamArgThirdPerson":
                target_idx = ptr
                break

        if not target_idx or target_idx not in instances:
            continue
        arg_resolved_count += 1

        target_base = _infer_instance_base(
            target_idx, "app.cCameraParamArgThirdPerson", third_person_layout
        )
        target_fields_multi = instances_multi.get(target_idx, {})

        # 寻找 AttachOfs，它是个 Vec3，所以内部只有 [0], [1], [2]
        has_readable_attach = False
        for arr_i in range(3):
            ofs_candidates = target_fields_multi.get(
                f"AttachOfs[{arr_i}]", []
            ) + target_fields_multi.get(f"_AttachOfs[{arr_i}]", [])
            if not ofs_candidates:
                continue
            attach_field_count += 1
            ofs_expected = third_person_layout.get(f"AttachOfs[{arr_i}]", [])
            ofs_fld = _pick_by_expected_offset(
                ofs_candidates, ofs_expected, target_base
            )

            if ofs_fld:
                old_val = _safe_read_f32(ofs_fld)
                if old_val is None:
                    continue
                attach_readable_count += 1
                has_readable_attach = True
                if old_val != 0:
                    new_val = round(old_val * scale_ratio, 4)
                else:
                    new_val = 0.0

                if not dry_run:
                    ofs_fld.write_f32(parser.buf, new_val)

                patched_any = True
                print(
                    f"  PATCH CAM [{ofs_fld.instance_idx}].AttachOfs[{arr_i}]  "
                    f"(F32 @ {ofs_fld.byte_offset:#010x})  {old_val:.6g} → {new_val:.6g}"
                    + ("  [DRY RUN]" if dry_run else "")
                )

    # 兜底路径：若通过 CameraParamData -> Argument 指针链未命中，
    # 直接对文件内所有 ThirdPerson 参数实例执行 AttachOfs 修改。
    if not patched_any:
        for idx, fields in instances.items():
            if not fields:
                continue
            first_fld = next(iter(fields.values()))
            if first_fld.class_name != "app.cCameraParamArgThirdPerson":
                continue

            target_base = _infer_instance_base(
                idx, "app.cCameraParamArgThirdPerson", third_person_layout
            )
            target_fields_multi = instances_multi.get(idx, {})
            patched_this_instance = False
            for arr_i in range(3):
                ofs_candidates = target_fields_multi.get(
                    f"AttachOfs[{arr_i}]", []
                ) + target_fields_multi.get(f"_AttachOfs[{arr_i}]", [])
                if not ofs_candidates:
                    continue
                attach_field_count += 1
                ofs_expected = third_person_layout.get(f"AttachOfs[{arr_i}]", [])
                ofs_fld = _pick_by_expected_offset(
                    ofs_candidates, ofs_expected, target_base
                )
                if not ofs_fld:
                    continue
                old_val = _safe_read_f32(ofs_fld)
                if old_val is None:
                    continue
                attach_readable_count += 1
                if old_val != 0:
                    new_val = round(old_val * scale_ratio, 4)
                else:
                    new_val = 0.0
                if not dry_run:
                    ofs_fld.write_f32(parser.buf, new_val)
                patched_any = True
                patched_this_instance = True
                print(
                    f"  PATCH CAMF [{ofs_fld.instance_idx}].AttachOfs[{arr_i}]  "
                    f"(F32 @ {ofs_fld.byte_offset:#010x})  {old_val:.6g} → {new_val:.6g}"
                    + ("  [DRY RUN]" if dry_run else "")
                )
            if patched_this_instance:
                fallback_thirdperson_count += 1

    if patched_any and not dry_run:
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        dst_path.write_bytes(bytes(parser.buf))

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
        return PatchResult(
            "no_match",
            "存在 CameraParamData，但 _IsRide 读值全非1（可能偏移未完全对齐）",
        )
    if arg_resolved_count == 0:
        return PatchResult(
            "no_match", "Ride 条目存在，但未解析到有效 _CameraParamArgument"
        )
    if attach_field_count == 0:
        return PatchResult("no_match", "已解析到 ThirdPerson，但未找到 AttachOfs 字段")
    if attach_readable_count == 0:
        return PatchResult("no_match", "AttachOfs 存在，但值越界或不可读")
    return PatchResult("no_match", "未命中可修改的 AttachOfs")


# ─── 扫描入口 ──────────────────────────────────────────────────────────────────
def scan_and_patch(
    natives_dir: Path,
    output_dir: Path,
    typedb: TypeDB,
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

    # 找出所有以 Ot 开头的子目录（忽略 CommonData 等公共目录）
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

        # 递归匹配所有 **/CommonData/*_BasicParam.user.3
        param_files = sorted(
            p
            for p in ot_dir.rglob("*_BasicParam.user.3")
            if p.parent.name == "CommonData"
        )

        # 递归匹配所有 **/CameraData/WOt*_CameraParam.user.3
        camera_files = sorted(
            p
            for p in ot_dir.rglob("WOt*_CameraParam.user.3")
            if p.parent.name == "CameraData"
        )
        # 为相机计算“新体型/原始体型”比值：按同一变体目录（如 00/01/02/XX）匹配 BasicParam。
        original_scale_by_variant: dict[Path, float] = {}
        for basic_path in param_files:
            variant = basic_path.parent.parent.relative_to(ot_dir)
            original = read_body_scale(basic_path, typedb)
            if original is not None and variant not in original_scale_by_variant:
                original_scale_by_variant[variant] = original

        if not param_files and not camera_files:
            skipped += 1
            continue

        for src_path in param_files:
            # 显示相对于 Ot* 目录的路径，便于识别是哪个变体（00/01/02/XX 等）
            rel_display = src_path.relative_to(ot_dir)
            # 输出保持 natives/ 以下完整相对路径
            rel = src_path.relative_to(natives_dir)
            dst_path = output_dir / "natives" / rel

            print(f"[{ot_dir.name}]  {rel_display}")
            result = patch_body_scale(
                src_path, dst_path, typedb, current_scale, dry_run
            )
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
                typedb,
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

    print(f"\n{'─'*60}")
    print(
        f"完成  处理: {processed}  跳过目录: {skipped}  "
        f"BodyScale未命中: {body_nomatch}  Camera未命中: {cam_nomatch}  错误: {errors}"
    )
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
        "--rsz",
        "--schema",
        dest="schema",
        default=str(auto_schema) if auto_schema else None,
        metavar="RSZ_JSON",
        help=(
            "rszmhst3.json（RSZ 类型模板）路径"
            + (
                f"（自动找到: {auto_schema}）"
                if auto_schema
                else "（未自动找到，需手动指定）"
            )
        ),
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
    ap.add_argument(
        "--il2cpp-map",
        type=str,
        default="",
        help="IL2CPP 子集 JSON 路径，用于修复类型数据库的基类继承字段（可选）",
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

    il2cpp_map = None
    if args.il2cpp_map:
        il2cpp_path = Path(args.il2cpp_map)
        if il2cpp_path.exists():
            print(f"加载 IL2CPP 继承树 : {il2cpp_path}")
            with open(il2cpp_path, "r", encoding="utf-8") as f:
                il2cpp_map = json.load(f)
        else:
            print(f"警告：找不到指定的 il2cpp map 文件 {il2cpp_path}")

    print()

    typedb = TypeDB.load(schema_path, il2cpp_map)
    scan_and_patch(
        natives_dir,
        output_dir,
        typedb,
        args.scale,
        args.dry_run,
        args.apply_enemy_scale,
        args.json_dir,
    )


if __name__ == "__main__":
    main()
