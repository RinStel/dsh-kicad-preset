# KiCad 预设设计参考：X1_RK3588 底板原理图任务的问题与工具沉淀

> 来源：2026-10-18 一次完整的「RK3588 通用底板原理图」任务（10 页、255 元件、597 网络）。
> 目的：供设计/改进 KiCad 预设模式的 Agent 参考——这里记录的是**踩过的坑、工具缺口、以及可复用脚本**，不是工程本身的交付说明。
> 工程路径：`<project>\KiCad_RK3588_Baseboard\`（目录与文件名已全部英文化）

---

## 一、结论先行：预设里最该加的 8 条硬规则

1. **做 MCP 原理图修改时，工程绝不能被 KiCad GUI 打开。** 见第 2 节——这是本次最昂贵的一条，GUI 会用内存旧快照整工程覆盖写盘。
2. **连通性判定只认 `kicad-cli` 导出的网表**，不要用 Konnect 的 `get_pin_net_name` / `get_component_nets` 作终判。
3. **电源符号只能落在导线端点或引脚端点上**，禁止落在导线中段靠自动 junction。
4. **跨页信号必须 `global_label`（或 hierarchical label + sheet pin）**，绝不用同名 `local label` 冒充。
5. **EasyEDA 导入后必须做引脚电气类型归一化**，否则 ERC 会出现数百条 `pin_to_pin` / `pin_not_driven`。
6. **每次批量改动前后都做网表 diff**，把它当回归门禁，而不是只看 ERC。
7. **中文路径/文件名先行英文化**，否则沙箱与 Python 工具链都会失效。
8. **布局先行：先重排、再实线直连、最后才删标签。** 反过来做（先删标签再挪元件）只会反复返工。

---

## 一之二、最严重的坑：KiCad GUI 整盘覆盖（务必写进预设）

**现象**：某时刻 **10 个 `.kicad_sch` 在同一秒被全部重写**（本次为 `12:36:08`），而 MCP 每次只写一个 sheet——多文件同秒 mtime 就是铁证。写回的是 GUI **内存里的旧快照**，比磁盘还旧（本次 1_Power 被写回 206 wires / 39 junctions，而磁盘是 208/43）。

**后果**（本次全部发生过）：
- 数十处正确修改被静默抹掉（`split_wire_at_point` 结果、新增引出线、标签位移）；
- 一条自由文本注记消失、元件字段位置被还原；
- 制造出「ERC 通过」的假象——同一时刻网表出现短接与丢网（`VCC4V0_SYS` 曾短接进 C10.2/R4.1）。

**为什么备份救不了**：它不报错、不中断，只是把工作悄悄换成旧的；等发现时中间若干批已白做，且"改前/改后"的判定基线也被污染。

**正确做法**：
1. 开工前检查：`Get-Process kicad,eeschema,pcbnew` 为空 + 无 `~*.kicad_pro.lck`；
2. 做 MCP 修改期间**不得打开 GUI**；要查看就等交付后再开；
3. 每批写入后校验「**mtime + md5 + wires/junctions 计数**」，出现以下任一立即停工并报告：**多个 .kicad_sch 同秒 mtime**、wires 计数下降、锁文件出现；
4. 确需终止 GUI 时，在它刚保存完（内存==磁盘）的时刻 `Stop-Process`，并清理陈旧 `.lck`。

---

## 二、工具层面（Konnect MCP）遇到的问题

| # | 问题 | 现象 | 规避/建议 |
|---|---|---|---|
| 1 | `get_pin_net_name` / `get_component_nets` 用几何启发式判网 | 对 U3.AGND 返回 `GND`，实际是悬空地孤岛；对无名网络返回 `null`，与「未连接」无法区分 | 一律以 `kicad-cli sch export netlist` 为准；预设应把这条写成硬规则 |
| 2 | 电源符号落导线中段依赖自动 junction | 后续任意一次写操作会触发 junction 重判，把「无依据」结点清掉 → 符号静默脱网，ERC 从 0 变 4 | 先 `split_wire_at_point` 或 `add_wire` 引出，再在端点放符号；预设可加校验钩子 |
| 3 | 无标题栏编辑工具 | `set_schematic_page` 只能改图幅；`verification` / `editor_navigation` 都没有 title_block 能力 | 预设需补此能力，或明确「标题栏由人工填写」并给出建议文案 |
| 4 | 文本注记只能增不能改 | 只有 `add_schematic_text`；但**删除是可以的**：`batch_delete(uuids=[...])` 支持 text | 预设应提供「删除+重建」的注记编辑模式（本次已实践成功） |
| 5 | 无「批量标签 → 电源符号」原语 | 220 处 GND 标签 + 149 处轨名标签只能逐个 `add_power_symbol` | 建议增量提供该原语，单次任务可省 300+ 次调用 |
| 6 | `update_symbols_from_library` 对引脚位移零容忍 | 引脚一动就拒绝；`allow_pin_moves=true` 会断线 | 预设应强制先 `dry_run`，并规定拒绝时只报告不改 |
| 7 | 多单元符号（本次 U1 为 7 单元/315 脚） | 只放 1 个单元时按引脚号查其它脚会失败；`edit_schematic_component` 返回体极大 | 预设应提示「多单元需分块放置」；字段编辑按 unit 逐个做 |
| 8 | `rename_project` 与子页改名 | 工程改名会重写各 symbol 的 `(project …)`；子页改文件名必须先落盘再用 `edit_sheet(new_file=…)` 重指向 | 预设应内置「英文名工程化」流程 |
| 9 | ERC JSON 字段缺失 | `unconnected_wire_endpoint` 的 items 无 x/y，无法定位 | 用 `find_orphan_items` 逐页定位 |
| 10 | 内联 PNG 会淹没上下文 | `render_schematic_png(inline=true)` 返回 base64，单页可达 200KB+ | 一律写文件 + `read_image`；或仅 `get_schematic_view` 取 SVG |
| 11 | **ERC 不能按子页跑** | `run_erc` 对子页文件会被拒（子页非工程根，工程库表不读 → 误报"整个库不存在"） | 门禁统一对**根页**跑全层级 ERC |
| 12 | **不能新建自定义轨名电源符号** | `3V3_BOARD`/`VIN_12V` 等是 `power:VCC` 改 Value 的实例，库里没有同名符号，`add_power_symbol("3V3_BOARD")` 报错 | 复用并移动**现有实例**（Value 不变 → 网络名不变）；新建时先放 `VCC` 再改 Value |
| 13 | `move_connected` 未实现 | 移动元件**不会带走导线**，旧导线留在原地变悬空段 | 重排一页 ≈ 重画该页布线：移动 → 清旧 wire/junction/label → 重画 → 仅保留必需命名 |
| 14 | no_connect 可随引脚移动 | `move_schematic_component` 会带 NC 标志（本次 `no_connects_moved=1`） | 移动后回读确认 NC 仍在引脚端点，**不要重建** |

---

## 三、KiCad 语义层面的坑（最容易造成真实设计缺陷）

1. **局部标签与全局标签同名 = 两个不同网络。**
   本次实测：`4G_PWR_EN`、`4G_RESET_CTRL`、`4G_WDISABLE_CTRL`、`HDMI_5V` 四条信号两端各不相同，仅因一侧写的是 local label、另一侧是 global label。ERC 当时只报 `isolated_pin_label`（warning），**error 为 0**，极易被忽略。

2. **ERC 的覆盖盲区会造成「假通过」。**
   - 完全悬空的地孤岛（内部无 `power_in` 引脚）不报 error → 本次有 3 组去耦电容地轨（`C2/C15+U3.AGND`、`C5/C7`、`C3/C4`）长期未接地，修复后 GND 节点 254→263。
   - 悬空线端只是 warning（`unconnected_wire_endpoint`）。
   - 结论：**「ERC error = 0」不等于电气正确**，必须叠加网表检查与结构检查。

3. **使用标签代替电源符号的三重代价**（用户指出、实测确认）：
   绕过电源驱动判定、与真实电源符号同名时报 `same_local_global_label`、图面读不出接地。
   本次把 220 处 `GND` 标签与 82 处轨名标签符号化后，`same_local_global_label` 从 12 → 0。

4. **EasyEDA 符号引脚电气类型**：大量 `unspecified` / 被误定为 `input`，导致 415 条 `pin_to_pin` 与 14 条 `pin_not_driven`。需要重建符号才能消——预设应在导入阶段就归一化。

---

## 三之二、绘图风格（**必须强调**）：局部实线、远端命名

这条是本任务后期才确立、但应当在预设里**默认执行**的风格。不强调它会怎样：整张图退化成靠 net label 接线，于是标签密集、归属难辨（"这段 `VCC4V0_SYS` 到底属于哪个符号"）、文字间隙永远在打补丁，最后连 1mm 门禁都救不回来。**去标签化不是美化，是消除复杂度的根因手段。**

### 默认规则
**局部连接画实线，不命名。** 判据按优先级：

| 情形 | 做法 |
|---|---|
| 两三个引脚相邻（几毫米到十几毫米），存在一条不与其它网络交叉的正交路径 | **实线直连，不命名** |
| 同一局部功能组内（bootstrap、FB 分压中点、COMP 补偿网络、去耦电容到电源脚、串联电阻中点、晶振与负载电容） | **实线直连，不命名** |
| 跨页信号 | `global_label`（或 hierarchical + sheet pin） |
| 电源轨 | `power` 符号 |
| 成员分布图面两端、拉线会横穿整页或穿过其它元件 | 保留命名 |
| 文档/资源表要求按名字识别的信号（`RS485_x_*`、`ETH0_*`、`PCIE2_*`、`HDMI0_*`、`USB*`） | 保留命名 |

### 识别"该改实线"的强信号
- **同一页出现两个以上同名标签** → 几乎总是应当合并成实线（本次 `HUB_A_XI`/`HUB_A_XO`、`BUCK_5V_RBOOT` 都属此类）；
- 标签把一个引脚"接"到隔壁几毫米的另一个引脚 → 实线；
- 标签用来在页内"长途布线"绕过元件 → 说明布局该重排了，而不是该加标签。

### 反方向的陷阱（避免过度复杂化）
去标签化**不等于**把所有东西都用线连起来。以下情况保留标签更清晰：
- 一个网络有 4 个以上成员且分散，硬连会形成蛛网；
- 多路同构电路（本次 RS485×4）——块内可实线，但块与块之间的**跨路信号仍用统一命名**，靠命名表达"同构对应关系"比靠连线更易读；
- 必须跨过多个元件才能连到的远端节点；
- 需要表达"同一物理信号在两处出现"的场合。

### 与门禁的关系
去标签化会让网络**改名甚至变成无名网**（KiCad 会自动命名 `Net-(R3-Pad2)` 之类）。因此此阶段的门禁必须从"网表逐字节一致"切换为「**每个网络的成员集合不变**」——这条口径不放开，去标签化就无法验收；但一旦放开，成员增删就是最灵敏的接错/短接探测器。

---

## 四、环境与工具链问题

| 问题 | 现象 | 处理 |
|---|---|---|
| 中文目录名 | DSH 沙箱把含中文的工程目录判为不可写（`workspace-write` 下 `Set-Content`/`Rename-Item` 均被拒），且 `easyeda2kicad`/Python 写文件报 `PermissionError` | 把目录、工程文件、子页文件名全部英文化；必要时对该类命令单独提权一次 |
| `easyeda2kicad` 参数 | `--output` 用相对路径 + `--project-relative` 会 `ValueError: not in the subpath` | 必须**绝对路径** + `--project-relative` |
| `easyeda2kicad` 封装错误 | 生成的 `THVD1450DR` 带 VSON-8 封装，而 DR 后缀实为 SOIC-8（官方 KiCad 符号同样有此问题） | 生成后必须核对封装与订货后缀 |
| PowerShell 编码 | 命令里含中文时解析失败（`ParserError`、mojibake） | 脚本输出全用 ASCII；中文只出现在写入的文件内容里 |
| PowerShell 不支持 heredoc | `python - <<'PY'` 报错 | 改为先 `write` 落 `.py` 再执行 |
| `tools/overlap_check.py` 找不到 kicad-cli | 默认 PATH 无 kicad-cli | 脚本默认 `kicad-cli`；可用 `$env:KICAD_CLI` 或 `--kicad-cli` 指定 |

---

## 五、可直接复用的脚本（`tools/`）

| 脚本 | 作用 | 关键用法/要点 |
|---|---|---|
| `sch_clearance_check.py` | **当前首选**的可读性门禁。直接只读解析 `.kicad_sch`，枚举 label/global_label/hierarchical_label、符号 Reference/Value（**含 `#PWR` 轨名**）、自由文本，做两类判定：`text-text`（包围盒间隙 < `--clear`，默认 1.0mm）与 `text-wire`（导线穿入文字框、沿导线累计 >1.5mm，标签锚在端点不算） | 零依赖、不栅格化；退出码 0/1 可做 CI 门禁；`--no-wires` 可只查文字 |
| `overlap_check.py` | 早期工具，基于 SVG 不可见 `<text>` 层的重叠检查 | **已知缺陷**：曾把 `(lib_symbols …)` 内符号图形文字用裸本地坐标比较（3_Core/6_Ethernet 因此各报 21/9 条假阳性）；且**不覆盖**文字↔元件本体、文字↔引脚号。保留作历史对照，新任务优先用 `sch_clearance_check.py` |
| `overlap_check.py`（原始说明） | **核心工具**。原理图标签/位号/值重叠检查器 | 原理：`kicad-cli sch export svg` 会把每段文字再写一遍为 `<text opacity="0">`，带 `x/y/textLength/font-size/text-anchor/transform`，据此算包围盒，无需栅格化。含三重排除：引脚名集（从 `.kicad_sym` 抽 788 个）、真实位号集（从工程 `.kicad_sch` 抽 337 个）、引脚号；沿祖先 `<g transform>` 累积旋转（竖直标签必需）。判定 `label_label / label_text / ref_value` 三类，`note_text` 单列。退出码 0/1 可做 CI 门禁 |
| `efoo2kicad.py` | EasyEDA Pro `.efoo`（JSONL）→ `.kicad_mod` | 比例固定 0.0254 mm/unit（=1 mil，EasyEDA PCB 域内部单位）；输出焊盘 + F.SilkS 外框 + F.CrtYd |
| `efoo_scale.py` | `.efoo` 单位反推器 | 用「单排内间距 / 焊盘尺寸 / 总跨距 / MP 位置」在候选比例里交叉验证，只有 1 mil 能让四个数字同时合理（0.5mm 间距、0.250×2.000mm 焊盘、80.00mm 长度） |
| `efoo_inspect.py` | `.efoo` 记录类型/字段布局探针 | 先看 `PAD`/`FILL`/`POLY` 分布再决定怎么转 |
| `gnd_masked_check.py` | `overlap_check` 的补丁视角 | 因 `"GND"` 同时在引脚名集里会被主脚本排除，此脚本专门把 GND 当标签重判 |
| `probe.py` / `sch_region.py` / `region_dump.py` | 区域级几何查询（文本盒/字段/标签/导线） | 定位「某个坐标上到底有什么」时最省事 |
| `free_space.py` / `plan.py` | 空闲位搜索与摆放规划 | 批量重排标签时用来找不压字的落点 |
| `fields_dump.py` / `field_sample.py` | 逐符号导出 Ref/Value 字段坐标 | 批量移动 Value 字段前的取数步骤 |
| `crop_png.py` / `crop_region.py` | 渲染图按 mm 区域裁剪放大 | 目视复核局部时用，A2/A3 混排需按页传尺寸 |

