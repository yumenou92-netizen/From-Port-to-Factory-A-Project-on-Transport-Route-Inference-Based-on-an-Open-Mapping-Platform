from src.dev.feature_demo import main


def test_feature_demo_runs_without_real_data_and_masks_secret(tmp_path, capsys):
    env_file = tmp_path / "runtime_env.csv"
    secret_value = "demo" + "-secret"
    env_file.write_text(
        "\n".join(
            [
                "key,value,required,note",
                "DATA_DIR,.\\data_REAL,true,local test data",
                (
                    "TENCENT_MAP_API_KEY,"
                    f"{secret_value},false,TENCENT_MAP_API_KEY={secret_value}"
                ),
                "SMOKE_RUN_TENCENT_PROBE,FALSE,false,do not call external API",
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(["--env-file", str(env_file), "--skip-real-data"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Developer Feature Demo" in output
    assert "unknown container truck" in output
    assert "Latest Freight Rate Selection" in output
    assert "TransportEdge -> MultiDiGraph -> Route Search" in output
    assert "Leader Full-Flow Demo Contract" in output
    assert "optional registered south port" in output
    assert "Parallel last mile" in output
    assert "nearest same-region operation fee" in output
    assert "src.web.server" in output
    assert "Excluded pending confirmation: AdditionalFee" in output
    assert "<set; 11 chars>" in output
    assert secret_value not in output
