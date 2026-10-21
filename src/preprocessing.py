"""Image preprocessing shared by training and the demo."""
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
    h, w = image.shape[:2]
    size = max(h, w)
    square = np.zeros((size, size, 3), dtype=image.dtype)
    top, left = (size - h) // 2, (size - w) // 2
    square[top:top + h, left:left + w] = image
    return square
