# dsh-kicad-preset

A KiCad 10 schematic/PCB agent preset for **DeepSeek Harness (DSH)**, built on the **Konnect MCP** server. It adds a `kicad` agent mode, a schematic-hardening skill for the failure modes found in a real 10-page RK3588 board, and read-only clearance/geometry scripts.

> English summary: a DSH agent preset for KiCad 10 + Konnect MCP. It bundles a `kicad` preset, the `kicad-schematic-hardening` skill, and read-only schematic QA scripts. Tested with DSH `0.2.1-rc.2`, KiCad `10.0.7`, and Konnect `0.13.0`.

## 目录结构

```text
dsh-kicad-preset/
  cordis.patch.yml                  # DSH bundle patch: preset declaration + MCP config
  package.json
  README.md
  LICENSE
  skills/
    kicad-schematic-hardening/
      SKILL.md                      # hard rules, batch loop, completion triangle
      reference/PITFALLS.md         # full case study (GUI overwrite, netlist gates, tool gaps)
      scripts/
        sch_clearance_check.py      # preferred 1.0 mm text/component clearance gate
        overlap_check.py            # legacy SVG overlap checker
        probe.py / sch_region.py / fields_dump.py / free_space.py / crop_region.py
        efoo2kicad.py / efoo_scale.py / efoo_inspect.py
        README.md
```

## 前置条件

- DSH 0.2.x（已在 `@deepseek-ai/dsh-*` `0.2.1-rc.2` 上测试）
- KiCad 10.0.x（已在 10.0.7 上测试）
- Konnect 0.13+，通过 KiCad 的 Plugin & Content Manager 安装；`konnect` 在 `PATH` 中
- 以下外部技能（**不包含在本包内**，由 Konnect 安装器或你自己的技能目录提供）：
  `konnect`、`kicad-schematic`、`kicad-pcb`、`kicad-library`、`kicad-review`、`kicad-manufacture`
- 原理图批量编辑时 **KiCad GUI 必须关闭**；PCB 布局/布线时才需要打开 KiCad 和目标板，并启用 `Preferences > Plugins > KiCad API`

## 安装

### 1. 安装预设

从本地克隆（或下载 zip）后，在 DSH 中让代理执行：

```text
plugin_manager install_bundle target="<path-to>/dsh-kicad-preset"
```

`plugin_manager` 需要 Full access 或用户批准。

### 2. 安装硬化技能（必需）

预设 persona 会加载 `kicad-schematic-hardening`。把包内的技能复制到**项目级**或**用户级**技能目录：

```powershell
# 项目级：只对当前工程生效
New-Item -ItemType Directory -Force "<project>\.agents\skills" | Out-Null
Copy-Item -Recurse ".\skills\kicad-schematic-hardening" "<project>\.agents\skills\"

# 或用户级：所有工程生效
New-Item -ItemType Directory -Force "$HOME\.agents\skills" | Out-Null
Copy-Item -Recurse ".\skills\kicad-schematic-hardening" "$HOME\.agents\skills\"
```

也可以把 `skills` 的父目录加入 `@deepseek-ai/dsh-skill-filesystem` 的 `customSkillDirs`。

### 3. 配置 Konnect

包内 `cordis.patch.yml` 默认 `command: konnect`。如果 `konnect` 不在 `PATH`，改成完整路径（Windows PCM 安装通常为）：

```text
C:/Users/<you>/Documents/KiCad/10.0/3rdparty/plugins/com_github_mixelpixx_konnect/bin/konnect.exe
```

如果 PCB IPC 找不到 KiCad，取消 `cordis.patch.yml` 中的注释并填入实际 socket：

```yaml
env:
  KICAD_API_SOCKET: 'ipc:///tmp/kicad/api.sock'   # Windows 示例：ipc://C:/Users/<you>/AppData/Local/Temp/kicad/api.sock
```

修改 `PATH` 或全局环境变量后需要重启 DSH，MCP 子进程才会继承新环境。

## 使用

1. 新建会话（已有会话不会切换预设）。
2. 选择 **KiCad 硬件设计**。
3. 原理图工作先让代理加载 `konnect`，再加载 `kicad-schematic-hardening`；PCB 工作加载 `kicad-pcb`。
4. 示例提示词：

   `打开工程，先加载 konnect 和 kicad-schematic-hardening，检查 GUI 是否关闭，然后按门禁做 5_RS485 页的重排。`

## 四条硬门禁

1. **MCP 改原理图时 KiCad GUI 必须关闭。** 运行中的 GUI 会用内存旧快照无提示地重写全部 sheet。出现多个 `.kicad_sch` 同秒 mtime、wires 计数下降或新 `.lck`，立即停工。
2. **连通性终判只认 `kicad-cli sch export netlist`。** `ERC error=0` 不等于电气正确；完成 = 网表 + 结构 + 间隙三角。
3. **电源符号只落导线/引脚端点；跨页信号只用 `global_label` 或 hierarchical label + sheet pin。** EasyEDA 导入后归一化引脚电气类型，并核对订货后缀对应的封装。
4. **批量改动前后做网表 diff。** 纯外观改动要求逐字节一致；去标签/实线化要求每个网络的成员集合不变。

详细案例、Konnect 工具缺口和量化基线见
`skills/kicad-schematic-hardening/reference/PITFALLS.md`。

> 注意：外部 `kicad-library` 技能若仍给出相对 `--output`，以本包硬化技能的绝对路径规则为准；相对路径加 `--project-relative` 会报 `ValueError: not in the subpath`。

## 只读检查脚本

首选零依赖、直接解析 `.kicad_sch` 的间隙门禁：

```text
python skills/kicad-schematic-hardening/scripts/sch_clearance_check.py --sch <sheet>.kicad_sch --clear 1.0 --md report.md --json report.json
```

退出码 0/1，可直接做每页门禁。`overlap_check.py` 是早期 SVG 工具，已知会因
`lib_symbols` 图形文字产生假阳性，只作第二意见。其余区域/字段/空闲位/裁剪
脚本见 `skills/kicad-schematic-hardening/scripts/README.md`。

## 发布

### GitHub

先把本目录复制到硬件工程之外，不要把 RK3588 设计文件一起提交：

```powershell
git init
git add .
git commit -m "feat: KiCad 10 agent preset with schematic hardening"
git branch -M main
git remote add origin https://github.com/<you>/dsh-kicad-preset.git
git push -u origin main
```

或使用 GitHub CLI：

```powershell
gh repo create dsh-kicad-preset --public --source . --remote origin --push
```

### npm

```powershell
npm pkg set name="@your-scope/dsh-kicad-preset"
npm login
npm publish --access public
```

非 scope 名 `dsh-kicad-preset` 可能已被占用，建议使用自己的 scope。安装 npm 包后，
仍需要把包内的 `skills/kicad-schematic-hardening` 复制到技能目录。

## 许可

MIT，见 [LICENSE](LICENSE)。
