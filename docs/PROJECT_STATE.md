# PROJECT_STATE.md

Updated: 2026-07-17

本文件是新线程接手项目时的首要状态说明。内容已依据当前代码、Git 状态、全量测试和本地集成验证重新核对，不以聊天记录或领导汇报作为完成依据。

## 1. 项目目标

项目名称：北港至客户工厂全链路运输路径推断原型。

目标是构建一个可解释的 Python 原型：读取本地运输业务数据，统一节点、订单、计费单位、费用和时间结构，构造保留平行运输方案的有向图，并分别输出成本最低路径和时效最优路径及其分段依据。

当前项目用于规则和数据可行性验证，不承担生产调度、正式报价、数据库服务、前端应用或高并发 API 职责。

## 2. 当前架构

### 2.1 已投入真实数据流程的前置链条

```mermaid
flowchart TD
    A["DATA_DIR 本地 JSON/JSONL"] --> B["data/audit.py 数据审计"]
    A --> C["data/loaders.py 类型化加载"]
    C --> D["domain/node_registry.py 节点注册与覆盖检查"]
    D --> E["geo/coordinate_provider.py 本地优先坐标解析"]
    E --> F["geo/tencent_map_provider.py 外部坐标兜底"]
    C --> G["domain/freight_rate.py FreightRate"]
    G --> H["domain/latest_rate_selector.py 最新有效运价"]
    I["domain/route_request.py RouteRequest"] --> J["domain/unit_conversion.py 单位精确匹配"]
    H --> K["domain/cost_rules.py CostRuleEngine"]
    J --> K
    K --> L["data/loaders.py EdgeCandidate / ReviewItem"]
    E --> L
    L --> M["本地 CSV 输出与 Demo 验证"]
```

`demos/real_data_run.py` 的真实数据链目前仍停在 `EdgeCandidate` 和本地 CSV 输出；该旧候选只有费用，没有接入运输时间、客户分支和正式 `TransportEdge`。正式模型链已经实现，但尚未与这条真实数据候选链连接。

### 2.2 外部地图边界

- `geo/coordinate_provider.py` 负责本地坐标优先和外部 Provider 兜底。
- `geo/distance_provider.py` 定义道路路线请求、结果、公里与小时单位及禁用 Provider。
- `geo/tencent_map_provider.py` 实现腾讯地点搜索、普通驾车路线和可选货车路线适配器。
- API Key 只从 `TENCENT_MAP_API_KEY` 读取。
- 当前数据加载主流程只绑定本地节点表，不会自动调用腾讯地图并回写坐标。

### 2.3 已剥离的旧原型图搜索链条

```text
sample_data CSV
-> data/io_utils.py
-> graph_builder.py: nx.DiGraph
-> route_planner.py: nx.shortest_path
-> models.py: legacy RouteResult
```

这条早期链路已从 `src/` 剥离，不再作为可导入代码保留。旧样例数据仍可作为历史材料存在，但真实业务主流程不得依赖该 CSV/DiGraph 链。

### 2.4 已实现的正式模型与搜索链条

```text
ShippingTimeProvider
-> CustomerProfile 与路线分支
-> TransportEdge
-> routing/transport_graph.py: nx.MultiDiGraph
-> routing/route_search.py: RouteSearchStrategy
-> 分别搜索 cost / time
-> routing/route_result.py: RouteSegment / RouteResult 解释输出
```

该链已通过虚构节点和脱敏字段完成单元与集成演示。只有 `available` 边可以进入正式图，平行边使用 `edge_id` 作为 key，搜索结果返回每段 edge key。真实客户画像、北港至南港数据和当前 `EdgeCandidate` 尚未接入。

## 3. 已完成功能

### 3.1 数据审计

- 扫描 JSON、JSON 数组和 JSON Lines。
- 统计结构类型、记录数、字段、类型、缺失率、运输方式、费用单位、包装方式和适用品种。
- 检查空值、明显别名、重复记录、费用异常和维护日期格式。
- 费用异常按费用单位分组，避免混合单位互相判定异常。
- 脱敏 Markdown 与本地详细输出分离；敏感明细默认只能写入 `output/`。

