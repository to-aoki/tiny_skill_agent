#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--label", default="default")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve()
    print(json.dumps({
        "label": args.label,
        "workspace": str(workspace),
        "exists": workspace.exists(),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
