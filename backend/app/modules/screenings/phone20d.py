"""Prepare a smartphone + 20D lens photo so it looks like the clinic fundus photos the model was trained on.

A phone held behind a 20D condensing lens shows the retina as a small, bright, reddish circle inside the lens
rim. The rest of the frame is skin, eyelid and the lens holder, the image is upside down (indirect
ophthalmoscopy inverts it) and the torch leaves glare spots. This module:

1. finds that circle (bright + reddish, roughly round, fully inside the frame, brighter than its surround);
2. rejects the photo with a plain reason when it can't, or when glare covers too much of the view;
3. crops a square around the circle, blacks out everything outside it and rotates it 180 degrees.

The model has NOT been validated on real phone photos: this step only removes the differences that are
known to break it (see the screening's image_source). Nothing here touches the clinic-photo path.
"""
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

WORK_SIDE = 800            # the search runs on a copy whose longest side is at most this many pixels
MIN_DIAMETER = 0.15        # circle diameter / shorter image side: smaller than this is a speck, not a retina view
MIN_FILL = 0.70            # blob area / enclosing-circle area: a round view fills most of its circle
MIN_CONTRAST = 1.25        # mean brightness inside the circle / in the ring around it
MIN_RED_OVER_BLUE = 1.15   # retina is red-orange; blue/grey/white blobs are not
LEVELS = (35, 50, 65, 80, 95, 110, 130)  # brightness cut-offs tried; the retina view's brightness varies a lot
BLOBS_PER_LEVEL = 4        # blobs judged per cut-off, largest first
EDGE_MARGIN = 2            # working-copy pixels: a blob touching the frame edge is cut off
GLARE_LEVEL = 235          # a pixel whose darkest channel is above this is near-white (light reflection)
MAX_GLARE = 0.08           # more than 8% of the retina view saturated -> retake (see the PR for the measurements)

NO_CIRCLE = ("We couldn't find the round view of the retina in this photo. Hold the 20D lens so the whole "
             "bright circle is in the frame, then retake.")
TOO_SMALL = ("The round view of the retina is too small in this photo. Move the phone and lens closer so the "
             "bright circle fills more of the frame, then retake.")
CUT_OFF = ("The round view of the retina is cut off by the edge of the photo. Centre the bright circle in the "
           "frame, then retake.")
GLARE = "Too much glare from the light. Tilt the 20D lens slightly or dim the light, then retake."


@dataclass
class PreparedPhone:
    ok: bool
    reason: str | None = None          # plain-language failure reason (None when ok)
    detail: str = ""                   # short technical line for fields.file
    image: Image.Image | None = None   # square, black outside the circle, rotated 180 degrees
    circle: tuple[int, int, int] | None = None  # x, y, radius in the ORIGINAL image's pixels
    glare: float = 0.0                 # fraction of near-white pixels inside the circle


def _fail(reason: str, detail: str, glare: float = 0.0) -> PreparedPhone:
    return PreparedPhone(False, reason, detail, glare=glare)


@dataclass
class _Candidate:
    cx: float
    cy: float
    radius: float
    fill: float
    failure: str | None = None  # NO_CIRCLE / TOO_SMALL / CUT_OFF, None = a usable circle
    detail: str = ""