### 3.2 真实数据加载

- 通过 `DATA_DIR` 查找 `运价表.json`、`地点经纬度.json`、`其他费用表.json`。
- 提供文件缺失、多文件冲突、非法 JSON、字段缺失、字段类型错误、非法数值和非法日期异常。
- 将运价、节点和其他费用加载为类型化对象。
- 保留运价来源文件和来源行号。

### 3.3 节点与坐标

- 生成稳定节点 ID。
- 支持保守别名识别、强制物理节点合并和坐标冲突报告。
- 分析运价始发/到达是否能匹配标准节点。
- 已实现本地优先坐标 Provider。
- 已实现腾讯地点搜索 Provider；唯一或唯一精确结果可解析，歧义结果转人工确认。

### 3.4 订单、单位与费用

- `RouteRequest` 支持数量、数量单位、包装、品种、节点标识、散船计价模式和可选人工时间字段。
- `吨`、`箱`、`柜` 分别精确匹配 `元/吨`、`元/箱`、`元/柜`。
- 包装仅用于辅助验证，运输方式从运价记录读取。
- 有效单位价格转换为当前订单当前运输段总费用，单位为元。
- `CostCalculationResult` 保存状态、总费用、规则编号、版本、计算过程、来源、方式和单位。
- 已实现既定运价单价、人工总价、散船指数、散船人工单价、散船人工总价、熟悉汽运维护运价和陌生散粮汽运距离阶梯计费。
- 陌生散粮汽运只在外部提供可追溯 `distance_km` 和 `distance_source` 时计算；缺距离或缺来源仍返回 `manual_review`。
- 陌生集装箱汽运规则已登记但保持禁用。

### 3.5 FreightRate 与最新运价

- `FreightRate` 保存业务字段、原始价格、价格类型、来源、维护日期、节点 ID 和源记录位置。
- `FreightRate.evaluate_for_request()` 兼容入口委托给 `CostRuleEngine`。
- 同一业务键按最新有效维护日期选取运价。
- 原始空日期保持 `None`，排序时映射为 `1970-01-01`。
- 正常日期记录覆盖无日期历史基线。
- 最新同日冲突转人工复核，完全重复记录确定性去重。
- 原始历史仍保留在加载结果和数据审计中。

### 3.6 地图路线 Provider

- 普通驾车路线返回公里制距离、小时制预计时间、收费金额和路线标签。
- 货车路线适配器保留为可选能力，不作为个人 Key 或当前原型的硬依赖。
- 网络、权限、空结果和异常字段均不会伪造成有效距离或时间。
- 单元测试使用模拟响应，不消耗真实 API 配额。

### 3.7 ShippingTimeProvider

- `ShippingTimeRequest` 和 `ShippingTimeResult` 已统一表示运输阶段、运输方式、原始输入、内部小时值、状态、来源和说明。
- `ManualShippingTimeProvider` 是当前唯一启用实现，接受人工确认的正数时间。
- 支持小时、天和分钟换算为内部小时。
- 缺失、零值、负数、非数值和不支持单位均返回 `manual_review`，不会产生可用于路径搜索的时间。
- `JsonShippingTimeProvider`、`DatabaseShippingTimeProvider` 和 `ApiShippingTimeProvider` 已作为未配置占位 Provider 保留；调用时只返回人工复核说明，不返回 0。
- 腾讯普通驾车耗时仍只属于道路参考 Provider，不会替代散船或完整运输作业时间。

### 3.8 CustomerProfile 与路线分支

- `CustomerProfile` 保存客户、工厂节点、自有码头标志/节点、允许包装/品种和可追溯来源。
- 自有码头标志未知、缺少来源、缺少码头节点或字段矛盾时返回 `manual_review`，不猜测路线分支。
- 有自有码头客户只允许南港至客户自有码头分支；无自有码头客户只允许候选中转港加短途汽运分支。
- 候选中转港可按确认距离预筛前 K，但结果明确要求后续分别比较总费用和总时间。

