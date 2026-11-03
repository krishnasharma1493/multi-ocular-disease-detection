import copy

import numpy as np
import torch
from sklearn.metrics import (average_precision_score, confusion_matrix, precision_recall_curve,
                             precision_recall_fscore_support, roc_auc_score)
from tqdm import tqdm

from .labels import DISEASES, UNKNOWN
from .model import calibrated_sigmoid


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
                num_epochs=20, device='cuda', patience=5, select_mask=None, amp=False):
    """
    Train the model, keeping the weights with the best validation mAP.

    select_mask: boolean array over the validation images. When given, the best epoch is chosen on
    those images only (e.g. ODIR photos), so easy external datasets can't hide a weak everyday model.
    amp: mixed precision on CUDA (about 2x faster on a T4); ignored on other devices.
    Returns a history dict with per-epoch train loss, val loss, val mAP and the selection mAP.
    """
    model = model.to(device)
    use_amp = amp and str(device).startswith('cuda')
    scaler = torch.amp.GradScaler('cuda', enabled=use_amp)
    history = {'train_loss': [], 'val_loss': [], 'val_map': [], 'select_map': []}
    best_map, best_state, epochs_without_improvement = -1.0, None, 0

    for epoch in range(num_epochs):
        model.train()
        train_loss, seen = 0.0, 0
        for images, labels in tqdm(train_loader, desc=f'Epoch {epoch+1}/{num_epochs} [Train]'):
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad()
            with torch.autocast('cuda', dtype=torch.float16, enabled=use_amp):
                loss = criterion(model(images).float(), labels)
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            train_loss += loss.item() * len(images)
            seen += len(images)
        train_loss /= max(seen, 1)

        probs, labels, val_loss = predict(model, val_loader, device, criterion)
        val_map = float(np.nanmean(per_class_ap(labels, probs)))
        select_map = (float(np.nanmean(per_class_ap(labels[select_mask], probs[select_mask])))
                      if select_mask is not None else val_map)
        if isinstance(scheduler, torch.optim.lr_scheduler.ReduceLROnPlateau):
            scheduler.step(select_map)
        elif scheduler is not None:
            scheduler.step()

        history['train_loss'].append(train_loss)
        history['val_loss'].append(val_loss)
        history['val_map'].append(val_map)
        history['select_map'].append(select_map)
        print(f'Epoch {epoch+1}/{num_epochs}: train loss {train_loss:.4f} | '
              f'val loss {val_loss:.4f} | val mAP {val_map:.4f}'
              + (f' | selection mAP {select_map:.4f}' if select_mask is not None else ''))

        if select_map > best_map:
            best_map, epochs_without_improvement = select_map, 0
            best_state = copy.deepcopy(model.state_dict())
        else:
            epochs_without_improvement += 1
            if epochs_without_improvement >= patience:
                print(f'Early stopping after {epoch+1} epochs')
                break

    model.load_state_dict(best_state)
    print(f'Restored weights with best selection mAP {best_map:.4f}')
    return history


@torch.no_grad()
def predict_logits(model, loader, device, criterion=None):
    """Return (logits, labels, mean loss) as numpy arrays."""
    model.eval()
    all_logits, all_labels, total_loss = [], [], 0.0
    for images, labels in tqdm(loader, desc='Predicting', leave=False):
        images, labels = images.to(device), labels.to(device)
        logits = model(images)
        if criterion is not None:
            total_loss += criterion(logits, labels).item() * len(images)
        all_logits.append(logits.float().cpu())
        all_labels.append(labels.cpu())
    return (torch.cat(all_logits).numpy(), torch.cat(all_labels).numpy(),
            total_loss / len(loader.dataset))


def predict(model, loader, device, criterion=None, temperature=None):
    """Return (probabilities, labels, mean loss) as numpy arrays (calibrated when a temperature is given)."""
    logits, labels, loss = predict_logits(model, loader, device, criterion)
    return calibrated_sigmoid(torch.from_numpy(logits), temperature).numpy(), labels, loss