### 关于 `exports/` 里的临时脚本（需要在预设里治理）

`exports/` 下目前有 **30 多个**一次性脚本（`_netraw.py`、`_erc_count.py`、`netdiff.py`、`net_analyze.py`、`value_plan*.py`、`build_worklist.py`、`classify_pts.py`、`gen_payload.py` 等），以及十余个 `svg_*` 目录、多个 `erc_*.json`、`.net` 快照与 `backup_r7/r8`。

**问题**：`exports/` 本应是交付物目录，却被当成了工作区，导致交付件与中间产物混在一起、难以判断哪个是最新版（本次同一工程出现过 `v2/v3/final/final2/final3/gnd/r7/r8` 共 8 套 PDF）。

**建议预设规则**：
- `exports/` 只放交付件，命名固定为 `<项目>_<类目>_<版本>.{pdf,net,csv}`，且只保留最新一版；
- 一次性脚本一律进 `tools/`，或进 `tmp/`（可随时清空）；
- 中间快照进 `tmp/`，不进 `exports/`。

---

## 六、建议加进预设的工作流钩子

1. **导入后归一化**：EasyEDA 符号引脚类型 → `passive/bidirectional/power_in`，并核对 DR/封装后缀对应关系。
2. **连线规范检查**：禁止电源符号落中段；`same_local_global_label` 与 `local/global 同名` 一律按 error 级别处理。
3. **跨页一致性检查**：同一信号名在不同页必须是同一种 label 类型（全 global 或全 hierarchical + sheet pin）。
4. **改前改后网表 diff**：任何布局类改动都要求网络拓扑零变化。门禁口径分两档：
   - **纯外观改动**（只移字段/移标签）：要求网表除时间戳外**逐字节一致**；
   - **去标签化 / 实线直连**（本任务后期的正确方向）：允许网络**改名甚至变成无名网**，但要求**每个网络的成员集合与改动前完全一致**——这是抓接错与短接的主门禁。
