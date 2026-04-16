import argparse
import json
import re
import time
from collections import deque
from pathlib import Path

_ROOT_STOP_TYPES = {
    "",
    "System.Object",
    "System.ValueType",
    "via.UserData",
    "via.ManagedObject",
}


def _normalize_type_name(name: object) -> str:
    if not isinstance(name, str):
        return ""
    s = name.strip()
    if not s:
        return ""

    # 常见 il2cpp dump 会带 assembly 附加信息，去掉后与 rsz 名称对齐。
    s = re.sub(r",\s*application,.*$", "", s)
    s = re.sub(r",\s*Assembly-CSharp,.*$", "", s)
    s = re.sub(r",\s*mscorlib,.*$", "", s)
    return s.strip()


def _iter_class_dicts(data: object) -> list[dict]:
    if isinstance(data, dict):
        if isinstance(data.get("Classes"), list):
            return [x for x in data["Classes"] if isinstance(x, dict)]
        if isinstance(data.get("classes"), list):
            return [x for x in data["classes"] if isinstance(x, dict)]

        out: list[dict] = []
        for k, v in data.items():
            if isinstance(v, dict):
                node = dict(v)
                node.setdefault("__key_name", k)
                out.append(node)
        return out

    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]

    return []


def _extract_names(cls: dict) -> list[str]:
    names: list[str] = []
    for k in (
        "__key_name",
        "__extracted_name",
        "name",
        "Name",
        "FullName",
        "full_name",
    ):
        v = _normalize_type_name(cls.get(k))
        if v:
            names.append(v)

    ns = _normalize_type_name(cls.get("namespace") or cls.get("Namespace"))
    short = _normalize_type_name(cls.get("name") or cls.get("Name"))
    if ns and short and "." not in short:
        names.append(f"{ns}.{short}")

    hier = cls.get("name_hierarchy")
    if isinstance(hier, list):
        clean = [_normalize_type_name(x) for x in hier if _normalize_type_name(x)]
        if clean:
            names.append(clean[-1])
            if len(clean) >= 2 and "." not in clean[-1]:
                names.append(".".join(clean[-2:]))

    seen = set()
    uniq: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            uniq.append(n)
    return uniq


def _extract_parent_name(cls: dict) -> str:
    parent = (
        cls.get("parent")
        or cls.get("Parent")
        or cls.get("Base")
        or cls.get("BaseClass")
        or cls.get("base")
    )
    if isinstance(parent, dict):
        parent = parent.get("name") or parent.get("Name") or parent.get("FullName")

    p = _normalize_type_name(parent)
    if p:
        return p

    hier = cls.get("name_hierarchy")
    if isinstance(hier, list):
        clean = [_normalize_type_name(x) for x in hier if _normalize_type_name(x)]
        if len(clean) >= 2:
            return clean[-2]
    return ""


def _load_rsz_class_names(rsz_path: Path) -> set[str]:
    with rsz_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    names: set[str] = set()
    if isinstance(data, dict):
        for value in data.values():
            if not isinstance(value, dict):
                continue
            n = _normalize_type_name(value.get("name"))
            if n:
                names.add(n)
    return names


def _build_full_hierarchy(
    class_dicts: list[dict],
    progress_every: int = 0,
    log_fn=None,
) -> dict[str, str]:
    hierarchy: dict[str, str] = {}
    total = len(class_dicts)
    for i, cls in enumerate(class_dicts, start=1):
        names = _extract_names(cls)
        if not names:
            if progress_every > 0 and i % progress_every == 0 and log_fn:
                log_fn(
                    f"Building hierarchy: {i}/{total} "
                    f"({(i / total * 100) if total else 0:.1f}%)"
                )
            continue
        parent = _extract_parent_name(cls)
        if not parent or parent in _ROOT_STOP_TYPES:
            if progress_every > 0 and i % progress_every == 0 and log_fn:
                log_fn(
                    f"Building hierarchy: {i}/{total} "
                    f"({(i / total * 100) if total else 0:.1f}%)"
                )
            continue
        for child in names:
            if child == parent:
                continue
            # 优先保留第一个稳定结果，避免被格式较差的别名覆盖。
            hierarchy.setdefault(child, parent)
        if progress_every > 0 and i % progress_every == 0 and log_fn:
            log_fn(
                f"Building hierarchy: {i}/{total} "
                f"({(i / total * 100) if total else 0:.1f}%)"
            )
    return hierarchy


def _build_shortname_index(full_hierarchy: dict[str, str]) -> dict[str, list[str]]:
    idx: dict[str, list[str]] = {}
    for full_name in full_hierarchy:
        short = full_name.rsplit(".", 1)[-1]
        idx.setdefault(short, []).append(full_name)
    return idx


def _resolve_seed(
    name: str,
    full_hierarchy: dict[str, str],
    shortname_index: dict[str, list[str]],
) -> str | None:
    if name in full_hierarchy:
        return name
    # 兜底：某些 dump 只有短名，按末段匹配唯一候选。
    short = name.rsplit(".", 1)[-1]
    candidates = shortname_index.get(short, [])
    if len(candidates) == 1:
        return candidates[0]
    return None