def known(labels, probs, i):
    """Labels and probabilities of class i for the images where that label is known."""
    mask = labels[:, i] != UNKNOWN
    return labels[mask, i].astype(int), probs[mask, i]


def per_class_ap(labels, probs):
    """AP per class; NaN for a class with no positives or no negatives among these images."""
    out = []
    for i in range(labels.shape[1]):
        y, p = known(labels, probs, i)
        out.append(average_precision_score(y, p) if len(np.unique(y)) == 2 else float('nan'))
    return out


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
    negatives = (labels == 0).sum()
    specificity = float(((preds == 0) & (labels == 0)).sum() / negatives) if negatives else float('nan')
    return {
        'precision': float(precision), 'recall': float(recall), 'f1': float(f1), 'specificity': specificity,
        'ap': float(average_precision_score(labels, probs)) if both_classes else float('nan'),
        'roc_auc': float(roc_auc_score(labels, probs)) if both_classes else float('nan'),
        'support': int(labels.sum()), 'num_images': int(len(labels)), 'threshold': float(threshold),
        'confusion_matrix': confusion_matrix(labels, preds, labels=[0, 1]).tolist(),
    }


def bootstrap_ci(labels, probs, groups, n_boot=1000, seed=0, thresholds=None):
    """95% bootstrap intervals for per-class AP, ROC-AUC and macro mAP (plus sensitivity and specificity
    at the given thresholds, when thresholds are passed).

    Patients (groups) are resampled with replacement, so both eyes of a patient
    move together. Each image is weighted by how often its patient was drawn,
    which gives the same scores as copying the images.
    """
    rng = np.random.default_rng(seed)
    _, group_idx = np.unique(groups, return_inverse=True)
    n_groups = group_idx.max() + 1
    scores = {'ap': [], 'roc_auc': [], 'recall': [], 'specificity': []}
    for _ in range(n_boot):
        weights = np.bincount(rng.integers(0, n_groups, n_groups), minlength=n_groups)[group_idx]
        ap, auc, rec, spec = [], [], [], []
        for i in range(labels.shape[1]):
            mask = (labels[:, i] != UNKNOWN) & (weights > 0)
            y, p, w = labels[mask, i].astype(int), probs[mask, i], weights[mask]
            if thresholds is not None:
                pred = p >= thresholds[i]
                rec.append(np.sum(w * pred * (y == 1)) / max(np.sum(w * (y == 1)), 1e-12) if (y == 1).any() else np.nan)
                spec.append(np.sum(w * ~pred * (y == 0)) / max(np.sum(w * (y == 0)), 1e-12) if (y == 0).any() else np.nan)
            if len(np.unique(y)) < 2:
                ap.append(np.nan), auc.append(np.nan)
                continue
            ap.append(average_precision_score(y, p, sample_weight=w))
            auc.append(roc_auc_score(y, p, sample_weight=w))
        scores['ap'].append(ap)
        scores['roc_auc'].append(auc)
        if thresholds is not None:
            scores['recall'].append(rec)
            scores['specificity'].append(spec)
    ci = {}
    for key, values in scores.items():
        if not values:
            continue
        values = np.array(values, dtype=float)
        ci[key] = [[float(x) for x in np.nanpercentile(values[:, i], [2.5, 97.5])] for i in range(labels.shape[1])]
    macro = np.nanmean(np.array(scores['ap']), axis=1)
    ci['mAP'] = [float(x) for x in np.nanpercentile(macro, [2.5, 97.5])]
    return ci


