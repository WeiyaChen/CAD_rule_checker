from pathlib import Path
import xml.etree.ElementTree as ET

from src.config.config import Settings
from src.io.dxf_to_svg import write_svg_tree


def test_runtime_settings_are_exposed_from_config():
    settings = Settings(config_file="src/config/settings.yaml")

    assert settings.run_mode == "SINGLE"
    assert settings.runtime_target_file == "南阳名门150.svg"


def test_llm_settings_can_be_overridden_by_environment(monkeypatch):
    monkeypatch.setenv("CAD_RULE_CHECKER_LLM_API_KEY", "env-key")
    settings = Settings(config_file="src/config/settings.yaml")

    assert settings.llm_api_key == "env-key"


def test_svg_tree_is_written_as_utf8(tmp_path):
    svg = ET.Element("svg")
    ET.SubElement(svg, "text").text = "中文"

    output_path = tmp_path / "sample.svg"
    write_svg_tree(svg, output_path)

    written = output_path.read_text(encoding="utf-8")
    assert "中文" in written
    assert "<?xml" in written