def _build_subset(
    full_hierarchy: dict[str, str],
    seeds: set[str],
    progress_every: int = 0,
    log_fn=None,
) -> tuple[dict[str, str], set[str]]:
    subset: dict[str, str] = {}
    unresolved: set[str] = set()
    q: deque[str] = deque()
    visited: set[str] = set()
    shortname_index = _build_shortname_index(full_hierarchy)

    sorted_seeds = sorted(seeds)
    total_seeds = len(sorted_seeds)
    for i, seed in enumerate(sorted_seeds, start=1):
        resolved = _resolve_seed(seed, full_hierarchy, shortname_index)
        if resolved is None:
            unresolved.add(seed)
        else:
            q.append(resolved)
        if progress_every > 0 and i % progress_every == 0 and log_fn:
            log_fn(
                f"Resolving seed roots: {i}/{total_seeds} "
                f"({(i / total_seeds * 100) if total_seeds else 0:.1f}%), "
                f"queue={len(q)}, unresolved={len(unresolved)}"
            )

    processed = 0
    while q:
        c = q.popleft()
        processed += 1
        if c in visited:
            if progress_every > 0 and processed % progress_every == 0 and log_fn:
                log_fn(
                    f"Resolving subset closure: queue_processed={processed}, "
                    f"visited={len(visited)}, subset={len(subset)}"
                )
            continue
        visited.add(c)
        p = full_hierarchy.get(c)
        if not p or p in _ROOT_STOP_TYPES or p == c:
            if progress_every > 0 and processed % progress_every == 0 and log_fn:
                log_fn(
                    f"Resolving subset closure: queue_processed={processed}, "
                    f"visited={len(visited)}, subset={len(subset)}"
                )
            continue
        subset[c] = p
        if p in full_hierarchy and p not in visited:
            q.append(p)
        if progress_every > 0 and processed % progress_every == 0 and log_fn:
            log_fn(
                f"Resolving subset closure: queue_processed={processed}, "
                f"visited={len(visited)}, subset={len(subset)}"
            )
    return subset, unresolved


def main() -> None:
    ap = argparse.ArgumentParser(
        description="从 il2cpp_dump 提取 rsz 相关最小继承闭包",
    )
    ap.add_argument(
        "--dump", default="src/data/il2cpp_dump.json", help="完整 il2cpp dump JSON"
    )
    ap.add_argument("--rsz", default="src/data/rszmhst3.json", help="RSZ 类型定义 JSON")
    ap.add_argument(
        "--out", default="src/data/il2cpp_subset.json", help="输出子集 JSON"
    )
    ap.add_argument(
        "--progress-every",
        type=int,
        default=2000,
        help="每处理多少条记录打印一次进度（0 表示关闭）",
    )
    args = ap.parse_args()

    dump_path = Path(args.dump)
    rsz_path = Path(args.rsz)
    out_path = Path(args.out)
    t0 = time.perf_counter()

    def log(msg: str) -> None:
        elapsed = time.perf_counter() - t0
        print(f"[{elapsed:7.1f}s] {msg}", flush=True)

    if not dump_path.exists():
        log(f"[ERROR] 文件不存在: {dump_path}")
        return
    if not rsz_path.exists():
        log(f"[ERROR] 文件不存在: {rsz_path}")
        return

    log(f"Loading dump: {dump_path}")
    try:
        with dump_path.open("r", encoding="utf-8") as f:
            dump_data = json.load(f)
    except Exception as e:
        log(f"[ERROR] 读取 dump 失败: {e}")
        return
    log("Dump loaded.")

    log(f"Loading rsz: {rsz_path}")
    try:
        rsz_names = _load_rsz_class_names(rsz_path)
    except Exception as e:
        log(f"[ERROR] 读取 rsz 失败: {e}")
        return
    log(f"RSZ loaded, roots={len(rsz_names)}")

    log("Normalizing class nodes from dump...")
    classes = _iter_class_dicts(dump_data)
    log(f"Class nodes normalized: {len(classes)}")

    log("Building full hierarchy...")
    full_hierarchy = _build_full_hierarchy(
        classes,
        progress_every=max(0, args.progress_every),
        log_fn=log,
    )
    log(f"Full hierarchy built: {len(full_hierarchy)}")

    log("Resolving rsz-rooted subset closure...")
    subset, unresolved = _build_subset(
        full_hierarchy,
        rsz_names,
        progress_every=max(0, args.progress_every),
        log_fn=log,
    )
    log(f"Subset resolved: {len(subset)}, unresolved_roots={len(unresolved)}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    log(f"Writing subset JSON: {out_path}")
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(dict(sorted(subset.items())), f, indent=2, ensure_ascii=False)
    log("Subset JSON written.")

    log(f"dump class nodes     : {len(classes)}")
    log(f"full hierarchy size : {len(full_hierarchy)}")
    log(f"rsz class roots     : {len(rsz_names)}")
    log(f"subset size         : {len(subset)}")
    log(f"unresolved roots    : {len(unresolved)}")
    if unresolved:
        preview = sorted(unresolved)[:20]
        log("unresolved sample:")
        for n in preview:
            log(f"  - {n}")

    size_kb = out_path.stat().st_size / 1024
    log(f"Saved: {out_path} ({size_kb:.2f} KB)")

    for key in ("app.cCameraParamData_AppDefault", "app.cCameraParamArgThirdPerson"):
        if key in subset:
            log(f"[OK] {key} -> {subset[key]}")
        elif key in full_hierarchy:
            log(f"[WARN] {key} 在 full hierarchy 中存在但未进入 subset")
        else:
            log(f"[WARN] {key} 在 dump 中未找到")


if __name__ == "__main__":
    main()
