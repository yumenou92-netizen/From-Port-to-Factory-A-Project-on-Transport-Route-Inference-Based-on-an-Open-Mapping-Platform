from pathlib import Path

from src.dev.runtime_env import load_runtime_env


def test_runtime_env_reads_gb18030_csv_and_redacts_secret_notes(tmp_path):
    env_file = tmp_path / "runtime_env.csv"
    env_file.write_text(
        "\n".join(
            [
                "key,value,required,note",
                "DATA_DIR,.\\data_REAL,true,真实数据目录",
                "FREIGHT_WORKBOOK_PATH,.\\data_REAL\\fee_switch\\运费数据_领导确认修订.xlsx,false,本次显式运价工作簿",
                "TENCENT_MAP_API_KEY,fake-key,false,TENCENT_MAP_API_KEY=fake-key",
            ]
        ),
        encoding="gb18030",
    )

    result = load_runtime_env(env_file, base_dir=Path.cwd(), apply=False)
    entries = {entry.key: entry for entry in result.entries}

    assert result.ok
    assert entries["DATA_DIR"].display_value.endswith("data_REAL")
    assert entries["FREIGHT_WORKBOOK_PATH"].display_value.endswith(
        "data_REAL\\fee_switch\\运费数据_领导确认修订.xlsx"
    )
    assert entries["TENCENT_MAP_API_KEY"].display_value == "<set; 8 chars>"
    assert entries["TENCENT_MAP_API_KEY"].display_note == "<redacted for secret-like key>"
