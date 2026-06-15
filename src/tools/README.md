# build data 工具说明

这个目录里的工具用于处理不适合提交到 Git 仓库的大型构建数据。
当前默认处理的文件是：

```text
src/data/il2cpp_dump.json
```

工具会把它压缩成 GitHub Release asset：

```text
il2cpp_dump.json.gz
il2cpp_dump.json.gz.sha256
```

默认上传到当前仓库的 `build-data` release。后续 GitHub Action 构建时会自动下载、校验并解压回 `src/data/il2cpp_dump.json`。

## 前置要求

本地上传需要安装并登录 GitHub CLI：

```powershell
gh auth login
```

GitHub Action 中已经有 `gh`，workflow 会通过自动创建的 `secrets.GITHUB_TOKEN` 设置 `GH_TOKEN`。这个 token 不需要手动配置。

## 本地上传 build data

在仓库根目录运行：

```powershell
python src/tools/build_data.py upload
```

这个命令会：

1. 读取 `src/data/il2cpp_dump.json`
2. 压缩为 `il2cpp_dump.json.gz`
3. 生成 `il2cpp_dump.json.gz.sha256`
4. 创建或更新 `build-data` release，并写入中英双语说明，标注普通用户无需下载
5. 用 `--clobber` 覆盖上传这两个 asset

只检查流程、不上传：

```powershell
python src/tools/build_data.py upload --dry-run
```

默认使用最大 gzip 压缩等级 9。如果想临时指定压缩等级：

```powershell
python src/tools/build_data.py upload --compresslevel 9
```

## 本地下载测试

如果想在本地模拟 Action 下载：

```powershell
python src/tools/build_data.py download
```

这个命令会：

1. 从 `build-data` release 下载 `il2cpp_dump.json.gz`
2. 下载 `il2cpp_dump.json.gz.sha256`
3. 校验 sha256
4. 解压到 `src/data/il2cpp_dump.json`

下载的中间文件默认放在：

```text
.temp/build_data
```

## GitHub Action 中的用法

workflow 中只需要在构建前调用：

```yaml
- name: Download build data
  run: python src/tools/build_data.py download
```

脚本会优先读取 Action 自动提供的 `GITHUB_REPOSITORY`，所以一般不需要写死仓库地址。

## 迁移到其他仓库

默认情况下不需要改代码。脚本会按下面顺序自动识别仓库：

1. 命令行参数 `--repo owner/name`
2. 环境变量 `GITHUB_REPOSITORY`
3. `git remote.origin.url`
4. `gh repo view`

如果需要手动指定仓库：

```powershell
python src/tools/build_data.py upload --repo owner/name
python src/tools/build_data.py download --repo owner/name
```

如果需要换 release tag：

```powershell
python src/tools/build_data.py upload --tag build-data
python src/tools/build_data.py download --tag build-data
```

如果 dump 文件路径不同：

```powershell
python src/tools/build_data.py upload --dump path/to/il2cpp_dump.json
python src/tools/build_data.py download --output path/to/il2cpp_dump.json
```

如果 asset 名想保持固定但输出路径不同：

```powershell
python src/tools/build_data.py download --output path/to/il2cpp_dump.json --asset il2cpp_dump.json.gz
```

## 注意事项

- `src/data/il2cpp_dump.json` 应继续放在 `.gitignore` 中，不要提交到普通 Git。
- 每次资源更新后重新运行 `upload` 即可，release asset 会覆盖更新。
- checksum 是针对压缩后的 `il2cpp_dump.json.gz` 计算的，Action 会先校验再解压。
- 这个目录只保留 `build_data.py` 这一套入口，上传和下载都通过它完成。
