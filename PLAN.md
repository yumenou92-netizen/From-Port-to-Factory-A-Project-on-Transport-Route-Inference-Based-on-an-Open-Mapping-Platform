# PLAN.md

Updated: 2026-07-17

本文件记录真实工程里程碑。较早的日计划、领导汇报和 7 月 9 日 SOP 仅作为历史材料；与当前代码或本计划冲突时，以代码、测试、`docs/DECISIONS.md` 和本文件为准。

## 开发主线

```text
数据审计
-> 真实数据加载
-> 节点注册与坐标确认
-> 订单与单位校验
-> FreightRate 与 CostRuleEngine
-> 最新有效运价选择
-> ShippingTimeProvider
-> CustomerProfile 与路线分支
-> TransportEdge
-> MultiDiGraph
-> RouteSearchStrategy
-> RouteResult 与解释输出
```

在费用、时间、节点和运输边可解释之前，不把真实业务候选直接写入正式路径图。

## 里程碑状态

| 阶段 | 里程碑 | 状态 | 当前验收结果 |
|---|---|---|---|
| 0 | 持久化项目记忆 | 已完成 | `AGENTS.md`、`PLAN.md`、`PROJECT_STATE.md`、`ARCHITECTURE.md`、`DECISIONS.md`、`CHANGELOG.md` 已建立并持续维护 |
| 1 | JSON 数据审计与脱敏输出 | 已完成（第一版） | 可扫描 JSON/JSONL、统计字段与质量问题；详细输出留在 `output/`，提交报告保持脱敏 |
| 2 | 真实数据加载 | 已完成（第一版） | 从 `DATA_DIR` 读取运价、地点经纬度和其他费用表；提供明确的文件、JSON 和字段异常 |
| 3 | NodeRegistry | 已完成（第一版） | 稳定节点 ID、别名、坐标冲突和运价端点覆盖检查具有测试 |
| 4 | 坐标与地图 Provider | 已完成（基础版） | 本地优先坐标解析、腾讯地点搜索和普通驾车距离/时间 Provider 已实现；正式业务回写与缓存未完成 |
| 5 | RouteRequest 与单位校验 | 已完成（第一版） | `吨/箱/柜` 精确匹配；包装辅助验证；不匹配转人工复核 |
| 6 | FreightRate 与 CostRuleEngine | 已完成（第一版） | 单价、人工总价、散船指数、散船人工报价和熟悉汽运运价具有统一结果与追溯 |
| 7 | 最新有效运价选择 | 已完成（第一版） | 1970 比较基线、较新记录覆盖、同日冲突人工复核、完全重复去重均已实现 |
| 8 | ShippingTimeProvider | 已完成（第一版） | 已定义统一请求/结果结构；`ManualShippingTimeProvider` 支持小时、天、分钟换算；缺失、零值、负数、非数值和未配置 Provider 均不会生成可用时间 |
| 9 | CustomerProfile 与路线分支 | 已完成（第一版） | 已定义可追溯客户画像、未知/矛盾状态、两类互斥路线、包装/品种过滤和候选港前 K 距离预筛 |
| 10 | TransportEdge | 已完成（第一版） | 已统一节点、订单段总费用、小时制时间、原始价格、来源、规则版本、计算过程和可用状态；缺字段不产生可搜索边 |
| 11 | `nx.MultiDiGraph` 正式图 | 已完成（第一版） | `routing/transport_graph.py` 使用 edge ID 作为 key 保留平行边，排除不可用、重复和未知节点边，不使用 0 默认值 |
| 12 | RouteSearchStrategy | 已完成（第一版） | NetworkX Dijkstra 分别搜索成本最低和时效最优路径，显式返回节点和每段 edge key |
| 13 | RouteResult 与解释输出 | 已完成（第一版） | 已输出分段费用、时间、方式、来源、规则、计算过程、总费用、总时间及人工复核/无路径状态 |
| 14 | 代码结构整理与旧原型剥离 | 已完成（第一版） | `src` 已按 `data/domain/geo/routing/demos` 分包；旧 CSV/DiGraph 原型代码和重复 demo 已剥离；演示入口改为 `python -m src.demos.leader` |
| 15 | 真实 EdgeCandidate 接入正式链 | 已完成（保守第一版） | `routing/real_data_bridge.py` 可将已计费候选在显式人工时间下转换为 `TransportEdge`，进入 MultiDiGraph 并执行 cost/time 搜索；缺时间或缺节点仍转人工复核 |

