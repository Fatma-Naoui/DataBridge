import argparse
import json
from pathlib import Path

import yaml

from src.pipeline import run

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the DataBridge data preparation pipeline."
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to the YAML configuration file.",
    )
    args = parser.parse_args()

    with Path(args.config).open("r", encoding="utf-8") as file:
        cfg = yaml.safe_load(file)

    print(json.dumps(run(cfg), indent=2, ensure_ascii=False))
