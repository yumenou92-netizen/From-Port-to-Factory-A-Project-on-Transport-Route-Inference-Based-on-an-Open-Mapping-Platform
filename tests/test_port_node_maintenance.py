from openpyxl import Workbook

from src.data.port_node_maintenance import (
    PORT_NODE_MAINTENANCE_HEADERS,
    load_port_node_maintenance_entries,
)


def test_load_port_node_maintenance_entries_preserves_aliases_and_coordinates(
    tmp_path,
):
    path = tmp_path / "码头信息维护0729版.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(PORT_NODE_MAINTENANCE_HEADERS)
    sheet.append(
        (
            "站点",
            "港口码头",
            None,
            "福建军航码头",
            "军航码头",
            None,
            None,
            "福建省",
            "福州市",
            "马尾区",
            None,
            "亭江镇闽安村",
            119.511455860655,
            26.056622741731,
        )
    )
    workbook.save(path)

    entries = load_port_node_maintenance_entries(path)

    assert len(entries) == 1
    assert entries[0].full_name == "福建军航码头"
    assert entries[0].aliases == ("军航码头",)
    assert entries[0].longitude == 119.511455860655
    assert entries[0].latitude == 26.056622741731
    assert entries[0].source == "码头信息维护0729版.xlsx#2"