5. **重叠门禁**：每页改完跑 `overlap_check.py`，三类缺陷必须为 0。
6. **结构门禁**：`find_shorted_nets`（每页）+ `find_orphan_items`（每页）+ `find_single_pin_nets`。
7. **ERC 门禁解读**：error 必须为 0，但要同时报告 warning 分类，并显式声明 ERC 覆盖盲区（地孤岛、悬空线端）。

---

## 七、本次任务的量化基线（供回归对比）

| 指标 | 终值 |
|---|---|
| 页数 / 图幅 | 10 页（核心板页 A2，其余 A3） |
| 元件 / 网络 / 引脚 | 255 / 597 / 1367 |
| ERC | **0 error**；423 warning（`pin_to_pin` 415、`isolated_pin_label` 8） |
| 重叠缺陷 | 0（10 页） |
| 已消除的规则 | `same_local_global_label`、`multiple_net_names`、`footprint_link_issues`、`lib_symbol_mismatch`、`unconnected_wire_endpoint` 全部归零 |
| 库 | `X1_EasyEDA`、`X1_EasyEDA_Extra`、`X1_Core_Board`（均 `${KIPRJMOD}` 内） |
| 未做 | PCB（无板框/叠层/布局/布线/DRC）；标题栏字段 |

### 7.1 进行中的 r10 「重排 + 去标签化」阶段（可作同类任务模板）