### 3.9 TransportEdge 与正式图

- `TransportEdge` 统一节点、方式、包装、品种、订单段总费用、小时制时间、原始价格、维护日期、距离、来源、规则版本和计算过程。
- 缺节点、费用、时间或追溯字段的候选保留为 `manual_review` 或 `not_applicable`，不会默认成 0。
- `routing/real_data_bridge.py` 已能把真实 `EdgeCandidate` 转换为正式 `TransportEdge`；缺人工时间或缺节点时仍保持 `manual_review`。
- `routing/transport_graph.py` 默认要求 `NodeRegistry`，使用 `nx.MultiDiGraph` 和 edge ID key 保存平行边；脱敏演示/测试必须显式声明允许未注册节点。
- 不可用、重复 edge ID 或引用未注册节点的边不会进入图，并保留问题代码和原因；存在建图排除项时不得输出 `resolved` 推荐。

### 3.10 双目标搜索与解释结果

- `routing/route_search.py` 定义 `RouteSearchStrategy` 协议和 NetworkX Dijkstra 基线实现。
- 成本使用 `cost`、时效使用 `time_hours` 独立搜索，不生成综合权重。
- 搜索结果返回节点序列和每段 `(from_node_id, to_node_id, edge_key)`。
- 缺节点、同起终点、缺权重、非法权重和无路径均有显式状态。
- 搜索结果绑定目标权重图签名；搜索后节点、边或目标权重变化时返回 `manual_review` 并要求重新搜索。
- `routing/route_result.py` 从图中还原完整分段，保存价格/时间来源、计费规则、计算过程、总费用和总时间。
- 结果层重新核对 edge key 和追溯字段，并强制总费用、总时间等于分段求和；无路径和人工复核结果导出时保留状态行。

### 3.11 Demo

- `demos/real_data_run.py`：读取真实本地数据、构建订单计费候选、转换正式运输边并输出本地候选/人工复核 CSV；设置本地演示人工时间后可验证正式图搜索链。
- `demos/leader.py`：统一入口展示各模块，默认运行双目标路径搜索与解释结果。
- `demos/leader_shipping_time.py`：展示人工运输时间来源、小时制换算、非法输入人工复核和未接入数据源占位。
- `demos/leader_customer_profile.py`：展示客户分支互斥、候选港预筛和缺数据人工复核。
- `demos/leader_transport_edge.py`：展示可用边和缺节点/缺时间候选。
- `demos/leader_transport_graph.py`：展示 MultiDiGraph 平行边和排除问题清单。
- `demos/leader_route_search.py`：展示成本最低与时效最优路径、edge key 和完整分段来源。
- `demos/tencent_map_probe.py`：可选的公开地点 API 冒烟测试。

## 4. 当前正在处理的问题

1. **陌生散粮汽运计费**：已可使用 geo 层确认的 `distance_km` 和 `distance_source` 计算；缺距离、缺来源或异常距离仍人工复核。
2. **真实数据正式链集成**：真实 `EdgeCandidate` 已能在显式人工时间下转换为 `TransportEdge` 并进入正式图；默认缺时间仍全部人工复核。
3. **Git 分支状态**：远程 README 分叉已处理并由用户完成推送；本次陌生散粮汽运计费提交后，本地 `main` 预计为 `ahead 1`。
4. **真实业务链尚未完全接通**：客户画像、正式运输时间来源、北港至南港散船数据和其他费用归属仍未接入。
5. **节点覆盖不足**：真实数据验证中仍有运价端点无法映射到标准节点，不能进入后续正式图。

## 5. 已知缺陷与技术债

### 5.1 阻止真实业务路径推荐的问题

