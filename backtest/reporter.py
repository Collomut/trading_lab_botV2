"""Report generation for backtests."""
from __future__ import annotations

import json
from pathlib import Path


def write_json_report(results: dict, output_path: str) -> str:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    return str(path)


def write_text_report(table: str, results: dict, output_path: str) -> str:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [table, "", "Per-candidate trade counts and assumptions:", ""]
    for name, result in results.items():
        m = result.get("metrics", {})
        lines.append(
            f"- {name}: trades={m.get('total_trades', 0)}, "
            f"PF={m.get('profit_factor')}, maxDD={m.get('max_drawdown_pct')}%, "
            f"slippage/fees are modeled (see docs/COMPARISON_PROTOCOL.md)"
        )
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)
