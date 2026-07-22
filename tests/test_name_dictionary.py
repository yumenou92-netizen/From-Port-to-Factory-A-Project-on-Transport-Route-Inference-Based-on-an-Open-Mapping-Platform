from openpyxl import Workbook
import pytest

from src.data.name_dictionary import (
    NAME_DICTIONARY_HEADERS,
    NameDictionaryError,
    build_external_alias_rules,
    load_name_dictionary_entries,
)


def test_name_dictionary_returns_only_explicit_full_short_alias_rules(tmp_path):
    path = tmp_path / "名称字典.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(NAME_DICTIONARY_HEADERS)
    worksheet.append(["港口码头", "测试东港码头有限公司", "测试东港"])
    worksheet.append(["港口码头", "", "深圳蛇口港"])
    worksheet.append(["客户仓库"])
    workbook.save(path)
    workbook.close()

    entries = load_name_dictionary_entries(path)
    rules = build_external_alias_rules(entries)

    assert len(entries) == 3
    assert len(rules) == 1
    assert rules[0].canonical_name == "测试东港码头有限公司"
    assert rules[0].aliases == ("测试东港",)
    assert rules[0].source == "名称字典.xlsx#2"
    assert entries[2].node_type == "客户仓库"
    assert entries[2].full_name is None
    assert entries[2].short_name is None


def test_name_dictionary_rejects_unexpected_header(tmp_path):
    path = tmp_path / "名称字典.xlsx"
    workbook = Workbook()
    workbook.active.append(["类型", "全称", "简称"])
    workbook.save(path)
    workbook.close()

    with pytest.raises(NameDictionaryError, match="前三列必须为"):
        load_name_dictionary_entries(path)


def test_name_dictionary_does_not_create_rules_for_ambiguous_short_name():
    from src.data.name_dictionary import NameDictionaryEntry

    rules = build_external_alias_rules(
        [
            NameDictionaryEntry(2, "港口码头", "甲港有限公司", "中心码头"),
            NameDictionaryEntry(3, "港口码头", "乙港有限公司", "中心码头"),
        ]
    )

    assert rules == ()
