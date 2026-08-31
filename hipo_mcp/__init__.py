from .server import mcp

__all__ = ["mcp"]


def _resolve_version() -> str:
    """版本号单一来源 = pyproject.toml（P1-20）。

    已安装（pip install -e . / 发布包）：用 importlib.metadata 读真实版本；
    源码直跑（未安装）：回退解析仓库根 pyproject.toml。
    用正则而非 tomllib，兼容 Python 3.10（requires-python >=3.10）。
    """
    try:
        from importlib.metadata import version
        return version("hipo-mcp")
    except Exception:  # noqa: BLE001 - 包未安装时 metadata 不可用
        pass
    try:
        from pathlib import Path
        import re
        root = Path(__file__).resolve().parent.parent / "pyproject.toml"
        if root.exists():
            m = re.search(r'^version\s*=\s*"([^"]+)"', root.read_text(encoding="utf-8"), re.M)
            if m:
                return m.group(1)
    except Exception:  # noqa: BLE001
        pass
    return "0.2.0"


__version__ = _resolve_version()