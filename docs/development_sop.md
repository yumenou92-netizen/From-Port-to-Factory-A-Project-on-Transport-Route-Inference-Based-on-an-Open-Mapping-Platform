# 北港至客户工厂全链路运输路径推断原型开发 SOP

## 1. 文件目的

本文是“北港至客户工厂全链路运输路径推断原型”的后续开发 SOP，用于约束从当前 demo 到下一阶段原型的开发顺序、数据使用方式、模块边界、验收标准和停止条件。

本 SOP 基于当前 demo 脚本、已有需求文档、数据审计报告、数据流向说明，以及近期业务讨论结论整理。它的目标不是一次性开发生产系统，而是保证后续每一步都可解释、可验证、可回退。

## 2. 当前项目定位

当前项目定位为：

```text
需求澄清 + 运输业务建模 + Python 原型验证
```

当前不定位为：

```text
生产级商业路径规划系统
```

因此，开发原则是：

- 先把业务数据结构、费用口径、时间口径和路径规则讲清楚。
- 再把数据标准化为节点、边、费率和请求对象。
- 最后再进入图构建和路径搜索。
- 每完成一个阶段先汇报，不未经确认继续扩展下一阶段。

## 3. 当前 demo 基线

当前 demo 入口为：

```text
src/demo_run.py
```

当前主流程：

```text
sample_data/transport_edges.csv
        ↓
pandas 读取边表
        ↓
graph_builder.build_directed_graph
        ↓
networkx.DiGraph
        ↓
route_planner.shortest_route 按 cost 搜索
        ↓
route_planner.shortest_route 按 time 搜索
        ↓
output/route_results.csv
```

当前 demo 特征：

- 起点和终点写死为 `NP_A` 到 `CUST_001`。
- 图结构使用 `nx.DiGraph`。
- 每条边只保留一套 `cost` 和 `time`。
- 费用和时间来自 `transport_edges.csv` 中预填的 `base_cost`、`base_time`。
- `transport_nodes.csv`、`customers.csv`、`bulk_shipping_prices.csv`、`railway_fee_rules.csv` 目前没有完整进入主流程。
- `data_audit.py` 只做 JSON 数据审计，不参与路径搜索。

当前已经生成的数据文档：

- `docs/data_usage_report.md`
- `docs/data_flow_and_unit_statement.md`

## 4. 后续开发总流程

后续开发应按以下顺序推进：

```text
阶段 0：确认当前基线
阶段 1：数据审计和数据声明
阶段 2：节点标准化
阶段 3：订单请求结构和单位校验
阶段 4：费率标准化和费用换算
阶段 5：时间 Provider 设计
阶段 6：客户画像和业务规则过滤
阶段 7：候选边生成
阶段 8：图结构升级
阶段 9：路径搜索策略封装
阶段 10：结果输出和解释字段
阶段 11：测试、演示和汇报材料
```

每个阶段必须有明确输入、输出和验收标准。没有通过当前阶段验收，不进入下一阶段。

## 5. 阶段 0：确认当前基线

### 目标

确认当前代码、数据、依赖和 demo 是否仍然可用。

### 输入

- `README_Codex_移交说明.md`
- `docs/*.md`
- `src/*.py`
- `sample_data/*.csv`
- `tests/*.py`
- `requirements.txt`

### 操作

1. 阅读 README、需求文档和当前代码。
2. 明确当前 demo 的真实能力和未接入能力。
3. 确认依赖环境是否可运行。

### 推荐命令

在 `codex_handoff` 目录下执行：

```powershell
$env:PYTHONPATH=(Resolve-Path ".python_packages").Path
python -m pytest tests
python src/demo_run.py
```

如果本机 Python 未安装依赖，但 `.python_packages` 存在，优先通过 `PYTHONPATH` 使用本地依赖目录。

### 输出

- 当前基线说明。
- 当前可运行命令。
- 当前失败点或缺失依赖。

### 验收标准

- 能说明当前 demo 如何从边表生成路径。
- 能说明当前哪些数据只是预留。
- 测试结果或失败原因有记录。

## 6. 阶段 1：数据审计和数据声明

### 目标

在任何 JSON 数据进入路径图之前，先完成数据结构、字段、单位、重复、缺失和异常的审计。

