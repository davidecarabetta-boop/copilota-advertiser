from pathlib import Path

import yaml

CONFIG = Path(__file__).parent.parent / "config"


def test_yaml_files_parse():
    for f in CONFIG.rglob("*.yaml"):
        assert yaml.safe_load(f.read_text(encoding="utf-8")) is not None, f
