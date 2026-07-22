# 2026-07-20 模块验收记录

本文记录代码理解与测试阶段的模块验收结果。它是开发验收记录，不是领导汇报稿。

记录格式固定为：

- 测试命令；
- 结果；
- 是否通过；
- 问题或疑问；
- 是否需要业务确认。

## 1. 主链路：真实数据 smoke

测试命令：

```powershell
python -B -m src.dev.smoke_test --skip-pytest
```

结果：

- `real-data smoke: passed`
- 运价记录：492 条。
- 标准地点坐标：263 条。
- 节点附加费用记录：18 条。
- 已完成计费候选运输段：314 条。
- 两端节点齐全、可进入正式图候选：144 条。
- 缺少标准节点 ID 候选：170 条。
- 人工复核记录：27 条。
- 已构建 TransportEdge：314 条。
- 可进入正式搜索图 TransportEdge：144 条。
- 仍需人工复核 TransportEdge：170 条。
- 正式图新增边：144 条。
- 正式图排除边：0 条。
- 本地演示人工时间已设置时，成本最低和时效最优两类搜索均返回 `resolved`。

是否通过：

- 通过。

问题或疑问：

- 当前 `REAL_DATA_DEMO_MANUAL_TIME_HOURS` 只用于链路验收，不能作为真实业务运输时效。
- `Defaulted_Maintenance_Dates=299` 是最新运价筛选阶段全量口径；候选 CSV 中 `maintenance_date_defaulted=True` 为 164 行，是最终计费候选行口径。二者不是矛盾。

是否需要业务确认：

- 需要。正式自动化仍需确认运输时效来源、客户自有码头字段、北港至南港数据、AdditionalFee 归属、缺节点 ID 的补齐方式。

## 2. 主链路：输出 CSV

测试命令：

```powershell
python -B -m src.dev.smoke_test --skip-pytest
```

检查文件：

- `output/real_data_edge_candidates.csv`
- `output/real_data_edge_reviews.csv`
- `output/real_data_route_recommendations.csv`

结果：

- `real_data_edge_candidates.csv` 存在，314 行；双端节点齐全 144 行，缺节点 ID 170 行；`total_cost` 和 `source_row_number` 均非空。
- `real_data_edge_reviews.csv` 存在，27 行；`validation_status` 全部为 `manual_review`，`validation_scope` 全部为 `freight_rate`。
- `real_data_route_recommendations.csv` 存在，2 行；包含 `lowest_cost` 和 `fastest_time` 各 1 行；`status` 均为 `resolved`，`missing_data_flag` 均为 `False`。

是否通过：

- 通过。

问题或疑问：

- CSV 内容仍包含真实业务数据，只能保留在本地 `output/`，不得提交到 Git。
- 路线推荐 CSV 的 2 行是基于本地演示人工时间的链路验证结果，不代表真实生产推荐。

是否需要业务确认：

- 需要。CSV 中人工复核原因需要后续由业务确认处理优先级，尤其是同一路线同维护日期价格冲突、系统基准日期价格冲突、订单单位与运价单位不匹配。

## 3. No-path：既有点但不存在既有路线

测试命令：

```powershell
python -B -m src.dev.smoke_test --pytest-target tests/test_route_search.py --pytest-target tests/test_route_result.py --skip-real-data
```

结果：

- `22 passed`
- 最小样例确认：
  - `search_status=no_path`
  - `result_status=no_path`
  - `missing_data_flag=False`
  - `total_cost_yuan=None`

是否通过：

- 通过。

问题或疑问：

- 当前行为符合设计：系统不会猜测路线，不会把缺失费用或时间补 0。

是否需要业务确认：

- 暂不需要。该模块属于工程安全边界，当前结论可以作为后续验收基线。

## 4. Tencent 地点多候选策略

测试命令：