### 输入

通过环境变量 `DATA_DIR` 指定本地 JSON 数据目录。

当前审计目标包括：

- `运价表.json`
- `地点经纬度.json`
- `其他费用表.json`

### 操作

1. 扫描 `DATA_DIR` 下全部 JSON 文件。
2. 判断文件结构类型。
3. 统计记录数、字段名、字段类型和缺失率。
4. 统计运输方式、费用单位、包装方式、适用品种。
5. 检查始发、到达、地点名称别名。
6. 检查重复记录。
7. 检查费用负数、零值、字符串、异常值。
8. 检查维护日期格式。
9. 判断哪些字段可形成运输边，哪些只能作为补充表。

### 推荐命令

```powershell
$env:DATA_DIR=(Resolve-Path "..\..\坐标信息与部分客户信息数据\fee_switch").Path
$env:PYTHONPATH=(Resolve-Path ".python_packages").Path
python -m src.data_audit
```

### 输出

- `docs/data_usage_report.md`
- `output/data_quality_summary.csv`

### 验收标准

- 所有 JSON 文件有清单。
- 每个文件有结构类型和记录数。
- 关键字段取值有统计。
- 明确说明哪些数据可以形成候选边。
- 明确说明哪些数据不能直接进入路径搜索。

### 禁止事项

- 禁止在完成数据审计前把 JSON 记录写入图。
- 禁止把 `运价表.json` 中的原始费用直接作为 `cost`。
- 禁止把 `地点经纬度.json` 当作运输边。

## 7. 阶段 2：节点标准化

### 目标

建立统一节点体系，解决地点名称和 `node_id` 的关系。

### 输入

- `地点经纬度.json`
- `运价表.json` 中的 `始发`、`到达`
- 后续客户表中的客户工厂、自有码头

### 核心规则

- 同一个物理地点只能对应一个 `node_id`。
- 第一阶段终点“南方港口”和第二阶段起点“南方港口”必须是同一个物理节点，必须使用同一个 `node_id` 和同一组经纬度。
- 别名只能映射到标准节点，不能作为独立节点直接参与路径搜索。

### 建议输出

后续可以新增标准节点表，例如：

```text
data/standard_nodes.jsonl
```

建议字段：

| 字段 | 说明 |
|---|---|
| `node_id` | 标准节点编号 |
| `node_name` | 标准节点名称 |
| `node_type` | 港口、码头、铁路站、客户工厂、仓库 |
| `longitude` | 经度 |
| `latitude` | 纬度 |
| `aliases` | 别名 |
| `source_file` | 来源文件 |
| `is_active` | 是否启用 |

### 验收标准

- 能从名称找到唯一标准节点。
- 发现别名时有映射规则。
- 南方港口没有重复建点。
- 缺失坐标的地点有明确标记。

## 8. 阶段 3：订单请求结构和单位校验

### 目标

定义用户输入的订单请求，确保费用单位能正确换算。

### 建议结构

`RouteRequest` 至少包含：

| 字段 | 说明 |
|---|---|
| `origin_port_id` | 北方起运港节点 |
| `south_port_id` | 南方港口节点 |
| `customer_id` | 客户编号 |
| `commodity` | 货物品种 |
| `package_type` | 包装方式，例如散粮、集装箱 |
| `quantity` | 用户输入数量 |
| `quantity_unit` | 数量单位，例如吨、箱、柜 |
| `shipping_price_mode` | 散船价格模式：指数测算或人工报价 |
| `shipping_time_hours` | 人工输入散船运时 |

### 单位校验规则

运价单位可以不完全统一，但用户输入数量单位必须与运价单位匹配。

| 用户输入 | 运价单位 | 处理 |
|---|---|---|
| `500 吨` | `元/吨` | 接受 |
| `500 箱` | `元/箱` | 接受 |
| `500 柜` | `元/柜` | 接受 |
| `500 吨` | `元/箱` | 拒绝 |
| `500 箱` | `元/吨` | 拒绝 |

### 输出

- 单位匹配通过的 `RouteRequest`。
- 或清晰错误提示，例如：`订单数量单位为 吨，但运价单位为 元/箱，不能直接计算总费用。`

