"""Grad-CAM maps for the screening flow's attention overlay.

The map is computed on the cropped, squared input (crop_fundus), so it lines up
with the square image the web app shows in the lens.
"""
import numpy as np
import torch
import torch.nn.functional as F


def target_layer(model, model_name):
    """Return (layer name, module) whose activations the map is built from."""
    if model_name == 'efficientnet_b0':
        return 'features.8', model.features[-1]
    if model_name == 'resnet50':
        return 'layer4', model.layer4
    if model_name == 'densenet121':
        return 'features.norm5', model.features.norm5
    raise ValueError(f'No Grad-CAM layer known for {model_name}')


def grad_cam(model, x, layer, class_idx):
    """Return an HxW map in [0, 1] for one class, or None when the map is empty."""
    store = {}

    def hook(_module, _inputs, out):
        store['act'] = out
        out.register_hook(lambda g: store.__setitem__('grad', g))

    handle = layer.register_forward_hook(hook)
    try:
        with torch.enable_grad():
            model.zero_grad(set_to_none=True)
            logits = model(x)
            logits[0, class_idx].backward()
    finally:
        handle.remove()
        model.zero_grad(set_to_none=True)
    act, grad = store['act'][0].detach(), store['grad'][0].detach()
    cam = F.relu((grad.mean(dim=(1, 2))[:, None, None] * act).sum(0))
    peak = float(cam.max())
    if not np.isfinite(peak) or peak <= 1e-8:
        return None
    return (cam / peak).cpu().numpy()