```powershell
python -B -m src.dev.smoke_test --pytest-target tests/test_tencent_map_provider.py --pytest-target tests/test_tencent_map_probe.py --pytest-target tests/test_coordinate_provider.py --skip-real-data
```

结果：

- `17 passed`
- 多候选默认自动选择 top1。
- `source_confidence` 区分：
  - `auto_top1_name_match`
  - `auto_top1_nearby_cluster`
  - `auto_top1_unclustered`
- resolved 结果保留 top 5 候选追溯。

是否通过：

- 单元测试通过。

问题或疑问：

- Codex 环境访问腾讯地图仍返回 `ConnectionError`，真实 API 结果需要用户在 PyCharm/venv 中复测。
- 低置信 `auto_top1_unclustered` 是否需要抽检比例或人工复核表，尚未设计。

是否需要业务确认：

- 需要。需要确认低置信自动 top1 的抽检规则、缓存机制、人工修正回写表，以及真实业务 OD 点候选保存格式。

## 5. Demo 中文展示文本

测试命令：

```powershell
python -B -m src.dev.smoke_test --pytest-target tests/test_tencent_map_probe.py --pytest-target tests/test_tencent_map_provider.py --skip-real-data
python -B -m src.dev.smoke_test
```

结果：

- demo 相关测试：`12 passed`
- 全量开发者 smoke：`248 passed`
- 真实数据 demo、Tencent 探针和节点标准化 demo 的主要展示文本已改为中文。
- 内部状态码、环境变量和输出文件名保留英文，便于追溯和排查。

是否通过：

- 通过。

问题或疑问：

- Codex 控制台显示中文会有乱码，但文件本身 UTF-8 检查正常；用户在 PyCharm/Windows 终端中应以本机编码实际复核展示观感。

是否需要业务确认：

- 暂不需要业务规则确认，但需要用户从展示口径角度复看文本是否适合领导展示。

## 第三阶段结论检修清单

后续逐步检修第三阶段结论时，建议按以下顺序进行：

1. 候选数量口径：确认 314、144、170、27 是否在不同输出中一致。
2. 缺节点 ID：抽查 170 条缺节点候选，判断是节点表缺失、别名未绑定，还是真实数据命名不一致。
3. 人工复核 27 条：按复核原因分组，确认哪些能自动处理，哪些必须业务介入。
4. 正式图边数 144：确认进入图的边是否全部具备费用、节点、时间、来源追溯。
5. 路线推荐 2 行：确认只是本地演示人工时间下的链路验证，不作为真实业务推荐。
6. 阻断自动化原因：逐项确认正式运输时效、客户自有码头字段、北港至南港数据、AdditionalFee 归属和 OD 候选回写机制的负责人和数据来源。

## 6. 第一版全流程领导 Demo

测试命令：

```powershell
python -B -m src.dev.smoke_test --pytest-target tests/test_leader_full_flow.py --pytest-target tests/test_dev_feature_demo.py --skip-real-data
python -B -m src.dev.smoke_test
python -B -m src.demos.leader help
```

结果：

- 专项测试 `4 passed`。
- 全量测试 `251 passed`，真实数据 smoke 通过。
- `leader` 菜单已包含 `full-flow`。
- 集成测试验证真实维护运价优先、腾讯距离加陌生汽运规则、北港至南港占位、双目标搜索和逐段来源标记。

是否通过：

- 代码和自动化测试通过；PyCharm 真实 A/B 与腾讯 API 完整预演待用户执行。

问题或疑问：

- 当前北港至南港费用和时间是明确的 `demo_placeholder`，不能作为正式报价或真实业务时效。
- AdditionalFee 已加载但本次不计入。
- 真实输入地点是否能获得合适的腾讯 top1、以及三个候选南港的现场输出效果，需要在 PyCharm 预演。

是否需要业务确认：

- 三项占位边界已由用户确认。
- 后续正式化仍需北港至南港数据、客户自有码头字段和 AdditionalFee 归属规则。