- `CustomerProfile` 模型和分支规则已实现，但正式客户数据源尚未提供。
- 北港至南港散船费用和完整运输时间尚未提供，无法形成全链真实边。
- 真实 `EdgeCandidate` 已可通过 `routing/real_data_bridge.py` 组合为 `TransportEdge`，但正式运输时间来源和客户规则数据仍未接入。
- 真实运价候选仍有端点缺少标准节点 ID，不能加入正式图。
- 其他费用是否计入运输段、计入哪一段尚未确认。

### 5.2 数据接入缺口

- 当前真实数据主要覆盖南港至客户工厂，北港至南港散船运价和人工运输时间尚未提供。
- `src/data/loaders.py` 的 `parse_freight_rate()` 当前把真实运价 JSON 全部解析为 `price_type="unit_price"`；真实数据协议尚不能表达人工总价运价。
- `其他费用表.json` 已加载为 `AdditionalFee`，但尚未叠加到运输段总费用。
- 腾讯地图新坐标和路线没有本地缓存、人工确认和正式表回写机制。
- 当前主流程不会对未匹配节点自动调用腾讯坐标 Provider。

### 5.3 已剥离旧原型的注意事项

- `graph_builder.py`、`route_planner.py` 和 `models.py` 已从 `src/` 删除。
- 不再保留旧 `nx.DiGraph` 和 `nx.shortest_path` 兼容入口。
- 新增业务代码必须接入 `src/routing/transport_graph.py`、`src/routing/route_search.py` 和 `src/routing/route_result.py`。
- `README.md` 仍以 CSV/DiGraph 早期设计为主，与当前 JSON/FreightRate/Provider 架构存在文档漂移；远程另有两次 README 修改尚未合并。

### 5.4 环境问题

- 默认 `C:\Program Files\Python312\python.exe` 为 Python 3.12.7，但没有安装 pytest。
- 当前测试依赖通过本地 `.python_packages` 和 `PYTHONPATH` 提供；该目录是机器/检出环境专属，不是标准项目虚拟环境，后续协作宜建立独立 `.venv`。
- PowerShell 输出中文时可能受控制台编码影响；设置 `PYTHONIOENCODING=utf-8` 后正常。

## 6. 关键文件及作用

| 文件 | 作用 | 当前状态 |
|---|---|---|
| `AGENTS.md` | 长期开发规范、隐私、Git、业务边界和完成标准 | 本次已更新 |
| `PLAN.md` | 真实里程碑和下一阶段验收标准 | 本次已更新 |
| `docs/PROJECT_STATE.md` | 当前交接状态 | 本文件 |
| `docs/DECISIONS.md` | 已确认业务与技术决策 | 本次更新 |
| `docs/ARCHITECTURE.md` | 当前功能包结构、正式链和下一真实数据接入边界 | 已同步至阶段 13 与代码重组 |
| `CHANGELOG.md` | 实际工程变更历史 | 已记录至阶段 13 第一版 |
| `src/data/audit.py` | 数据质量审计与脱敏输出 | 已完成第一版 |
| `src/data/loaders.py` | 真实 JSON 加载和计费候选构建 | 已完成第一版，仍缺时间与其他费用集成 |
| `src/domain/node_registry.py` | 标准节点、别名、坐标冲突和覆盖检查 | 已完成第一版 |
| `src/geo/coordinate_provider.py` | 本地优先坐标解析接口 | 已完成基础版 |
| `src/geo/distance_provider.py` | 道路路线请求/结果和禁用 Provider | 已完成基础版 |
| `src/geo/tencent_map_provider.py` | 腾讯地点与道路路线适配器 | 已完成基础版 |
| `src/routing/shipping_time_provider.py` | 运输时间请求/结果、人工 Provider 和未配置占位 Provider | 已完成第一版 |
| `src/routing/customer_profile.py` | 客户画像、互斥路线分支、包装/品种过滤和候选港预筛 | 已完成第一版；正式数据源待接入 |
| `src/domain/route_request.py` | 订单结构和包装/单位辅助校验 | 已完成第一版 |
| `src/domain/unit_conversion.py` | 单位精确匹配和总费用换算 | 已完成 |
| `src/domain/freight_rate.py` | 正式运价模型 | 已完成第一版 |
| `src/domain/latest_rate_selector.py` | 最新有效运价、冲突和重复处理 | 已完成第一版 |
| `src/domain/cost_rules.py` | 统一费用规则引擎和追溯结果 | 已完成第一版；陌生散粮可用确认距离计费，陌生集装箱仍禁用 |
| `src/routing/transport_edge.py` | 正式运输边、可用状态、来源和规则追溯 | 已完成第一版 |
| `src/routing/real_data_bridge.py` | 真实 EdgeCandidate 到 TransportEdge/正式搜索链的保守桥接 | 已完成保守第一版；缺时间仍人工复核 |
| `src/routing/transport_graph.py` | 正式 MultiDiGraph 构建、平行边和排除问题清单 | 已完成第一版 |
| `src/routing/route_search.py` | cost/time 独立 Dijkstra 策略和 edge key 结果 | 已完成第一版 |
| `src/routing/route_result.py` | 分段解释、汇总校验和行式导出 | 已完成第一版 |
| `src/demos/real_data_run.py` | 真实数据开发集成脚本 | 可运行 |
| `src/demos/leader.py` | 领导展示入口 | 可运行，默认展示双目标路径搜索与解释结果 |
| `src/demos/leader_shipping_time.py` | 运输时间 Provider 展示 | 可运行 |
| `src/demos/leader_customer_profile.py` | 客户画像与路线分支展示 | 可运行 |
| `src/demos/leader_transport_edge.py` | 标准运输边展示 | 可运行 |
| `src/demos/leader_transport_graph.py` | MultiDiGraph 展示 | 可运行 |
| `src/demos/leader_route_search.py` | 双目标搜索与解释结果展示 | 可运行 |

