import copy

import numpy as np
import torch
from sklearn.metrics import (average_precision_score, confusion_matrix, precision_recall_curve,
                             precision_recall_fscore_support, roc_auc_score)
from tqdm import tqdm

from .labels import DISEASES, UNKNOWN


class MaskedBCEWithLogitsLoss(torch.nn.Module):
    """BCEWithLogitsLoss that ignores targets equal to UNKNOWN (labels a dataset doesn't provide)."""

    def __init__(self, pos_weight=None):
        super().__init__()
        self.bce = torch.nn.BCEWithLogitsLoss(pos_weight=pos_weight, reduction='none')

    def forward(self, logits, targets):
        known = (targets != UNKNOWN).float()
        loss = self.bce(logits, targets.clamp(min=0)) * known
        return loss.sum() / known.sum().clamp(min=1)


def train_model(model, train_loader, val_loader, criterion, optimizer, scheduler=None,
                num_epochs=20, device='cuda', patience=5):
    """
    Train the model, keeping the weights with the best validation mAP.
    Returns a history dict with per-epoch train loss, val loss and val mAP.
    """
    model = model.to(device)
    history = {'train_loss': [], 'val_loss': [], 'val_map': []}
    best_map, best_state, epochs_without_improvement = -1.0, None, 0

    for epoch in range(num_epochs):
        model.train()
        train_loss = 0.0
        for images, labels in tqdm(train_loader, desc=f'Epoch {epoch+1}/{num_epochs} [Train]'):
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad()
            loss = criterion(model(images), labels)
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * len(images)
        train_loss /= len(train_loader.dataset)

        probs, labels, val_loss = predict(model, val_loader, device, criterion)
        val_map = float(np.mean(per_class_ap(labels, probs)))
        if scheduler is not None:
            scheduler.step(val_map)

        history['train_loss'].append(train_loss)
        history['val_loss'].append(val_loss)
        history['val_map'].append(val_map)
        print(f'Epoch {epoch+1}/{num_epochs}: train loss {train_loss:.4f} | '
              f'val loss {val_loss:.4f} | val mAP {val_map:.4f}')

        if val_map > best_map:
            best_map, epochs_without_improvement = val_map, 0
            best_state = copy.deepcopy(model.state_dict())
        else:
            epochs_without_improvement += 1
            if epochs_without_improvement >= patience:
                print(f'Early stopping after {epoch+1} epochs')
                break

    model.load_state_dict(best_state)
    print(f'Restored weights with best val mAP {best_map:.4f}')
    return history


@torch.no_grad()
def predict(model, loader, device, criterion=None):
    """Return (sigmoid probabilities, labels, mean loss) as numpy arrays."""
    model.eval()
    all_probs, all_labels, total_loss = [], [], 0.0
    for images, labels in tqdm(loader, desc='Predicting', leave=False):
        images, labels = images.to(device), labels.to(device)
        logits = model(images)
        if criterion is not None:
            total_loss += criterion(logits, labels).item() * len(images)
        all_probs.append(torch.sigmoid(logits).cpu())
        all_labels.append(labels.cpu())
    return (torch.cat(all_probs).numpy(), torch.cat(all_labels).numpy(),
            total_loss / len(loader.dataset))


def known(labels, probs, i):
    """Labels and probabilities of class i for the images where that label is known."""
    mask = labels[:, i] != UNKNOWN
    return labels[mask, i].astype(int), probs[mask, i]


def per_class_ap(labels, probs):
    return [average_precision_score(*known(labels, probs, i)) for i in range(labels.shape[1])]


def tune_thresholds(labels, probs):
    """Per-class decision threshold that maximises F1 (fit on the validation set)."""
    thresholds = []
    for i in range(labels.shape[1]):
        precision, recall, cuts = precision_recall_curve(*known(labels, probs, i))
        f1 = 2 * precision * recall / np.clip(precision + recall, 1e-8, None)
        thresholds.append(float(cuts[np.argmax(f1[:-1])]))
    return thresholds


