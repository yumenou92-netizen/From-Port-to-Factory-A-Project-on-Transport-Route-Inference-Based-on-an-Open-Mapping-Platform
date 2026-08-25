import pytest

from src.domain.node_role import (
    allows_north_south_bulk_candidate,
    has_confirmed_sea_access,
    infer_node_role_from_name,
    infer_port_waterway_role,
    north_south_bulk_exclusion_reason,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    (
        ("梧州站", "railway_station"),
        ("北京西", "railway_station"),
        ("怀化西", "railway_station"),
        ("深圳北", "railway_station"),
        ("中央储备粮南宁直属库", "customer_facility"),
        ("阳江华南诚通仓库", "customer_facility"),
        ("贵港市海大饲料有限公司", "customer_facility"),
        ("宁德鑫华港饲料有限公司", "customer_facility"),
        ("钦州港", "port"),
        ("韶关北江国际港（白土码头）", "port"),
        ("肇庆福加德码头", "port"),
        ("东莞深粮", "customer_facility"),
    ),
)
def test_infer_node_role_from_confirmed_name_rules(name, expected):
    assert infer_node_role_from_name(name) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    (
        ("军航码头", "sea_inland_dual_use"),
        ("福建军航码头", "sea_inland_dual_use"),
        ("福州马尾港", "sea_inland_dual_use"),
        ("洋浦港", "sea_port"),
        ("福州松下码头", "sea_port"),
        ("福建松下码头", "sea_port"),
        ("清远清新码头", "inland_port"),
        ("苏湾港", "inland_port"),
        ("贵港白沙码头", "inland_port"),
        ("韶关北江国际港（白土码头）", "inland_port"),
        ("南平港", "inland_port"),
        ("钦州港", "sea_port"),
        ("东莞深粮", "not_port"),
    ),
)
def test_infer_confirmed_port_waterway_role(name, expected):
    assert infer_port_waterway_role(name) == expected


def test_confirmed_unmarked_customer_names_are_customer_facilities():
    assert infer_node_role_from_name("东莞深粮") == "customer_facility"
    assert infer_node_role_from_name("平和县储备粮") == "customer_facility"


def test_confirmed_packaging_capability_excludes_mawei_and_songxia_from_bulk_trunk():
    assert not allows_north_south_bulk_candidate("福州马尾港")
    assert "仅确认集装箱" in north_south_bulk_exclusion_reason("福州马尾港")
    assert not allows_north_south_bulk_candidate("福州松下码头")
    assert "尚未确认" in north_south_bulk_exclusion_reason("福州松下码头")
    assert allows_north_south_bulk_candidate("军航码头")


def test_bulk_trunk_accepts_confirmed_sea_access_or_bulk_origin_evidence():
    assert has_confirmed_sea_access("钦州港")
    assert allows_north_south_bulk_candidate("钦州港")
    assert not has_confirmed_sea_access("广州花都港")
    assert not allows_north_south_bulk_candidate("广州花都港")
    assert allows_north_south_bulk_candidate(
        "广州新港",
        has_bulk_freight_origin_evidence=True,
    )
    assert not allows_north_south_bulk_candidate(
        "广州花都港",
        has_bulk_freight_origin_evidence=False,
    )
    assert not allows_north_south_bulk_candidate("南平港")
    assert not allows_north_south_bulk_candidate(
        "清远清新码头",
        has_bulk_freight_origin_evidence=True,
    )
    assert not allows_north_south_bulk_candidate(
        "福州马尾港",
        has_bulk_freight_origin_evidence=True,
    )
    assert has_confirmed_sea_access("蛇口港", "深圳蛇口港")
    assert allows_north_south_bulk_candidate("蛇口港", "深圳蛇口港")
    assert not allows_north_south_bulk_candidate("百达码头")
    assert "人工确认忽略" in north_south_bulk_exclusion_reason("百达码头")
