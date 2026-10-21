import albumentations as A
import torch
from albumentations.pytorch import ToTensorV2
from PIL import Image
from torch.utils.data import Dataset

from .labels import LABELS, UNKNOWN
from .preprocessing import crop_fundus

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


class ODIR5KDataset(Dataset):
    def __init__(self, df, transform=None):
        """
        Args:
            df (DataFrame): rows from data/labels.csv (one per eye image, image at df['path'])
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


def train_transforms(img_size=384):
    return A.Compose([
        A.Resize(img_size, img_size),
        A.HorizontalFlip(p=0.5),
        A.Affine(scale=(0.9, 1.1), rotate=(-20, 20), translate_percent=(-0.05, 0.05), p=0.7),
        A.RandomBrightnessContrast(brightness_limit=0.2, contrast_limit=0.2, p=0.5),
        A.HueSaturationValue(hue_shift_limit=5, sat_shift_limit=10, val_shift_limit=5, p=0.3),
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