### 验收标准

- 不匹配单位会被拒绝。
- 匹配单位能计算出总费用，单位为元。
- 费用换算失败时不会进入路径搜索。

## 9. 阶段 4：费率标准化和费用换算

### 目标

把原始运价和附加费用标准化为可计算的 `FreightRate`，并在进入图之前换算为当前订单该运输段总费用。

### 需要支持的费用来源

1. 散船指数测算：

```text
单位运费 = 煤炭指数 × 1.12 + 2 元港驶费 + 5 元利润
总运费 = 单位运费 × 计费数量
```

2. 散船人工报价：

必须显式区分：

```text
price_type = unit_price
price_type = total_price
```

并记录费用单位。

3. 运价表台账：

`运价表.json` 中的 `费用` 和 `费用单位`。

4. 其他费用：

`其他费用表.json` 中的作业费、提柜费、装卸费、过闸费等。

5. 最后一公里汽运：

先判断南港到客户工厂是否在既定路线库中。

- 如果存在既定路线运价，取维护好的确切运费。
- 如果同一路线多次维护，以最新时间标签对应的运价为准。
- 如果不存在既定运价，按陌生路线规则计费，并使用腾讯地图 API 公路距离作为距离来源。
- 当前阶段不直接实现腾讯地图 API，应先预留独立距离 Provider。

陌生路线散粮规则：

| 距离范围 | 计费规则 |
|---|---|
| `X <= 20 公里` | `15 元/吨` 一口价 |
| `20 < X <= 30 公里` | `20 元/吨` 一口价 |
| `30 < X <= 100 公里` | `0.5 元/吨/公里 × X` |
| `100 < X <= 150 公里` | `0.4 元/吨/公里 × X` |
| `X > 150 公里` | `0.3 元/吨/公里 × X` |

陌生路线集装箱规则：

| 距离范围 | 计费规则 |
|---|---|
| `X <= 20 公里` | `500 元/箱` |
| `X > 20 公里` | `500 - (X - 20) × 30 × 0.55 元/箱` |

集装箱可按 `Y / 30` 折合为 `元/吨`。该 `30 吨/箱` 口径和 `X > 20` 公式方向需要在正式实现前再次确认。

### 建议结构

`FreightRate` 至少包含：

| 字段 | 说明 |
|---|---|
| `rate_id` | 费率编号 |
| `from_node_id` | 起点节点 |
| `to_node_id` | 终点节点 |
| `transport_mode` | 运输方式 |
| `package_type` | 包装方式 |
| `commodity_scope` | 适用品种 |
| `raw_price` | 原始价格 |
| `raw_price_unit` | 原始费用单位 |
| `price_type` | unit_price 或 total_price |
| `normalized_total_cost` | 换算后的运输段总费用，单位元 |
| `price_source` | 价格来源 |
| `maintained_date` | 维护日期 |

### 验收标准

- 所有进入图的费用均已换算为元。
- 原始价格、原始单位、价格来源仍可追溯。
- 不支持的单位有清晰异常。
- 缺少订单数量时不会计算总费用。
- 熟悉线路能取最新维护的既定运价。
- 陌生路线能按包装方式选择散粮或集装箱规则。
- 腾讯地图距离调用未实现前，不应在业务代码里直接调用外部 API。

## 10. 阶段 5：时间 Provider 设计

### 目标

统一运输时间来源，保证路径搜索中的 `time` 使用同一内部单位。

### 内部单位

建议统一为：

```text
小时
```

### 接口设计

必须设计统一 `ShippingTimeProvider` 接口。

当前启用：

```text
ManualShippingTimeProvider
```

预留但暂不启用：

```text
JsonShippingTimeProvider
DatabaseShippingTimeProvider
ApiShippingTimeProvider
```

### 停止条件

如果需要外部数据库或 API 才能实现时间接口，应停止并汇报，不自行假设接口格式。

### 验收标准

- 散船运时可人工输入。
- 时间来源可被记录。
- 缺少时间时不会错误输出可靠的时效最优路径。

## 11. 阶段 6：客户画像和业务规则过滤

### 目标

根据客户是否有自有码头、包装方式、适用品种等业务条件过滤不可行路径。

### 建议结构

