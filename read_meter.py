"""
Read water meters from image files without starting the API server.

Usage:
    python read_meter.py "water meter.jpg"
    python read_meter.py photo1.jpg photo2.png        # several images
    python read_meter.py path/to/folder               # every .jpg/.jpeg/.png in a folder
    python read_meter.py https://example.com/meter.jpg

Runs the same pipeline as POST /flowvision/v1/extract-reading, but nothing is stored in the database.
"""
import os
import sys
import time
import argparse
from pathlib import Path

try:
    import numpy as np
    from PIL import Image
    import fastai, ultralytics  # noqa: F401  (fail fast with a helpful message)
except ImportError as e:
    sys.exit(
        f"Missing package ({e.name}). Activate the project's virtual environment first:\n"
        "  PowerShell : .venv\\Scripts\\Activate.ps1\n"
        "  Git Bash   : source .venv/Scripts/activate\n"
        "  Linux/Mac  : source .venv/bin/activate"
    )

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
REPO_ROOT = Path(__file__).resolve().parent


def rejoin_split_paths(args):
    """
    An unquoted path containing spaces arrives as several arguments
    (e.g. 'water' 'meter.jpg'); join neighbours back together when that forms an existing path.
    """
    result = []
    i = 0
    while i < len(args):
        for j in range(len(args), i, -1):
            candidate = " ".join(args[i:j])
            if j == i + 1 or Path(candidate).exists():
                result.append(candidate)
                i = j
                break
    return result


def collect_inputs(args):
    inputs = []
    for arg in rejoin_split_paths(args):
        if arg.startswith(("http://", "https://")):
            inputs.append(arg)
            continue
        path = Path(arg).resolve()
        if path.is_dir():
            inputs.extend(sorted(p for p in path.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS))
        elif path.is_file():
            inputs.append(path)
        else:
            sys.exit(f"Not found: {arg}")
    if not inputs:
        sys.exit("No images found.")
    return inputs


def main():
    parser = argparse.ArgumentParser(description="Read water meters from image files, folders or URLs.")
    parser.add_argument("images", nargs="+", help="image file(s), folder(s) or URL(s)")
    inputs = collect_inputs(parser.parse_args().images)

    # Config and model paths are relative to the repo root, so run from there
    os.chdir(REPO_ROOT)
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from conf.config import Config
    from service.api.image_service import ImageService

    print("Loading models (takes ~20 seconds)...", flush=True)
    service = ImageService(config=Config())

    for item in inputs:
        name = item if isinstance(item, str) else item.name
        start = time.perf_counter()
        try:
            if isinstance(item, str):
                image_rgb = service.download_image(item)
            else:
                image_rgb = np.array(Image.open(item).convert("RGB"))
            result = service.analyze_image(image_rgb)
        except Exception as e:
            print(f"\n{name}\n  ERROR: {e}")
            continue
        elapsed = time.perf_counter() - start

        print(f"\n{name}")
        print(f"  Reading : {result['meterReading']}")
        print(f"  Status  : {result['status']}")
        print(f"  Quality : {result['qualityStatus']} ({result['qualityConfidence']:.0%} sure)")
        if result['lastDigitColor'] != "unknown":
            print(f"  Last digit colour : {result['lastDigitColor']} ({result['colorConfidence']:.0%} sure)")
        print(f"  Time    : {elapsed:.2f}s")


if __name__ == "__main__":
    main()
