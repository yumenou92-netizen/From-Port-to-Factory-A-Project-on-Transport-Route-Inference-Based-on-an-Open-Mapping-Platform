# From Port to Factory: A Project on Transport Route Inference Based on an Open Mapping Platform
#README MAIN DOCUNMENT 07-10 by Menou

#北港-南港-客户工厂全链运输路线推断系统

## 1. 工程定位

本工程不是商业级生产系统。目标是在Codex的辅助下用 Python 先验证“北方港口—南方港口—客户工厂”全运输链条的路径生成、费用计算、时效排序是否可行。

当前开发者身份为交通工程方向研一实习生，具备基础加权图最短路径理解能力，但无数据库、前端、后端生产系统经验。因此，本工程应优先采用：

- Excel / CSV 作为临时数据源；
- `pandas` 读取台账；
- `networkx` 构建有向加权图；
- 函数式费用规则计算；
- 输出 JSON / Excel / CSV 结果；
- 暂不接入正式数据库和生产前端；当前仅提供复用同一模型的本地领导展示页。

## 2.开发总目标

逐步实现一个 Python 原型，完成以下能力：

1. 读取节点、边、客户、散船价格、铁路费用等 CSV 数据；
2. 构建有向加权运输网络；
3. 支持散船两种计价模式：指数测算、线下询价；
4. 支持铁路费用细化：始发站作业费、铁路运费、下站费、短途拖车费、敞顶箱返篷布费用；
5. 根据客户是否有自建码头过滤不可行路径；
6. 分别以 `cost` 和 `time` 为权重求最短路径；
7. 输出成本最低方案和时效最优方案；
8. 输出每条路径的分段明细。

## 3. 开发顺序

1. 建立数据模型：Node、Edge、Customer、RouteSegment、RouteResult；
2. 实现费用规则：散船、铁路、汽运、码头费用；
3. 通过可替换 Loader/Provider 读取本地数据，未来数据库适配器复用同一领域契约；
4. 构建保留平行运输边的 `networkx.MultiDiGraph`；
5. 实现最短路径搜索；
6. 实现路径明细拆解；
7. 实现结果导出；
8. 再考虑配置、测试和接口化。

## 4. 重要边界

本项目不是及不包含：

- 商业级最短路径检索；
- 数据库生产部署；
- 生产前端、账号权限和公网服务；
- 高并发接口服务；
- 自动海运里程获取；
- 正式报价责任。

本README编写于7-10-2026，项目最新变化和结构以文件提交时间为准。

当前阶段只做“可解释的规则型路径推断原型”。

## 4.1 长期运输网络口径

全链路只定义两个业务运输段：

1. `北港 -> 南港`；
2. `南港 -> 客户工厂`。

业务运输段不等于一条图边。第一段当前优先实现散船，但未来可以加入集装箱船和其他运输方式；第二段是一个可包含多个中转节点和多种运输方式的子路径搜索问题，可以由汽运、驳船、铁路及其组合构成。军航码头、南平港等具体节点只属于当前数据支持的示例路线，不是长期架构中的固定节点。

正式边分别记录业务运输段、运输方式和图边角色。当前契约中，业务运输段为 `north_to_south` / `south_to_customer`，图边角色为 `trunk` / `transfer` / `delivery`，运输方式继续保留散船、驳船、汽运、铁路等业务值。

`leader_full_flow.py` 和本地 Web 页面已经验证的输入、输出、费用分项、提示/错误和地图信息属于领导确认的产品 IO 口径，后续重构必须保留。领导不指定模型的具体推断算法；候选生成、Provider、图结构和搜索实现由工程侧在业务规则下独立设计。正确方向是正式能力和界面无关的路线规划服务供 CLI Demo/Web 调用，Demo 负责展示能力，不得为了固定演示路线反向定义主代码。

当前界面无关应用层已包含统一请求/响应契约，以及独立的南港选择模块 `src/application/south_port_selection.py`。CLI 和 Web 共享同一份结构化候选决策，逐节点记录身份筛选、排序、散船干线、码头作业费、第二业务段和最终入图状态；展示层只负责格式化，不重新计算候选资格。

## 5. 开发者测试入口

面向开发者的统一冒烟测试入口：

```powershell
python -B -m src.dev.smoke_test
```

该入口会读取本地运行配置、注入环境变量、运行全量 pytest，并在配置齐全时额外运行真实数据链路验证。腾讯地图公开点探针默认不调用，需要显式设置。

本地配置文件：

```text
local_env/runtime_env.csv
```

该文件不提交 GitHub。可从模板复制：

```text
config/runtime_env.example.csv
```

当前已知未完成项：项目级 `pytest.ini` 临时目录配置今天先跳过；开发者 smoke 入口内部已使用项目本地临时目录规避 Windows 默认 pytest 临时目录权限问题。

## 6. 第一版全流程领导 Demo

```powershell
python -B -m src.demos.leader full-flow
```

按提示输入北港点 A 和客户工厂 B。程序优先使用本地真实节点、真实维护运价、腾讯地图普通驾车距离/时间和已确认计费规则，构建正式 `MultiDiGraph`，分别输出费用最低与时间最短路线。当前 Demo 已展示直接汽运以及一条闽江驳船中转实例，但 Demo 中出现的路线结构不代表第二业务运输段只允许这些组合。