用户对本工程的进一步要求很关键：**先重排布局让模块间距拉开，局部网才能用实线直连并删掉多余网络名**。这不是美化，是消除拥挤的根因——原图几乎全靠 net label 接线，于是标签密集、归属难辨、1mm 间隙永远在打补丁。

| 页 | 元件 | 状态 |
|---|---:|---|
| 2_Basic_IO | 13 | ✅ 完成：16 wire → 10 wire + 1 junction，删 5 个局部标签，四功能区块间 ≥10mm；成员集合 10 组 17 引脚逐一比对无差异；ERC 0/0；clearance 0 |
| 5_RS485 | 20 | 进行中（4 路同构块，验证同构间距与四路内部实线化） |
| 8_4G_Module / 9_Aux_GPIO | 24 | 待做 |
| 4_USB | 66 | 待做 |
| 6_Ethernet / 7_Display_Audio | 76 | 待做 |
| 1_Power | 95 | 最后做（最复杂） |

每页闭环模板：导出该页网络成员集基线 → 规划功能区与坐标 → 移动元件 → 清旧 wire/junction/label → 重画局部实线 → 仅对必需命名放标签/电源符号 → 四项门禁（成员集 / 根页 ERC / 两零间隙 / 渲染目视）→ mtime+md5+wires 快照校验。

**必须保留命名的白名单**：跨页信号、电源轨、跨页远端网络、文档要求按名识别的信号（`RS485_x_*`、`ETH0_*`、`PCIE2_*`、`HDMI0_*`、`USB*`）。其余局部网（bootstrap、FB 分压中点、COMP 补偿、去耦到电源脚、串联电阻中点、晶振负载电容）一律实线直连、不命名。

**两条不要"顺手改掉"的语义**：未确认电压的外部电源针（如 RS485 接头 pin1）保持悬空**且不标 NC**；可选端接（120Ω 跨 A/B）保持"默认不装"的可配置语义，不因改实线变成常接。

---

## 八、给预设的一句话

这次任务里最贵的教训是：**ERC error=0 会让一个电气上已经断开的图通过验收**。所以预设必须以「网表 + 结构检查 + 重叠检查」三角来定义完成，而 ERC 只是其中一角。
