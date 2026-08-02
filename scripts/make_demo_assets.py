"""Assemble docs/assets/movie-demo.gif from ordered PNG frames.

Usage: uv run python scripts/make_demo_assets.py <frames_dir>
Frames are sorted by name; 600ms/frame, loops forever. Fixture data only.
"""
import sys
from pathlib import Path
from PIL import Image

def main(frames_dir: str) -> None:
    frames = [Image.open(p).convert("P", palette=Image.ADAPTIVE)
              for p in sorted(Path(frames_dir).glob("*.png"))]
    if len(frames) < 2:
        raise SystemExit(f"need >=2 frames in {frames_dir}, found {len(frames)}")
    out = Path("docs/assets/movie-demo.gif")
    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(out, save_all=True, append_images=frames[1:],
                   duration=600, loop=0, optimize=True)
    print(f"wrote {out} ({out.stat().st_size // 1024} KB, {len(frames)} frames)")

if __name__ == "__main__":
    main(sys.argv[1])