北港至南港散船费用和完整运输段时效已使用正式业务表和已确认分区规则；南港码头作业费优先使用精确数据，空缺时可使用带参考港、距离和区域追溯的 `regional_proxy`。当前仍需显式标记的占位主要是“客户无自有码头”演示画像，以及正式端点能力未齐时的驳船能力标签。AdditionalFee 在归属未确认前不计入。API Key 仅从本地 `local_env/runtime_env.csv` 读取，不打印、不提交。

南港身份当前可由明确海港/海河双用角色，或适用当前品种的散粮始发运价证据支持；已确认纯内河港、铁路站、客户设施和显式散粮能力排除始终优先。仅出现集装箱始发运价的港口不作为散粮南港，只进入“潜在中转港待确认”范围。W3 港口能力表另设三态 `is_transfer_port`：只有明确为真时，节点才能作为第二业务段的中转端点；空值表示未知，不自动构边。

也可以在预演时直接传入地点（`北港实际名称`、`客户工厂实际名称` 必须替换为腾讯地图可检索的真实业务名称，不是可直接运行的固定示例值）：

```powershell
python -B -m src.demos.leader full-flow --origin "北港实际名称" --destination "客户工厂实际名称" --region "全国"
```

如果领导已指定南港，可将候选范围固定为一个已注册标准南港：

```powershell
python -B -m src.demos.leader full-flow --origin "北港实际名称" --destination "客户工厂实际名称" --south-port "南港标准名称" --region "全国"
```

## 7. 本地腾讯地图展示页

```powershell
python -X utf8 -B -m src.web.server --host 127.0.0.1 --port 8765
```

浏览器打开：

```text
http://127.0.0.1:8765
```

页面可输入北港、客户工厂、可选南港、粮食品种、包装方式、重量、计费单位和贸易类型，并展示费用最低/时间最短路线、分段费用组成、候选与运行提示。页面调用的仍是 `leader_full_flow` 正式 `MultiDiGraph`/双目标主链，不另写一套计费算法，也不以图上的第一条边或固定节点数量推断业务运输段。

腾讯地图浏览器 Key 优先读取本地 `TENCENT_MAP_JS_KEY`；未配置时复用 `TENCENT_MAP_API_KEY`。当前用户已确认本地 Key 同时具备 JavaScript API 和 WebService API 权限，并已完成地图底图与后端路线调用实测。Key 不写入前端源码。地图按运输段分别绘制：北港至南港散船使用贴近中国大陆沿海的近海虚线示意，广西方向经琼州海峡进入北部湾，不代表真实航道；南港至客户的汽运使用与本次距离/时效测算相同的腾讯驾车响应折线。腾讯未返回折线时只保留测算结果并提示，不用端点直线冒充真实道路。服务默认只监听本机回环地址；数据库、鉴权、部署和生产 API 不在当前阶段。

## Developer Feature Demo

```powershell
python -B -m src.dev.feature_demo
```

This demo is for code understanding and daily feature review. When a core
feature changes, update `src/dev/feature_demo.py` in the same commit so the
current model behavior can be inspected from one stable entry. Use
`src.dev.smoke_test` for pass/fail verification; use `src.dev.feature_demo` for
human-readable behavior display. Tencent Maps is not called by this feature
demo.

### Order and port admission audit

```powershell
python -B -m src.demos.order_graph_admission_audit
```

This read-only audit derives the commodities present in the freight data,
all legal package/unit pairs, both trade types, and the current bulk-vessel
capacity boundaries. It checks current freight-rate origins and registered
nodes whose names have port-like characteristics, so both automatic selection
and explicit south-port preconditions can be reviewed. Names containing `站`
or ending in a place-direction form are treated as railway stations; names
containing `库`, `仓`, or `公司` are treated as customer facilities. A
customer-owned terminal must be maintained as a separate port/terminal node.
The remaining name test is still a compatibility heuristic, not an authoritative
port-role label. Outputs are written under ignored `output/`; the main human-review file
is `output/order_graph_manual_review.csv`. The audit does not call Tencent,
does not write real data, and does not claim that an offline-ready port has
already formed a customer-specific truck or barge edge.

The separate data-foundation audit keeps CSV schemas even when a formal table
currently contains zero rows. In particular,
`data_foundation_port_capabilities.csv` still exposes the W3
`is_transfer_port` field so a data-platform or manual-maintenance handoff does
not depend on inferred columns.

### Missing-node coordinate review

```powershell
# Build a deduplicated local review list; does not call an API or write business data.
python -B -m src.demos.node_coordinate_backfill

# In the user's PyCharm environment only: query Tencent candidates for human review.
python -B -m src.demos.node_coordinate_backfill --query-tencent --region "全国"
```

The list is written to `output/node_coordinate_backfill_review.jsonl`. Each row
keeps the raw business name as the first Tencent query and, when the local
`名称字典.xlsx` has an explicit full-name/short-name pair, adds the full name as a
parallel query for human comparison. The JSONL fields `query_names` and
`coordinate_resolutions` preserve every query result and its candidate trace.
The dictionary never supplies a missing coordinate or automatically merges two
existing nodes. After human review, approved coordinates can be written to the
local `地点经纬度.json` under the separate data-governance process.