## 当前阶段

当前位于阶段 15 保守第一版完成、真实业务候选可在显式人工时间下接入正式图的确认点。

模型和算法基线已经贯通：

```text
CustomerProfile
-> TransportEdge
-> nx.MultiDiGraph
-> cost / time 独立 Dijkstra
-> RouteSegment / RouteResult
```

下一步不是继续扩展抽象模型，而是取得缺失业务数据并把真实候选生成链从“演示人工时间”推进到正式业务输入：

1. 确认客户自有码头字段、码头节点和允许包装/品种的正式数据源；
2. 提供北港至南港散船费用与运输时间，或确认第一批只覆盖南港至客户工厂；
3. 将 `src/demos/real_data_run.py` 中的本地演示人工时间替换为正式运输时间来源；
4. 对接前先解决真实运价端点缺节点和其他费用是否计入运输段的问题。

## 已完成阶段：ShippingTimeProvider

### 目标

建立统一运输时间接口，第一版只启用人工输入，所有内部时间使用小时。

### 计划文件

- `src/routing/shipping_time_provider.py`
- `tests/test_shipping_time_provider.py`
- `src/demos/leader_shipping_time.py`
- `src/demos/leader.py`

### 接口要求

- 已定义统一的请求和结果结构；
- `ManualShippingTimeProvider` 接受正数时间并返回小时；
- 支持小时、天和分钟换算为内部小时；
- 缺失、零值、负数、非数值和不支持单位均转人工复核；
- 已预留但不启用 `JsonShippingTimeProvider`、`DatabaseShippingTimeProvider`、`ApiShippingTimeProvider`；
- 占位 Provider 被调用时明确说明未配置，不返回 0；
- 不把腾讯普通驾车时间直接等同于散船或完整运输作业时间。

### 验收标准

- 正常人工输入、单位转换、缺失和非法输入均有测试；
- 全量 pytest 通过；
- `python -m src.demos.leader shipping-time` 能解释当前来源和未接入来源；
- 项目状态、架构、决策和变更记录已同步；
- 敏感信息检查通过。

## 已完成阶段：正式路线模型与搜索

### CustomerProfile

- `src/routing/customer_profile.py` 定义客户 ID、工厂节点、自有码头标志、自有码头节点、允许包装/品种和来源；
- 未知标志、缺少来源、缺码头节点和字段矛盾均返回 `manual_review`；
- 有自有码头客户不生成中转港路线，无自有码头客户不生成自有码头直达路线；
- `prefilter_transfer_ports()` 只按确认距离筛前 K，结果明确要求继续比较总费用和总时间。

### TransportEdge

`src/routing/transport_edge.py` 已包含：

- `edge_id` / edge key；
- `from_node_id`、`to_node_id`；
- `transport_mode`、`packaging`；
- 当前订单运输段总费用（元）；
- 运输时间（小时）；
- 原始价格、单位、价格来源和维护日期；
- 距离及其来源；
- 计费规则编号、版本和计算过程；
- 数据来源、人工复核原因和可用状态。

只有 `status="available"` 的边可以导出正式图；费用、时间、节点或追溯字段缺失时保留候选和原因，但不进入搜索。

### MultiDiGraph 与搜索

