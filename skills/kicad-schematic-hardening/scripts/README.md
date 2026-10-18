# 原理图只读检查脚本

这些脚本只读解析 `.kicad_sch` 或已导出的 SVG，**不会写任何 `.kicad_*` 文件**。
建议使用 DSH 工作区 Python（`load_workspace_dependencies` 返回的 `python`），
并让当前目录保持在 `.kicad_pro` 所在工程目录。

## 首选：文字/元件间隙检查

零依赖，直接解析原理图源文件，覆盖标签、`#PWR` 轨名、自由文本、位号/值、
元件本体和引脚号。1.0 mm 间隙门禁：

```text
python scripts/sch_clearance_check.py --sch <sheet>.kicad_sch --clear 1.0 --md <report>.md --json <report>.json
```

- 退出码 `0` = 无冲突，`1` = 存在冲突，可直接做 CI/批量门禁。
- `--no-wires` 只查文字，忽略导线穿字。
- 每页单独跑；10 页工程逐页跑完再汇总。

## 历史对照：SVG 重叠检查

基于 `kicad-cli sch export svg` 生成的不可见 `<text>` 层。**已知会因
`lib_symbols` 图形文字产生假阳性**，只作第二意见，不作为首选门禁。

```text
python scripts/overlap_check.py --export --schematic <root>.kicad_sch --svg-dir <svg_dir> --kicad-cli <kicad-cli> --lib <project_dir> --md <report>.md --json <report>.json
```

- `kicad-cli` 不在 PATH 时，用 `--kicad-cli` 或环境变量 `KICAD_CLI`。
- `--lib` 指向包含 `.kicad_sym` 的工程目录，用于排除引脚名；找不到时会警告。
- `--min-overlap` 默认 0.30 mm；`--include-pin-text` 才把引脚名/号纳入比较。
- 退出码 `0/1`。

## 区域/字段/空闲位查询

```text
# 列出区域内的标签/导线/结点/文字/元件
python scripts/sch_region.py <sheet>.kicad_sch --x0 0 --y0 0 --x1 100 --y1 100

# 逐符号导出 Reference / Value 坐标
python scripts/fields_dump.py <sheet>.kicad_sch [--ref R160] [--region x0,y0,x1,y1]

# SVG 文本盒探查：texts / fields / labels / wires / syms / raw
python scripts/probe.py syms --sch <sheet>.kicad_sch --near 71.12,40.64 --r 20

# 在 SVG 文本盒中找空闲落点
python scripts/free_space.py --svg <sheet>.svg --w 4 --h 1.7 --x0 100 --y0 34 --x1 120 --y1 48 --top 12
```

`probe.py` 和 `free_space.py` 依赖同目录的 `overlap_check.py`，三者必须放在一起。

## 渲染图裁剪

```text
python scripts/crop_region.py <page>.png <x0> <y0> <x1> <y1> <out.png> --page-w 419.9890 --page-h 297.0022 --scale 2
```

按 KiCad 页面 mm 坐标裁剪；A2/A3 混排时按页传 `--page-w/--page-h`。
需要 Pillow。

## EasyEDA Pro `.efoo` 转换

```text
python scripts/efoo_inspect.py <file.efoo>          # 先看记录类型
python scripts/efoo_scale.py <file.efoo>            # 反推 mm/unit
python scripts/efoo2kicad.py <file.efoo> --output <name>.kicad_mod
```

`efoo2kicad.py` 默认 0.0254 mm/unit（1 mil），转换后必须核对焊盘尺寸、间距、
1 脚标记和外框；不要直接把未核对的封装放进工程。

## EasyEDA/LCSC 符号与封装

`easyeda2kicad` 的 `--output` 必须是**绝对路径**；相对路径加
`--project-relative` 会报 `ValueError: not in the subpath`。生成后必须核对
订货后缀对应的封装（例如 `THVD1450DR` 是 SOIC-8，不是 VSON-8）以及引脚
电气类型。

## 目录约定

- `exports/` 只放交付件，固定命名并只保留最新版；
- 一次性脚本进 `tools/` 或 `tmp/`；
- 中间快照进 `tmp/`，不要混入 `exports/`。