def _class_metrics(labels, probs, thresholds, groups=None, n_boot=0):
    """Per-class, macro and micro metrics on images where each label is known."""
    per_class, tp, fp, fn = {}, 0, 0, 0
    for i, disease in enumerate(DISEASES):
        y, p = known(labels, probs, i)
        per_class[disease] = binary_metrics(y, p, thresholds[i])
        (_, fp_i), (fn_i, tp_i) = per_class[disease]['confusion_matrix']
        tp, fp, fn = tp + tp_i, fp + fp_i, fn + fn_i

    macro = {k: float(np.nanmean([m[k] for m in per_class.values()]))
             for k in ('precision', 'recall', 'f1', 'ap', 'roc_auc')}
    micro_p, micro_r = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
    metrics = {
        'macro': {**macro, 'mAP': macro.pop('ap')},
        'micro': {'precision': micro_p, 'recall': micro_r,
                  'f1': 2 * micro_p * micro_r / max(micro_p + micro_r, 1e-8)},
        'per_class': per_class,
        'num_images': int(len(labels)),
    }
    if groups is not None and n_boot:
        ci = bootstrap_ci(labels, probs, groups, n_boot, thresholds=thresholds)
        for i, m in enumerate(per_class.values()):
            m['ap_ci'], m['roc_auc_ci'] = ci['ap'][i], ci['roc_auc'][i]
            m['recall_ci'], m['specificity_ci'] = ci['recall'][i], ci['specificity'][i]
        metrics['macro']['mAP_ci'] = ci['mAP']
    return metrics


def compute_metrics(labels, probs, thresholds, sources=None, groups=None, n_boot=0):
    """Per-class and averaged precision / recall / F1 / AP / ROC-AUC.

    Each class is scored only on the images where its label is known. If sources
    is given, ODIR images are also scored on their own ('odir_only': realistic
    photos where any of the diseases can appear), and every class labelled by
    more than one dataset is scored per dataset: pooling datasets with very
    different prevalence can inflate AUC just by telling the datasets apart.
    With groups (patient ids) and n_boot > 0, AP / AUC get 95% bootstrap intervals.
    """
    metrics = _class_metrics(labels, probs, thresholds, groups, n_boot)
    if sources is not None:
        odir = sources == 'ODIR'
        if odir.any():
            metrics['odir_only'] = _class_metrics(labels[odir], probs[odir], thresholds,
                                                  None if groups is None else groups[odir], n_boot)
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


def _fmt_ci(m, key):
    ci = m.get(f'{key}_ci')
    return f' [{ci[0]:.2f}-{ci[1]:.2f}]' if ci else ''


def _print_table(metrics, title):
    print(f'\n{title} ({metrics["num_images"]} images)')
    print(f'{"":26}{"Prec":>7}{"Recall":>8}{"F1":>7}{"AP":>7}{"AUC":>7}{"n":>6}')
    for disease, m in metrics['per_class'].items():
        print(f'{disease:26}{m["precision"]:7.3f}{m["recall"]:8.3f}{m["f1"]:7.3f}'
              f'{m["ap"]:7.3f}{m["roc_auc"]:7.3f}{m["support"]:6d}'
              f'{"   Sens" + _fmt_ci(m, "recall") + "  AP" + _fmt_ci(m, "ap") + "  AUC" + _fmt_ci(m, "roc_auc") if "ap_ci" in m else ""}')
    macro = metrics['macro']
    print(f'{"Macro average":26}{macro["precision"]:7.3f}{macro["recall"]:8.3f}{macro["f1"]:7.3f}'
          f'{macro["mAP"]:7.3f}{macro["roc_auc"]:7.3f}{"":6}{"   mAP" + _fmt_ci(macro, "mAP") if "mAP_ci" in macro else ""}')


def print_metrics(metrics, title):
    _print_table(metrics, title)
    if 'odir_only' in metrics:
        _print_table(metrics['odir_only'], f'{title}, ODIR only')
    for disease, by_source in metrics.get('by_source', {}).items():
        for source, m in by_source.items():
            # Last word keeps rows short ('Myopia @ PALM')
            print(f'{"  " + disease.split()[-1] + " @ " + source:26}{m["precision"]:7.3f}{m["recall"]:8.3f}'
                  f'{m["f1"]:7.3f}{m["ap"]:7.3f}{m["roc_auc"]:7.3f}{m["support"]:6d}')
