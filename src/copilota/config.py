"""Lettura di config/: soglie generali, eventualmente sovrascritte dal file del cliente."""

from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).parent.parent.parent / "config"


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_thresholds(client: str | None = None, config_dir: Path = CONFIG_DIR) -> dict[str, Any]:
    """Soglie da soglie.yaml; la sezione `soglie` di config/clienti/<client>.yaml le sovrascrive."""
    base = yaml.safe_load((config_dir / "soglie.yaml").read_text(encoding="utf-8"))
    if client:
        f = config_dir / "clienti" / f"{client.lower()}.yaml"
        if f.exists():
            override = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("soglie") or {}
            base = _merge(base, override)
    return base