## 7. 环境配置

### 7.1 必需环境变量

```powershell
$env:DATA_DIR=(Resolve-Path ".\data_REAL").Path
$env:TENCENT_MAP_API_KEY="<仅在本地配置，不写入代码或文档>"
$env:PYTHONIOENCODING="utf-8"
```

- 只运行单元测试和非 API Demo 时不需要腾讯地图 Key。
- 只运行领导默认 Demo 时不需要 `DATA_DIR`。
- `demos/real_data_run.py` 和 `data/audit.py` 需要 `DATA_DIR`。

### 7.2 当前验证解释器

默认 Python：

```text
C:\Program Files\Python312\python.exe
Python 3.12.7
```

默认 Python 当前不能单独导入 pytest，但仓库本地 `.python_packages` 已包含测试依赖。设置 `PYTHONPATH=.python_packages` 后，本次全量测试通过。用户现有 PyCharm 虚拟环境也可以运行测试，但其机器专属绝对路径不写入 Git 交接文档。

### 7.3 依赖

依赖声明在 `requirements.txt`，主要包括 pandas、openpyxl、networkx、numpy、pydantic、python-dotenv、requests、geopy、xlsxwriter 和 pytest。

## 8. 启动、测试和验证命令

先进入仓库：

```powershell
cd "D:\中粮贸易实习文件\路径规划项目\Codex工程移交包_港口路径规划原型\codex_handoff"
$env:PYTHONPATH=(Resolve-Path ".\.python_packages").Path
$env:PYTHONIOENCODING="utf-8"
```

全量测试：

```powershell
python -m pytest -q
```

本次实测结果：

```text
217 passed in 1.00s
```

真实数据集成验证：

```powershell
$env:DATA_DIR=(Resolve-Path ".\data_REAL").Path
python -m src.demos.real_data_run
```

领导 Demo：

```powershell
python -m src.demos.leader
python -m src.demos.leader latest-rate
python -m src.demos.leader shipping-time
python -m src.demos.leader customer-profile
python -m src.demos.leader transport-edge
python -m src.demos.leader transport-graph
python -m src.demos.leader route-search
```

数据审计：

