"""Image preprocessing shared by training and the demo."""
import cv2
import numpy as np
from PIL import Image


def crop_fundus(image, threshold=15):
    """Crop away the black border around the fundus and pad to a square.

    The training images are already cropped this way, so applying it to
    arbitrary uploads (other cameras, other datasets) keeps inputs consistent.
    """
    if isinstance(image, Image.Image):
        image = np.array(image.convert('RGB'))
    mask = image.max(axis=2) > threshold
    rows, cols = np.where(mask.any(axis=1))[0], np.where(mask.any(axis=0))[0]
    if len(rows) and len(cols):
        image = image[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]
    return _pad_square(image)


def _pad_square(image):
    h, w = image.shape[:2]
    size = max(h, w)
    square = np.zeros((size, size, 3), dtype=image.dtype)
    top, left = (size - h) // 2, (size - w) // 2
    square[top:top + h, left:left + w] = image
    return square


def _fill_holes(mask):
    """Pixels enclosed by the mask (a bright optic disc, a dark fovea) belong to it."""
    flood = np.pad(mask.astype(np.uint8), 1)
    cv2.floodFill(flood, None, (0, 0), 1)
    return mask | (flood[1:-1, 1:-1] == 0)


def prepare_fundus(image):
    """The model's input for an uploaded photo: crop_fundus, after white or grey margins are made black.

    Training photos are a round field on a black background. Photos from the web or a screenshot often
    sit on white or grey margins, with captions or letter labels around them, which crop_fundus keeps
    (it only removes black). Here light, colourless pixels outside the retina are set to black first;
    the retina is the largest region that is neither black nor light grey, with everything it encloses
    (a bright optic disc). A photo with no such margin goes through crop_fundus unchanged, so clean
    photos give exactly the input the model was validated on. On test eyes pasted onto a white margin
    this restores the clean-photo results (myopia found in 84% instead of 55%).
    The side of the returned square is the retina's size in the original photo's pixels.
    """
    a = np.asarray(image.convert('RGB') if isinstance(image, Image.Image) else image)
    if a.size == 0:
        raise ValueError('empty image')
    mx, mn = a.max(axis=2).astype(int), a.min(axis=2).astype(int)
    light = (mn >= 200) & (mx - mn <= 30)
    if not light.any():
        return crop_fundus(a)
    retina = (~(light | (mx <= 15))).astype(np.uint8)
    retina = cv2.morphologyEx(retina, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))  # drops thin text and lines
    n, labels, stats, _ = cv2.connectedComponentsWithStats(retina, connectivity=8)
    if n <= 1:  # nothing but background: the quality check rejects it
        return crop_fundus(a)
    k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    margin = light & ~_fill_holes(labels == k)
    if not margin.any():
        return crop_fundus(a)
    a = a.copy()
    a[margin] = 0
    return crop_fundus(a)
