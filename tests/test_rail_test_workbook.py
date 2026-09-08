from decimal import Decimal

from src.data.loaders import NodeRecord, make_node_id
from src.data.rail_test_workbook import build_confirmed_rail_test_rates
from src.domain.node_registry import build_node_registry
from src.domain.route_request import RouteRequest
from src.routing.rail_container_provider import TableRailContainerProvider


def _registry():
    return build_node_registry(
        (
            NodeRecord(make_node_id("白城北站"), "白城北站", 122.0, 46.0),
            NodeRecord(make_node_id("桂林西站"), "桂林西站", 110.2, 25.3),
            NodeRecord(make_node_id("马坝站"), "马坝站", 113.5, 24.7),
        ),
        auto_alias=False,
    )


def _rows(*data_rows):
    header = (
        "路线编号", "发站", "到站", "路线名称", "敞顶箱-历史",
        "敞顶箱-8.28查询", "到客户1费用", "到门1", "到客户2费用", "到门2",
    )
    return (header, *data_rows)


def test_confirmed_workbook_rates_convert_group_price_and_add_confirmed_components():
    result = build_confirmed_rail_test_rates(
        source="fixture.xlsx",
        route_rows=_rows((1, "白城北站", "桂林西站", "白城北站→桂林西站", None, 12000, "客户甲", None, "客户乙", None)),
        station_locations={"白城北": ("吉林省", "白城市"), "桂林西": ("广西壮族自治区", "桂林市")},
        node_registry=_registry(),
    )

    assert result.admitted_count == 1
    admission = result.admissions[0]
    assert admission.railway_freight_yuan_per_group == Decimal("12000")
    assert admission.railway_freight_yuan_per_box == Decimal("6000")
    assert admission.served_customer_names == ("客户甲", "客户乙")
    record = result.records[0]
    assert record.source_type == "real_data"
    assert record.base_freight_yuan_per_box == Decimal("6000")
    assert record.discount_ratio == Decimal("0")
    assert record.origin_station_fee_yuan_per_box == Decimal("136.5")
    assert record.destination_station_fee_yuan_per_box == Decimal("136.5")
    assert record.duration_hours == Decimal("192")
    assert record.tarpaulin_yuan_per_box == Decimal("250")
    edge, match = TableRailContainerProvider((record,)).build_edge(
        north_station_name="白城北站",
        south_station_name="桂林西站",
        request=RouteRequest(Decimal("2"), "箱", "集装箱", "玉米", trade_type="内贸"),
        container_type="敞顶箱",
    )
    assert match.status == "resolved"
    assert edge is not None
    assert edge.data_source.startswith("fixture.xlsx/")
    assert edge.cost_yuan == Decimal("13046.0")


def test_special_terminal_and_unregistered_north_remain_out_of_normal_station_records():
    result = build_confirmed_rail_test_rates(
        source="fixture.xlsx",
        route_rows=_rows(
            (1, "白城北站", "马坝站转中南专用线", "", None, 12000, "客户甲", None, None, None),
            (2, "未注册北站", "桂林西站", "", None, 12000, "客户乙", None, None, None),
        ),
        station_locations={"白城北": ("吉林省", "白城市"), "马坝": ("广东省", "韶关市"), "桂林西": ("广西壮族自治区", "桂林市")},
        node_registry=_registry(),
    )

    assert result.records == ()
    assert [item.status for item in result.admissions] == [
        "held_special_terminal",
        "held_unregistered_north_station",
    ]


def test_confirmed_test_rate_uses_normal_station_handling_fee_outside_shaoguan():
    result = build_confirmed_rail_test_rates(
        source="fixture.xlsx",
        route_rows=_rows((1, "白城北站", "桂林西站", "", None, 12000, None, None, None, None)),
        station_locations={"白城北": ("吉林省", "白城市"), "桂林西": ("广西壮族自治区", "桂林市")},
        node_registry=_registry(),
    )

    assert result.admitted_count == 1