def binary_metrics(labels, probs, threshold):
    """Precision / recall / F1 / AP / ROC-AUC for one class (labels all known)."""
    preds = (probs >= threshold).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(
        labels, preds, average='binary', zero_division=0)
    both_classes = len(np.unique(labels)) == 2
    return {
        'precision': float(precision), 'recall': float(recall), 'f1': float(f1),
        'ap': float(average_precision_score(labels, probs)) if both_classes else float('nan'),
        'roc_auc': float(roc_auc_score(labels, probs)) if both_classes else float('nan'),
        'support': int(labels.sum()), 'num_images': int(len(labels)), 'threshold': float(threshold),
        'confusion_matrix': confusion_matrix(labels, preds, labels=[0, 1]).tolist(),
    }


def compute_metrics(labels, probs, thresholds, sources=None):
    """Per-class and averaged precision / recall / F1 / AP / ROC-AUC.

    Each class is scored only on the images where its label is known. If sources
    is given, every class labelled by more than one dataset is also scored per
    dataset: pooling datasets with very different prevalence can inflate AUC just
    by telling the datasets apart.
    """
    per_class, tp, fp, fn = {}, 0, 0, 0
    for i, disease in enumerate(DISEASES):
        y, p = known(labels, probs, i)
        per_class[disease] = binary_metrics(y, p, thresholds[i])
        (_, fp_i), (fn_i, tp_i) = per_class[disease]['confusion_matrix']
        tp, fp, fn = tp + tp_i, fp + fp_i, fn + fn_i

    macro = {k: float(np.mean([m[k] for m in per_class.values()]))
             for k in ('precision', 'recall', 'f1', 'ap', 'roc_auc')}
    micro_p, micro_r = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
    metrics = {
        'macro': {**macro, 'mAP': macro.pop('ap')},
        'micro': {'precision': micro_p, 'recall': micro_r,
                  'f1': 2 * micro_p * micro_r / max(micro_p + micro_r, 1e-8)},
        'per_class': per_class,
        'num_images': int(len(labels)),
    }
    if sources is not None:
        metrics['by_source'] = {}
        for i, disease in enumerate(DISEASES):
            mask = labels[:, i] != UNKNOWN
            labelled_by = np.unique(sources[mask])
            if len(labelled_by) > 1:
                metrics['by_source'][disease] = {
                    source: binary_metrics(labels[mask & (sources == source), i].astype(int),
                                           probs[mask & (sources == source), i], thresholds[i])
                    for source in labelled_by}
    return metrics


def print_metrics(metrics, title):
    print(f'\n{title} ({metrics["num_images"]} images)')
    print(f'{"":26}{"Prec":>7}{"Recall":>8}{"F1":>7}{"AP":>7}{"AUC":>7}{"n":>6}')
    for disease, m in metrics['per_class'].items():
        print(f'{disease:26}{m["precision"]:7.3f}{m["recall"]:8.3f}{m["f1"]:7.3f}'
              f'{m["ap"]:7.3f}{m["roc_auc"]:7.3f}{m["support"]:6d}')
    macro = metrics['macro']
    print(f'{"Macro average":26}{macro["precision"]:7.3f}{macro["recall"]:8.3f}{macro["f1"]:7.3f}'
          f'{macro["mAP"]:7.3f}{macro["roc_auc"]:7.3f}')
    for disease, by_source in metrics.get('by_source', {}).items():
        for source, m in by_source.items():
            # Last word keeps rows short ('Myopia @ PALM')
            print(f'{"  " + disease.split()[-1] + " @ " + source:26}{m["precision"]:7.3f}{m["recall"]:8.3f}'
                  f'{m["f1"]:7.3f}{m["ap"]:7.3f}{m["roc_auc"]:7.3f}{m["support"]:6d}')