`CustomerProfile` 至少包含：

| 字段 | 说明 |
|---|---|
| `customer_id` | 客户编号 |
| `customer_name` | 客户名称 |
| `factory_node_id` | 工厂节点 |
| `has_private_terminal` | 是否有自有码头 |
| `private_terminal_node_id` | 自有码头节点 |
| `allowed_package_types` | 支持包装方式 |
| `allowed_commodities` | 支持品种 |

### 第二阶段水路链规则

如果客户有自有码头：

```text
南港 → 客户自有码头 → 完成交付
```

不得再经过中转港。

如果客户没有自有码头：

```text
南港 → 候选中转港 → 短途汽运 → 客户工厂
```

候选中转港不能只按直线距离确定。允许先按距离筛选前 K 个候选港，再分别计算总费用和总时间。

### 验收标准

- 有自有码头客户不会生成中转港路线。
- 无自有码头客户不会生成自有码头直达路线。
- 候选中转港有可解释筛选过程。

## 12. 阶段 7：候选边生成

### 目标

把标准节点、费率、订单和客户规则组合成候选 `TransportEdge`。

### 建议结构

`TransportEdge` 至少包含：

| 字段 | 说明 |
|---|---|
| `edge_id` | 边编号 |
| `from_node_id` | 起点 |
| `to_node_id` | 终点 |
| `transport_mode` | 运输方式 |
| `package_type` | 包装方式 |
| `commodity` | 适用品种 |
| `cost` | 当前订单该段总费用，单位元 |
| `time_hours` | 当前订单该段耗时，单位小时 |
| `raw_price` | 原始价格 |
| `raw_price_unit` | 原始费用单位 |
| `price_source` | 价格来源 |
| `maintained_at` | 运价维护时间 |
| `distance_source` | 距离来源，例如既定路线、腾讯地图 API、人工维护 |
| `time_source` | 时间来源 |
| `is_available` | 是否可用 |
| `unavailable_reason` | 不可用原因 |

### 验收标准

- 每条候选边都能解释费用来源和时间来源。
- 缺少费用或时间的边不会静默进入正式推荐。
- 同一始发到达之间允许存在多条候选边。
- 最后一公里汽运边能说明采用的是既定路线运价还是陌生路线规则计价。

## 13. 阶段 8：图结构升级

### 目标

评估并优先使用 `nx.MultiDiGraph`，避免同一节点对之间的多条运输边互相覆盖。

### 原因

同一始发和到达之间可能存在：

- 不同运输方式。
- 不同包装方式。
- 不同价格来源。
- 不同费用单位。
- 不同维护日期。

`nx.DiGraph` 默认同一对节点只保留一条边，不适合作为长期结构。

### 验收标准

- 图中同一 `from_node_id -> to_node_id` 可以保留多条边。
- 路径结果不仅返回节点列表，还返回具体 edge key。
- 每段结果保留费用、时间、运输方式、包装方式、价格来源。

## 14. 阶段 9：路径搜索策略封装

### 目标

保留统一 `RouteSearchStrategy` 接口，先使用 NetworkX Dijkstra 作为基线实现。

### 必须保留两套权重

```text
cost = 当前订单该运输段总费用
time = 当前订单该运输段总耗时
```

### 禁止事项

- 禁止在没有业务权重系数时把 cost 和 time 合并成综合权重。
- 禁止只输出节点列表，不输出具体边。

### 算法边界

当前搜索算法暂不限定。可以先保留 NetworkX Dijkstra。

如果后续需要复现毕业论文或毕业论文源代码“残疾人地铁换乘站点推断和模式分析”中的算法，必须停止开发并明确提出需要的文件，不能自行假设算法内容。

### 验收标准

- 能分别输出成本最低路径。
- 能分别输出时效最优路径。
- 两条路径可以不同。
- 每条路径有分段明细。

## 15. 阶段 10：结果输出和解释字段

### 目标

输出可解释路径，而不是只输出最终价格。

### 建议结构

`RouteSegment` 至少包含：

