import albumentations as A
import torch
from albumentations.pytorch import ToTensorV2
from PIL import Image
from torch.utils.data import Dataset

from .labels import LABELS, UNKNOWN
from .preprocessing import crop_fundus

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


class FundusDataset(Dataset):
    def __init__(self, df, transform=None):
        """
        Args:
            df (DataFrame): rows from data/labels.csv (one per eye image from ODIR or an external dataset, image at df['path'])
            transform (callable, optional): albumentations transform
        """
        self.data = df.reset_index(drop=True)
        self.transform = transform
        # Unknown labels (external datasets only know some diseases) become -1, which
        # the loss and metrics ignore
        targets = self.data[LABELS].astype(float).fillna(UNKNOWN).values
        self.targets = torch.tensor(targets, dtype=torch.float32)

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        image = crop_fundus(Image.open(self.data.loc[idx, 'path']))
        if self.transform:
            image = self.transform(image=image)['image']
        return image, self.targets[idx]


def train_transforms(img_size=384, strong=False):
    """strong=True adds camera variation: exposure, colour, mild noise, JPEG artefacts and low resolution.

    Blur stays mild on purpose: on a fundus photo, haze is the sign of cataract, so heavy blur on
    images labelled "no cataract" would teach the model to ignore it.
    """
    camera = [
        A.RandomBrightnessContrast(brightness_limit=0.3, contrast_limit=0.3, p=0.7),
        A.RandomGamma(gamma_limit=(80, 120), p=0.3),
        A.HueSaturationValue(hue_shift_limit=8, sat_shift_limit=20, val_shift_limit=10, p=0.5),
        A.CLAHE(clip_limit=2.0, p=0.2),
        A.OneOf([A.GaussianBlur(blur_limit=(3, 3), sigma_limit=(0.1, 0.8)),
                 A.GaussNoise(std_range=(0.01, 0.04)),
                 A.Downscale(scale_range=(0.5, 0.9))], p=0.3),
        A.ImageCompression(quality_range=(60, 95), p=0.3),
    ] if strong else [
        A.RandomBrightnessContrast(brightness_limit=0.2, contrast_limit=0.2, p=0.5),
        A.HueSaturationValue(hue_shift_limit=5, sat_shift_limit=10, val_shift_limit=5, p=0.3),
    ]
    return A.Compose([
        A.Resize(img_size, img_size),
        A.HorizontalFlip(p=0.5),
        A.Affine(scale=(0.9, 1.1), rotate=(-20, 20), translate_percent=(-0.05, 0.05), p=0.7),
        *camera,
        A.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ToTensorV2(),
    ])


def val_transforms(img_size=384):
    return A.Compose([
        A.Resize(img_size, img_size),
        A.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ToTensorV2(),
    ])


def to_tensor(image, img_size=384):
    """Preprocess a single image (PIL or RGB array) exactly like validation data."""
    return val_transforms(img_size)(image=crop_fundus(image))['image'].unsqueeze(0)
