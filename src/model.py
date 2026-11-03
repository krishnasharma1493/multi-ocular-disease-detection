import json

import torch
import torch.nn as nn
from torchvision import models

from .labels import LABELS


def get_model(model_name='efficientnet_b0', pretrained=True, num_classes=len(LABELS)):
    """
    Create and return the model architecture
    Args:
        model_name (str): 'efficientnet_b0', 'resnet50' or 'densenet121'
        pretrained (bool): Whether to start from ImageNet weights
    Returns:
        model (nn.Module): network producing one logit per disease
    """
    if model_name == 'efficientnet_b0':
        model = models.efficientnet_b0(weights='IMAGENET1K_V1' if pretrained else None)
        num_features = model.classifier[1].in_features
        model.classifier = nn.Sequential(nn.Dropout(0.3), nn.Linear(num_features, num_classes))

    elif model_name == 'resnet50':
        model = models.resnet50(weights='IMAGENET1K_V2' if pretrained else None)
        num_features = model.fc.in_features
        model.fc = nn.Sequential(nn.Dropout(0.3), nn.Linear(num_features, num_classes))

    elif model_name == 'densenet121':
        model = models.densenet121(weights='IMAGENET1K_V1' if pretrained else None)
        num_features = model.classifier.in_features
        model.classifier = nn.Sequential(nn.Dropout(0.3), nn.Linear(num_features, num_classes))

    else:
        raise ValueError(f"Model {model_name} not supported")

    return model


def get_device():
    if torch.cuda.is_available():
        return 'cuda'
    if torch.backends.mps.is_available():
        return 'mps'
    return 'cpu'


def save_checkpoint(path, model, model_name, img_size, thresholds, temperature=None, meta=None, tta=False):
    """meta: JSON-safe run record (run id, data hash, git commit, config, metrics), stored inside the
    checkpoint so the file alone says how it was made. temperature: per-class calibration (None = off)."""
    checkpoint = {
        'model_name': model_name,
        'img_size': img_size,
        'labels': LABELS,
        'thresholds': [float(t) for t in thresholds],
        'state_dict': model.state_dict(),
    }
    if tta:
        checkpoint['tta'] = True  # thresholds / temperature were fitted on flip-averaged logits
    if temperature is not None:
        checkpoint['temperature'] = [float(t) for t in temperature]
    if meta is not None:
        checkpoint['meta'] = json.loads(json.dumps(meta))  # plain types only, so weights_only loading works
    torch.save(checkpoint, path)


def forward_logits(model, x, tta=False):
    """Logits for a batch; with tta they are averaged over the image and its horizontal flip
    (a left and a right eye look alike once flipped, which training already relies on)."""
    logits = model(x)
    if tta:
        logits = (logits + model(torch.flip(x, dims=[-1]))) / 2
    return logits


def calibrated_sigmoid(logits, temperature=None):
    """Per-class probabilities; logits are divided by the checkpoint's temperature when it has one."""
    if temperature is not None:
        logits = logits / torch.as_tensor(temperature, dtype=logits.dtype, device=logits.device)
    return torch.sigmoid(logits)


def load_checkpoint(path, device='cpu'):
    """Return (model, checkpoint dict) with the model in eval mode."""
    checkpoint = torch.load(path, map_location=device, weights_only=True)
    # Older checkpoints were trained on fewer classes (before myopia was added)
    model = get_model(checkpoint['model_name'], pretrained=False, num_classes=len(checkpoint['labels']))
    model.load_state_dict(checkpoint['state_dict'])
    return model.to(device).eval(), checkpoint