| 字段 | 说明 |
|---|---|
| `segment_no` | 分段序号 |
| `from_node_id` | 起点节点 |
| `to_node_id` | 终点节点 |
| `edge_key` | MultiDiGraph 边 key |
| `transport_mode` | 运输方式 |
| `package_type` | 包装方式 |
| `cost` | 本段费用，单位元 |
| `time_hours` | 本段耗时，单位小时 |
| `raw_price` | 原始价格 |
| `raw_price_unit` | 原始单位 |
| `price_source` | 价格来源 |
| `time_source` | 时间来源 |

`RouteResult` 至少包含：

| 字段 | 说明 |
|---|---|
| `recommendation_type` | 成本最低或时效最优 |
| `segments` | 分段列表 |
| `total_cost` | 总费用，单位元 |
| `total_time_hours` | 总耗时，单位小时 |
| `missing_data_flag` | 是否存在缺失数据 |
| `explanation` | 结果解释 |

### 验收标准

- 输出能说明为什么选择该路径。
- 总费用由分段费用相加得到。
- 总时间由分段时间相加得到。
- 所有费用和时间来源可追溯。

## 16. 阶段 11：测试、演示和汇报材料

### 测试要求

每个阶段至少补充对应 pytest。

必须覆盖：

- JSONL 读取。
- 数据审计。
- 单位匹配。
- 费用换算。
- 散船指数测算。
- 散船人工报价 unit_price / total_price。
- 时间 Provider。
- 最后一公里既定路线优先。
- 同一路线多次维护时取最新运价。
- 陌生路线散粮阶梯计费。
- 陌生路线集装箱计费。
- 客户自有码头过滤。
- MultiDiGraph 多边保留。
- cost/time 分别搜索。

### 推荐命令

```powershell
$env:PYTHONPATH=(Resolve-Path ".python_packages").Path
python -m pytest tests
```

### 演示要求

每次演示至少准备：

- 输入订单。
- 使用的数据文件。
- 生成的候选边数量。
- 被过滤的边和原因。
- 成本最低路径。
- 时效最优路径。
- 每段费用和时间来源。

### 汇报要求

每完成一个阶段后，向用户汇报：

- 完成了什么。
- 改了哪些文件。
- 运行了哪些命令。
- 测试是否通过。
- 还有哪些业务口径未确认。

## 17. 开发纪律

### 必须遵守

- 不硬编码 D 盘业务路径，数据目录通过 `DATA_DIR` 配置。
- 不在未审计数据上直接构图。
- 不把不同费用单位的原始数值直接相加。
- 不把缺失费用或缺失时间默认为 0。
- 不重复创建同一物理南方港口节点。
- 不把成本和时间合并成综合权重。
- 不在没有业务确认时自行编造费用规则。
- 不在未封装 Provider 的情况下把腾讯地图 API 调用直接写入业务计费逻辑。
- 不在集装箱 20 公里以上公式未复核前用于正式推荐。

### 允许保留为占位

- 数据库接口。
- 外部 API。
- 前端页面。
- 生产部署。
- 复杂路径算法。

占位模块必须明确标注“预留，当前未启用”。

## 18. 推荐文件组织

后续建议逐步演进为以下结构：

```text
src/
  data_audit.py
  data_loaders.py
  models.py
  node_registry.py
  unit_conversion.py
  freight_rates.py
  time_providers.py
  business_rules.py
  edge_builder.py
  graph_builder.py
  search_strategy.py
  route_planner.py
  exporters.py
  demo_run.py

docs/
  development_sop.md
  data_usage_report.md
  data_flow_and_unit_statement.md

output/
  data_quality_summary.csv
  route_results.csv

tests/
  test_data_audit.py
  test_unit_conversion.py
  test_freight_rates.py
  test_time_providers.py
  test_business_rules.py
  test_graph_builder.py
  test_route_search.py
```

该结构是建议路线，不要求一次性重构完成。

## 19. 下一步建议

下一步不应直接改路径搜索，而应先做以下最小阶段：

1. 新增 `unit_conversion.py`，实现订单数量单位和运价单位匹配校验。
2. 为 `元/吨`、`元/箱`、`元/柜` 建立明确换算规则。
3. 为不匹配单位返回清晰异常。
4. 补充 `test_unit_conversion.py`。
5. 汇报后再进入 `FreightRate` 标准化。

这样可以先解决当前业务上最关键的风险：不同费用单位不能直接相加。
