from src.data.port_reference import load_port_reference_tables


def test_load_port_reference_tables_reads_capabilities_and_region_mappings(tmp_path):
    write_csv(
        tmp_path / "港口能力表.csv",
        [
            "canonical_name",
            "node_id",
            "region_code",
            "infrastructure_type",
            "can_receive_bulk_shipping",
            "can_handle_barge",
            "supported_package_types",
            "supported_commodities",
            "aliases",
            "source",
        ],
        [
            [
                "秀屿港",
                "node-xiuyu",
                "fujian_meizhou_bay",
                "seaport",
                "是",
                "否",
                "散粮",
                "玉米；小麦",
                "莆田秀屿港",
                "manual_confirmed:2026-07-24",
            ]
        ],
    )
    write_csv(
        tmp_path / "区域映射表.csv",
        [
            "region_code",
            "region_name",
            "city_keywords",
            "port_keywords",
            "bulk_rate_destination_group",
            "bulk_time_region",
            "source",
        ],
        [
            [
                "fujian_meizhou_bay",
                "福建湄洲湾",
                "莆田；秀屿",
                "秀屿港",
                "秀屿",
                "福建",
                "manual_confirmed:2026-07-24",
            ]
        ],
    )

    tables = load_port_reference_tables(tmp_path)

    assert tables.missing_file_names == ()
    assert len(tables.port_capabilities) == 1
    capability = tables.port_capabilities[0]
    assert capability.node_id == "node-xiuyu"
    assert capability.canonical_name == "秀屿港"
    assert capability.can_receive_bulk_shipping
    assert not capability.can_handle_barge
    assert capability.supported_package_types == ("散粮",)
    assert capability.supported_commodities == ("玉米", "小麦")

    assert len(tables.region_mappings) == 1
    mapping = tables.region_mappings[0]
    assert mapping.matches("莆田秀屿港")
    assert mapping.bulk_rate_destination_group == "秀屿"
    assert mapping.bulk_time_region == "福建"


def test_missing_port_reference_tables_are_auditable_not_fatal(tmp_path):
    tables = load_port_reference_tables(tmp_path)

    assert tables.port_capabilities == ()
    assert tables.region_mappings == ()
    assert tables.missing_file_names == ("港口能力表.csv", "区域映射表.csv")
    assert len(tables.warnings) == 2


def test_port_capability_loader_preserves_unknown_values_instead_of_false(tmp_path):
    write_csv(
        tmp_path / "港口能力表.csv",
        [
            "canonical_name",
            "node_id",
            "region_code",
            "infrastructure_type",
            "can_receive_bulk_shipping",
            "can_handle_barge",
            "supported_package_types",
            "supported_commodities",
            "supported_transport_modes",
            "city",
            "shipping_time_region",
            "confirmation_status",
            "maintained_at",
            "source",
        ],
        [
            [
                "待确认港口",
                "node-pending-port",
                "",
                "unknown",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "manual_review",
                "",
                "pending_manual_review",
            ]
        ],
    )

    record = load_port_reference_tables(tmp_path).port_capabilities[0]

    assert record.can_receive_bulk_shipping is None
    assert record.can_handle_barge is None
    assert record.supported_package_types is None
    assert record.supported_commodities is None
    assert record.supported_transport_modes is None
    assert not record.capability_data_confirmed


def test_region_table_loads_explicit_confirmed_operation_fee_node_assignments(tmp_path):
    write_csv(
        tmp_path / "区域映射表.csv",
        [
            "region_code",
            "region_name",
            "city_keywords",
            "port_keywords",
            "source",
            "operation_fee_region_code",
            "operation_fee_port_node_ids",
            "operation_fee_mapping_basis",
            "operation_fee_mapping_rule_id",
            "operation_fee_mapping_rule_version",
            "operation_fee_confirmation_status",
            "maintained_at",
        ],
        [
            [
                "fujian_zhangzhou",
                "福建漳州",
                "漳州",
                "漳州港",
                "manual_confirmed:2026-07-24",
                "operation_fee_fujian_zhangzhou",
                "node-zhangzhou；node-nearby-port",
                "业务人工确认同一作业费区域",
                "operation_fee_region_manual_mapping",
                "1.0",
                "confirmed",
                "2026-07-24",
            ]
        ],
    )

    tables = load_port_reference_tables(tmp_path)

    assert len(tables.operation_fee_region_assignments) == 2
    assignment = tables.operation_fee_region_assignments[1]
    assert assignment.port_node_id == "node-nearby-port"
    assert assignment.operation_fee_region_code == "operation_fee_fujian_zhangzhou"
    assert assignment.mapping_rule_version == "1.0"
    assert assignment.is_confirmed


def write_csv(path, headers, rows):
    path.write_text(
        ",".join(headers)
        + "\n"
        + "\n".join(",".join(str(value) for value in row) for row in rows),
        encoding="utf-8-sig",
    )