```powershell
$env:DATA_DIR=(Resolve-Path ".\data_REAL").Path
python -m src.data_audit
```

腾讯地图公开地点冒烟测试，仅在本地配置 Key 后执行：

```powershell
$env:TENCENT_MAP_API_KEY="<local-only>"
python -m src.demos.tencent_map_probe
```

本次交接没有重新调用真实腾讯 API；相关单元测试使用模拟响应并通过。

## 9. 本次真实数据验证摘要

本地 `data_REAL/` 验证成功，汇总结果如下，不包含客户名、路线名、坐标或价格明细：

| 指标 | 数量 |
|---|---:|
| 运价记录 | 492 |
| 坐标记录 | 263 |
| 其他费用记录 | 18 |
| 运价表唯一地点名称 | 295 |
| 已匹配地点名称 | 263 |
| 未匹配地点名称 | 32 |
| 双端点均匹配的原始运价记录 | 306 |
| 当前订单计费候选 | 314 |
| 具备双端节点 ID 的候选 | 144 |
| 缺少节点 ID 的候选 | 170 |
| 人工复核记录 | 27 |
| 被较新记录覆盖 | 12 |
| 最新完全重复记录 | 4 |
| 使用 1970 比较基线的记录 | 299 |
| 包装不适用 | 134 |
| 品种不适用 | 1 |

验证生成的 CSV 位于忽略目录 `output/`，不得提交。

## 10. 最近修改内容

### 当前未提交真实链桥接改动

主要内容：

- 新增 `src/routing/real_data_bridge.py`，把真实计费候选转换为正式 `TransportEdge`；
- 缺人工运输时间或缺节点 ID 的真实候选保持 `manual_review`；
- `src/demos/real_data_run.py` 默认不伪造时间；只有设置 `REAL_DATA_DEMO_MANUAL_TIME_HOURS` 后才运行本地正式图搜索验证；
- 更新 `PLAN.md`、`docs/ARCHITECTURE.md`、`docs/DECISIONS.md`、`docs/PROJECT_STATE.md` 和 `CHANGELOG.md`。

### 本地最新提交

```text
3888e7d refactor(structure): organize route prototype packages
```

主要内容：

- 将主代码按功能包整理为 `src/data`、`src/domain`、`src/geo`、`src/routing` 和 `src/demos`；
- 删除旧 CSV/DiGraph 原型文件和重复 Demo；
- 更新测试导入、Demo 导入和长期文档。

### 上一个本地功能提交

```text
75674a3 feat(routing): add formal route recommendation pipeline
```

主要内容是正式路线推荐链路：运输时间、客户分支、标准运输边、MultiDiGraph 建图、cost/time 独立搜索和解释结果。

### 已整合的远程 README 提交

```text
78aa04d Update README.md
2f5e9a8 Update README.md
```

两次提交只修改 `README.md` 标题区域；已通过 `git rebase origin/main` 整合到本地历史。上一轮本机 GitHub 凭据问题已由用户在 PowerShell 中完成认证和推送，本轮如需同步远程继续执行普通 fetch/push。

## 11. 本次提交范围与本地材料

### 11.1 当前陌生散粮汽运计费工作区改动

以下改动属于 2026-07-17 陌生散粮汽运确认距离计费范围，提交前需作为同一组审阅：

- `PLAN.md`
- `CHANGELOG.md`
- `docs/ARCHITECTURE.md`
- `docs/PROJECT_STATE.md`
- `docs/DECISIONS.md`
- `src/domain/cost_rules.py`：启用陌生散粮汽运确认距离计费，保留熟悉路线优先和缺距离人工复核；
- `src/demos/leader_cost_rules.py`：展示熟悉路线、陌生路线缺距离和陌生路线有确认距离三种结果；
- `tests/test_cost_rules.py`：覆盖确认距离计费、缺距离/缺来源拦截、熟悉路线优先和阶梯边界。

### 11.2 保留并迁移的公开探针改动

