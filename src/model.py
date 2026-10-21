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


def save_checkpoint(path, model, model_name, img_size, thresholds):
    torch.save({
        'model_name': model_name,
        'img_size': img_size,
        'labels': LABELS,
        'thresholds': [float(t) for t in thresholds],
        'state_dict': model.state_dict(),
    }, path)


def load_checkpoint(path, device='cpu'):
    """Return (model, checkpoint dict) with the model in eval mode."""
    checkpoint = torch.load(path, map_location=device, weights_only=True)
    # Older checkpoints were trained on fewer classes (before myopia was added)
    model = get_model(checkpoint['model_name'], pretrained=False, num_classes=len(checkpoint['labels']))
    model.load_state_dict(checkpoint['state_dict'])
    return model.to(device).eval(), checkpoint

