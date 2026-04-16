import json
import shutil
import subprocess
import tempfile
from pathlib import Path
import sys


def main():
    root_dir = Path(__file__).resolve().parent.parent

    # 1. Read version
    version_file = root_dir / "src" / "data" / "user_version.json"
    mod_version = "v1.0.0-debug"
    if version_file.exists():
        try:
            with open(version_file, "r", encoding="utf-8") as f:
                version_data = json.load(f)
            mod_version = version_data.get("mod_version", mod_version)
        except Exception as e:
            print(f"[!] 读取版本文件失败: {e}")

    print(f"[*] Build version: {mod_version}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        # ─── 2. Build Normal ───
        out_normal = tmp_dir / "user3_output"
        out_normal.mkdir(parents=True, exist_ok=True)

        print("\n[*] 正在运行 Normal 版本构建...")
        try:
            cmd_normal = [
                sys.executable,
                str(root_dir / "src" / "normal_otomon_body_scale.py"),
                "--rsz",
                str(root_dir / "src" / "data" / "rszmhst3.json"),
                "--natives",
                str(root_dir / "src" / "data" / "unpak" / "natives"),
                "--output",
                str(out_normal),
                "--scale",
                "1.0",
            ]
            if (root_dir / "src" / "data" / "il2cpp_subset.json").exists():
                cmd_normal.extend(["--il2cpp-map", str(root_dir / "src" / "data" / "il2cpp_subset.json")])
            
            subprocess.run(
                cmd_normal,
                check=True,
                cwd=str(root_dir),
            )
        except subprocess.CalledProcessError as e:
            print(f"[!] Normal 构建失败: {e}")
            sys.exit(1)

        # Zip normal
        zip_normal_name = f"NormalOtomonScale_{mod_version}"
        zip_normal_path = root_dir / zip_normal_name
        shutil.make_archive(str(zip_normal_path), "zip", out_normal)
        print(f"[+] 成功创建: {zip_normal_path}.zip")

        # ─── 3. Build Enemy Size ───
        out_enemy = tmp_dir / "user3_with_enemy_size_output"
        out_enemy.mkdir(parents=True, exist_ok=True)

        print("\n[*] 正在运行 With Enemy Size 版本构建...")
        try:
            cmd_enemy = [
                sys.executable,
                str(root_dir / "src" / "normal_otomon_body_scale.py"),
                "--rsz",
                str(root_dir / "src" / "data" / "rszmhst3.json"),
                "--natives",
                str(root_dir / "src" / "data" / "unpak" / "natives"),
                "--output",
                str(out_enemy),
                "--scale",
                "1.0",
                "--apply-enemy-scale",
                "--json-dir",
                str(root_dir / "src" / "data" / "json"),
            ]
            if (root_dir / "src" / "data" / "il2cpp_subset.json").exists():
                cmd_enemy.extend(["--il2cpp-map", str(root_dir / "src" / "data" / "il2cpp_subset.json")])
            
            subprocess.run(
                cmd_enemy,
                check=True,
                cwd=str(root_dir),
            )
        except subprocess.CalledProcessError as e:
            print(f"[!] Enemy Size 构建失败: {e}")
            sys.exit(1)

        # Zip enemy
        zip_enemy_name = f"NormalOtomonScale_with_enemy_size_{mod_version}"
        zip_enemy_path = root_dir / zip_enemy_name
        shutil.make_archive(str(zip_enemy_path), "zip", out_enemy)
        print(f"[+] 成功创建: {zip_enemy_path}.zip")

    print("\n[*] 构建流程完成，生成的压缩包已存放于项目根目录！")


if __name__ == "__main__":
    main()
