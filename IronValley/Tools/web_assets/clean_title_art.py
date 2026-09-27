"""Clean title-menu background from the user's mockup (Docs/navrhy/06_uvodni_menu_navrh.webp).

The mockup has its logo, menu items and place name baked into the picture. The game draws those as real,
selectable text, so this script removes them. It masks the UI pixels inside known rectangles and fills them
with OpenCV inpainting, then writes Web/public/assets/ui/title_kalne_hamry.webp. The menu CSS darkens the left
third of the picture, which hides the soft inpainted areas.

Needs opencv-python-headless + Pillow. Use a separate venv: OpenCV pulls numpy 2, and bpy needs numpy < 2.
    python -m venv .cvenv && .cvenv/bin/pip install opencv-python-headless pillow
    .cvenv/bin/python Tools/web_assets/clean_title_art.py
"""
import pathlib

import cv2
import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / 'Docs/navrhy/06_uvodni_menu_navrh.webp'
OUT = ROOT / 'Web/public/assets/ui/title_kalne_hamry.webp'
REF_W, REF_H = 1672, 941  # rectangles below are in mockup pixels

# (x0, y0, x1, y1, mode): 'fill' masks the whole rectangle, 'ink' only bright / yellow pixels in it
RECTS = [
    (78, 92, 552, 352, 'ink'),     # IRON VALLEY logo
    (82, 366, 336, 384, 'fill'),   # yellow bar under the logo
    (82, 421, 437, 499, 'fill'),   # HRÁT button
    (106, 522, 305, 806, 'ink'),   # VÝCVIK .. UKONČIT
    (1428, 874, 1640, 902, 'ink'), # — KALNÉ HAMRY
]


def main():
    img = cv2.cvtColor(np.array(Image.open(SRC).convert('RGB')), cv2.COLOR_RGB2BGR)
    h, w = img.shape[:2]
    sx, sy = w / REF_W, h / REF_H
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    ink = ((hsv[..., 2] > 125) & (hsv[..., 1] < 90)) | (
        (hsv[..., 0] >= 14) & (hsv[..., 0] <= 34) & (hsv[..., 1] > 90) & (hsv[..., 2] > 110))
    mask = np.zeros((h, w), np.uint8)
    for x0, y0, x1, y1, mode in RECTS:
        x0, x1 = int(x0 * sx), int(x1 * sx)
        y0, y1 = int(y0 * sy), int(y1 * sy)
        if mode == 'fill':
            mask[y0:y1, x0:x1] = 255
        else:
            region = ink[y0:y1, x0:x1].astype(np.uint8) * 255
            region = cv2.morphologyEx(region, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))  # distress holes in letters
            mask[y0:y1, x0:x1] = np.maximum(mask[y0:y1, x0:x1], region)
    mask = cv2.dilate(mask, np.ones((7, 7), np.uint8))  # anti-aliased edges and the drop shadow
    clean = cv2.inpaint(img, mask, 9, cv2.INPAINT_TELEA)
    # inpainting drags colour in from the lit trees; darken the filled areas with a soft edge so they read as shade
    soft = cv2.GaussianBlur(mask.astype(np.float32) / 255.0, (0, 0), 14)[..., None]
    clean = (clean.astype(np.float32) * (1.0 - 0.5 * soft)).clip(0, 255).astype(np.uint8)
    Image.fromarray(cv2.cvtColor(clean, cv2.COLOR_BGR2RGB)).save(OUT, 'WEBP', quality=82, method=6)
    print(f'{OUT.relative_to(ROOT)}: {OUT.stat().st_size // 1024} KiB, masked {int((mask > 0).mean() * 1000) / 10} %')


if __name__ == '__main__':
    main()