def _candidates(bright: np.ndarray, red_ok: np.ndarray, level: int) -> list[_Candidate]:
    """The largest few bright reddish blobs at one brightness cut-off, each judged as a possible retina view.

    More than one is looked at because the skin around the lens can be the biggest bright blob at a low cut-off.
    """
    sh, sw = bright.shape
    mask = ((bright > level) & red_ok).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))  # drop specks
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    order = 1 + np.argsort(stats[1:, cv2.CC_STAT_AREA])[::-1][:BLOBS_PER_LEVEL]
    found = []
    for blob_id in order:
        blob = (labels == blob_id).astype(np.uint8)
        contours, _ = cv2.findContours(blob, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)  # outer outline: fills holes
        outline = max(contours, key=cv2.contourArea)
        (cx, cy), radius = cv2.minEnclosingCircle(outline)
        if radius < 3:
            continue
        fill = float(cv2.contourArea(outline)) / (np.pi * radius * radius)
        item = _Candidate(cx, cy, radius, fill)
        found.append(item)
        if fill < MIN_FILL:
            item.failure, item.detail = NO_CIRCLE, f"REGION IS NOT ROUND (FILL {fill:.2f} · MINIMUM {MIN_FILL:.2f})"
            continue
        x, y, bw, bh = cv2.boundingRect(outline)
        if x <= EDGE_MARGIN or y <= EDGE_MARGIN or x + bw >= sw - EDGE_MARGIN or y + bh >= sh - EDGE_MARGIN:
            item.failure, item.detail = CUT_OFF, "THE CIRCLE TOUCHES THE EDGE OF THE PHOTO"
            continue
        if 2 * radius < MIN_DIAMETER * min(sh, sw):
            item.failure = TOO_SMALL
            item.detail = f"CIRCLE DIAMETER {2 * radius / min(sh, sw):.0%} OF THE SHORTER SIDE · MINIMUM {MIN_DIAMETER:.0%}"
            continue
        disc = np.zeros((sh, sw), np.uint8)
        cv2.circle(disc, (round(cx), round(cy)), round(radius), 1, -1)
        ring = np.zeros((sh, sw), np.uint8)
        cv2.circle(ring, (round(cx), round(cy)), round(radius * 1.35), 1, -1)
        ring[disc > 0] = 0
        around = bright[ring > 0]
        contrast = float(bright[disc > 0].mean() / max(1.0, float(around.mean()))) if around.size else 0.0
        if contrast < MIN_CONTRAST:
            item.failure = NO_CIRCLE
            item.detail = f"THE CIRCLE IS NOT BRIGHTER THAN ITS SURROUND (RATIO {contrast:.2f} · MINIMUM {MIN_CONTRAST:.2f})"
    return found


def prepare_phone_20d(image: Image.Image) -> PreparedPhone:
    rgb = np.asarray(image.convert("RGB"))
    h, w = rgb.shape[:2]
    scale = min(1.0, WORK_SIDE / max(h, w))
    small = cv2.resize(rgb, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else rgb
    sh, sw = small.shape[:2]
    bright = cv2.GaussianBlur(small.max(axis=2), (0, 0), 1.2)
    red_ok = small[..., 0].astype(np.float32) / (small[..., 2].astype(np.float32) + 1) >= MIN_RED_OVER_BLUE

    found = [c for level in LEVELS for c in _candidates(bright, red_ok, level)]
    usable = [c for c in found if c.failure is None]
    if not usable:
        # Say the most helpful thing: a round view that is cut off or tiny beats "not found"
        for wanted in (CUT_OFF, TOO_SMALL):
            hit = next((c for c in found if c.failure == wanted and c.fill >= MIN_FILL), None)
            if hit:
                return _fail(wanted, hit.detail)
        roundest = max(found, key=lambda c: c.fill, default=None)
        return _fail(NO_CIRCLE, roundest.detail if roundest else "NO BRIGHT REDDISH REGION FOUND")
    best = max(usable, key=lambda c: (c.fill, c.radius))
    cx, cy, radius = best.cx, best.cy, best.radius

    # Work in the original pixels from here on
    ox, oy, orad = round(cx / scale), round(cy / scale), max(1, round(radius / scale))
    side = 2 * orad
    left, top = ox - orad, oy - orad
    if left < 0 or top < 0 or left + side > w or top + side > h:
        return _fail(CUT_OFF, "THE CIRCLE TOUCHES THE EDGE OF THE PHOTO")
    square = rgb[top:top + side, left:left + side].copy()
    yy, xx = np.mgrid[:side, :side]
    inside = (xx - orad + 0.5) ** 2 + (yy - orad + 0.5) ** 2 <= orad ** 2
    glare = float((square.min(axis=2)[inside] > GLARE_LEVEL).mean())
    if glare > MAX_GLARE:
        return _fail(GLARE, f"GLARE {glare:.0%} OF THE RETINA VIEW · MAXIMUM {MAX_GLARE:.0%}", glare)
    square[~inside] = 0
    prepared = Image.fromarray(np.ascontiguousarray(np.rot90(square, 2)))  # indirect ophthalmoscopy inverts the view
    return PreparedPhone(True, None, "", prepared, (ox, oy, orad), glare)