- `src/routing/transport_graph.py` 使用 `nx.MultiDiGraph`，不复用旧 `DiGraph` 作为正式业务图；
- 正式建图默认必须提供 `NodeRegistry`；仅脱敏演示和单元测试可显式允许未注册节点；
- 建图排除项会保留在图元数据中，并阻止输出错误的“已解决”推荐；
- `src/routing/route_search.py` 提供 `RouteSearchStrategy` 协议和 NetworkX Dijkstra 基线；
- 成本和时间分别搜索，不创建未经确认的综合权重；
- 缺节点、缺权重、同起终点和无路径均有显式状态；
- 搜索结果绑定目标权重图签名，搜索后图发生变化时必须重新搜索；
- `src/routing/route_result.py` 返回节点、edge key、完整分段信息和严格分段求和结果；
- 无路径和人工复核结果导出时保留一条状态行，不再从表格结果中消失；
- `python -m src.demos.leader route-search` 可运行脱敏集成演示。

### 验收结果

- 阶段 9-13 新增 67 个 pytest 场景；
- 全量测试：`217 passed in 1.00s`；
- 领导演示：`customer-profile`、`transport-edge`、`transport-graph`、`route-search` 均可运行；
- 真实业务数据尚未写入正式图，本次演示全部使用虚构节点和脱敏字段。

## 已完成阶段：代码结构整理与旧原型剥离

- `src/data`：真实数据加载、数据审计和本地输出工具；
- `src/domain`：订单、单位、节点、运价、最新运价和费用规则；
- `src/geo`：坐标、距离和腾讯地图 Provider；
- `src/routing`：客户画像、运输时间、运输边、正式图、搜索和结果解释；
- `src/demos`：领导展示、真实数据本地开发脚本和公开 API 探针；
- 旧 `models.py`、`graph_builder.py`、`route_planner.py` 和重复的 `demo_cost_rules.py` 已从 `src` 剥离。

## 已完成阶段：真实 EdgeCandidate 接入正式链

- `src/routing/real_data_bridge.py` 将 `EdgeCandidate` 转换为正式 `TransportEdge`；
- 转换只接受显式人工运输时间，默认缺时间时全部保留为 `manual_review`；
- 双端节点完整且有人工时间的候选可进入 `src/routing/transport_graph.py`、`src/routing/route_search.py` 和 `src/routing/route_result.py`；
- `src/demos/real_data_run.py` 默认只输出候选和人工复核；设置 `REAL_DATA_DEMO_MANUAL_TIME_HOURS` 后才运行本地正式图搜索验证；
- 真实验证中默认缺时间时 314 条候选全部人工复核；设置本地演示时间后 144 条双端节点候选进入正式图并完成 cost/time 搜索；
- 该演示时间只用于链路验证，不代表真实业务时效。

## 已知依赖与待确认项

- 北港至南港真实散船数据尚未提供；模型接口可先设计，但不得假设数据内容。
- 客户自有码头数据源尚未确认。
- 陌生散粮汽运 `draft-2` 已可在外部提供 `distance_km` 和 `distance_source` 时计算；费用层不直接调用地图 API。
- 陌生集装箱汽运 `draft-1` 已确认 20 公里内 500 元/箱、20 公里以上 `500 + (X - 20) * 30 * 0.55` 元/箱；不折吨，缺距离或缺来源仍人工复核。
- 真实运价 JSON 当前没有显式 `price_type`，加载器统一按 `unit_price` 解析；正式支持总价记录前必须扩展数据协议。
- 其他费用表已加载但尚未进入运输段总费用。
- 地图 API 获取的新坐标和路线结果尚未设计本地缓存及人工确认后的回写流程。

## 停止并确认条件

遇到以下情况先停止实现并向用户确认：

- 公式、区间边界、单位、方向或价格类型存在歧义；
- 需求与代码、测试或已确认决策冲突；
- 需要在 `吨`、`箱`、`柜` 之间换算；
- 需要使用尚未提供的北港至南港数据；
- 需要改变陌生集装箱汽运公式、单位或箱/柜换算口径；
- 需要复现毕业论文算法但论文或源代码未提供；
- 外部接口契约、权限或密钥管理方式不明确。
