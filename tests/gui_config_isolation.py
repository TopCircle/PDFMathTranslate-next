"""Point GUI config paths at a temporary directory before pdf2zh_next.gui is imported."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def isolate_gui_config(tmp_path: Path) -> Path:
    """Rebind config locations onto tmp_path and disable Gradio analytics."""
    os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
    config_dir = tmp_path / "config" / "pdf2zh"
    config_dir.mkdir(parents=True, exist_ok=True)
    default_dir = config_dir / "default"
    default_dir.mkdir(parents=True, exist_ok=True)

    import pdf2zh_next.config.main as config_main
    import pdf2zh_next.const as const

    const.DEFAULT_CONFIG_DIR = config_dir
    const.DEFAULT_CONFIG_FILE = (
        config_dir / f"config.v{const.__config_file_version__}.toml"
    )
    const.WRITE_TEMP_CONFIG_FILE = (
        config_dir / f"config.v{const.__config_file_version__}.temp.toml"
    )
    const.VERSION_DEFAULT_CONFIG_DIR = default_dir
    const.VERSION_DEFAULT_CONFIG_FILE = default_dir / f"{const.__version__}.toml"

    config_main.DEFAULT_CONFIG_DIR = const.DEFAULT_CONFIG_DIR
    config_main.DEFAULT_CONFIG_FILE = const.DEFAULT_CONFIG_FILE
    config_main.WRITE_TEMP_CONFIG_FILE = const.WRITE_TEMP_CONFIG_FILE
    config_main.VERSION_DEFAULT_CONFIG_FILE = const.VERSION_DEFAULT_CONFIG_FILE
    config_main.ConfigManager._default_config_file_path = const.DEFAULT_CONFIG_FILE

    gui = sys.modules.get("pdf2zh_next.gui")
    if gui is not None:
        gui.DEFAULT_CONFIG_DIR = const.DEFAULT_CONFIG_DIR
        gui.DEFAULT_CONFIG_FILE = const.DEFAULT_CONFIG_FILE
        gui.config_fake_pdf_path = const.DEFAULT_CONFIG_DIR / "config.fake.pdf"
    return config_dir


def home_config_dir() -> Path:
    return Path(os.path.expanduser("~")) / ".config" / "pdf2zh"


def snapshot_home_config() -> dict[Path, bytes | None]:
    home = home_config_dir()
    watched = [
        home / "config.fake.pdf",
        home / "config.v3.toml",
        home / "config.v3.temp.toml",
        home / "default" / "2.9.0.toml",
    ]
    return {path: path.read_bytes() if path.exists() else None for path in watched}


def install_home_config_write_guard(monkeypatch) -> None:
    """Fail if a test writes a config artifact under ~/.config/pdf2zh."""
    home = home_config_dir().resolve()

    def reject(path) -> None:
        try:
            resolved = Path(path).expanduser().resolve()
        except OSError:
            return
        if resolved == home or home in resolved.parents:
            raise AssertionError(f"config write escaped to {resolved}")

    real_open = Path.open

    def guarded_open(self, mode="r", *args, **kwargs):
        if any(flag in str(mode) for flag in ("w", "a", "x", "+")):
            reject(self)
        return real_open(self, mode, *args, **kwargs)

    real_write_text = Path.write_text

    def guarded_write_text(self, *args, **kwargs):
        reject(self)
        return real_write_text(self, *args, **kwargs)

    real_write_bytes = Path.write_bytes

    def guarded_write_bytes(self, *args, **kwargs):
        reject(self)
        return real_write_bytes(self, *args, **kwargs)

    real_replace = Path.replace

    def guarded_replace(self, target):
        reject(self)
        reject(target)
        return real_replace(self, target)

    real_os_replace = os.replace

    def guarded_os_replace(src, dst, *args, **kwargs):
        reject(src)
        reject(dst)
        return real_os_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(Path, "write_text", guarded_write_text)
    monkeypatch.setattr(Path, "write_bytes", guarded_write_bytes)
    monkeypatch.setattr(Path, "replace", guarded_replace)
    monkeypatch.setattr(os, "replace", guarded_os_replace)