- `src/demos/tencent_map_probe.py`：保留此前用户侧公开测试地点修改，将测试地点设为全国范围的“福田站”和“故宫博物院”；不含 API Key 或真实业务地点，已随 Demo 目录迁移一并保留。

### 11.3 未跟踪本地材料

当前 Git 状态包含以下未跟踪文件，应逐个判断是否脱敏后再决定是否提交；默认不要批量加入：

- `docs/2026-07-16_DEVELOPMENT_LOG.md`
- `docs/2026-7-15_Work Plan.docx`
- `docs/2026-7-15_Work Report.docx`
- `docs/2026-7-16_Work Report.docx`
- `docs/Trans_Road_Analysis_PJ_Data_Flow-2026-07-16-013028.png`
- `docs/Untitled diagram-2026-07-16-011802.png`
- `docs/daily_development_plan_2026-07-15.docx`
- `docs/daily_work_report_2026-07-13.md`
- `docs/work_report_2026-07-10_to_2026-07-13.pptx`
- `docs/最后一公里汽运计费规则算法设计_修订版.docx`
- `docs/最后一公里汽运计费规则算法设计（修订版）.pdf`

### 11.4 忽略内容

- `data_REAL/`：已被 `.gitignore` 忽略，未被 Git 跟踪。
- `output/`：已被 `.gitignore` 忽略，包含本地验证输出，未被 Git 跟踪。

### 11.5 当前分支关系

```text
main...origin/main [ahead 1 after current local commit]
```

远程 README 分叉已处理，用户已在本机完成上一轮推送。本轮提交完成后如需同步远程，按 SOP 先 `git fetch origin`，再执行普通 `git push`，不得使用强制推送。

## 12. 下一步建议

1. 围绕 `domain/cost_rules.py`、`geo/distance_provider.py` 和 `geo/tencent_map_provider.py` 理解“距离获取”和“距离计费”的边界。
2. 用公开测试点验证 Tencent 普通驾车距离 Provider；API Key 只放本地环境变量，不写入代码或文档。
3. 继续理解和测试真实数据桥接链；确认 `REAL_DATA_DEMO_MANUAL_TIME_HOURS` 只作为本地链路验证开关。
4. 取得并确认客户自有码头标志、码头节点、允许包装/品种的正式数据源；在此之前继续使用 `manual_review`，不得猜测。
5. 确认北港至南港散船费用和时间来源，或明确第一批真实搜索只覆盖南港至客户工厂。
6. 将本地演示人工时间替换为正式运输时间来源。
7. 接入真实候选前继续处理缺节点 ID，并确认 `AdditionalFee` 应计入哪一个运输段。

## 13. 明确禁止重新实施或推翻的已确认事项

除非用户明确给出新的业务结论并要求变更决策，否则后续线程不得：

- 重新把南方港口拆成第一阶段终点和第二阶段起点两个节点；
- 重新用包装方式推断运输方式；
- 把 `箱` 和 `柜` 当作同一单位或自动换算；
- 将 `元/吨`、`元/箱`、`元/柜` 原始数值直接相加；
- 把缺失费用、距离或时间默认成 0；
- 在没有业务系数时合并 cost 和 time；
- 跳过最新运价筛选，将全部历史运价直接写入图；
- 覆盖原始空维护日期；1970 日期只允许作为内部比较基线；
- 在最新同日冲突时任意选择一条记录；
- 绕过 Provider，从费用规则、建图或搜索代码直接调用腾讯地图；
- 将地图普通驾车时间直接当作完整散船或运输作业时间；
- 启用尚未验收的陌生集装箱汽运规则；
- 使用 `nx.DiGraph` 作为最终业务图并丢失平行边；
- 只按直线距离决定中转港，不比较总费用和总时间；
- 让有自有码头的客户仍经过中转港；
- 把真实业务数据、API Key、真实输出或未脱敏材料提交到 GitHub；
- 在未取得论文或源代码时猜测并复现用户毕业论文算法；
- 把领导汇报材料当作真实工程完成状态。
