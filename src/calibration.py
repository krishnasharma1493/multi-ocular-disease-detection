"""Probability calibration and sensitivity-first thresholds, fitted on validation data only.

Both are fitted on ODIR validation images (everyday clinic photos, where any of the four diseases can
appear), never on the test split. The test split is scored once, with the stored values, afterwards.
"""
import numpy as np
import torch

from .labels import LABELS, UNKNOWN

# Goal per disease on ODIR photos: (sensitivity to reach, specificity not to drop below).
# Sensitivity comes first: missing a disease is worse than a false alarm that a doctor then clears.
TARGETS = {'M': (0.92, 0.97), 'C': (0.90, 0.95), 'G': (0.70, 0.90), 'D': (0.85, 0.85)}


def fit_temperature(logits, labels, max_iter=200):
    """One temperature per class that minimises the BCE of sigmoid(logit / T) on the known labels.

    Temperature scaling never changes the ranking of images (AUC / AP stay the same); it only makes
    the probabilities honest, e.g. 0.9 means right about 9 times in 10.
    """
    temperatures = []
    for i in range(labels.shape[1]):
        mask = labels[:, i] != UNKNOWN
        x = torch.as_tensor(logits[mask, i], dtype=torch.float64)
        y = torch.as_tensor(labels[mask, i], dtype=torch.float64)
        if len(np.unique(y.numpy())) < 2:
            temperatures.append(1.0)
            continue
        log_t = torch.zeros(1, dtype=torch.float64, requires_grad=True)
        optimizer = torch.optim.LBFGS([log_t], lr=0.1, max_iter=max_iter)

        def closure():
            optimizer.zero_grad()
            loss = torch.nn.functional.binary_cross_entropy_with_logits(x / log_t.exp(), y)
            loss.backward()
            return loss

        optimizer.step(closure)
        temperatures.append(float(np.clip(log_t.exp().item(), 0.05, 20.0)))
    return temperatures


def expected_calibration_error(labels, probs, bins=10):
    """Per class: the average gap between predicted probability and observed frequency, over equal-width bins."""
    out = []
    for i in range(labels.shape[1]):
        mask = labels[:, i] != UNKNOWN
        y, p = labels[mask, i], probs[mask, i]
        if len(y) == 0:
            out.append(float('nan'))
            continue
        idx = np.minimum((p * bins).astype(int), bins - 1)
        out.append(float(sum(abs(p[idx == b].mean() - y[idx == b].mean()) * (idx == b).sum()
                             for b in range(bins) if (idx == b).any()) / len(y)))
    return out


def _rates(y, p, t):
    pred = p >= t
    sens = (pred & (y == 1)).sum() / max((y == 1).sum(), 1)
    spec = (~pred & (y == 0)).sum() / max((y == 0).sum(), 1)
    return float(sens), float(spec)


def target_thresholds(labels, probs, targets=TARGETS, label_order=LABELS):
    """Per class, the threshold that reaches the target sensitivity while keeping the specificity floor.

    Rule, for each disease:
    1. Among thresholds that keep specificity >= floor and reach sensitivity >= target, take the highest
       (the fewest false alarms that still meets the sensitivity goal).
    2. If none reaches the target, take the lowest threshold that keeps the specificity floor (the most
       sensitivity the floor allows) and report target_met = False. The goal is never silently lowered.
    3. If no threshold keeps the floor, report floor_met = False and use the threshold that reaches the
       target sensitivity, so missed disease stays the priority.
    Returns (thresholds, report).
    """
    thresholds, report = [], {}
    for i, code in enumerate(label_order):
        sens_goal, spec_floor = targets[code]
        mask = labels[:, i] != UNKNOWN
        y, p = labels[mask, i].astype(int), probs[mask, i]
        if (y == 1).sum() == 0 or (y == 0).sum() == 0:
            raise ValueError(f'{code}: validation data needs positive and negative images to set a threshold')
        candidates = np.unique(p)
        rates = [(t, *_rates(y, p, t)) for t in candidates]
        meets_floor = [r for r in rates if r[2] >= spec_floor]
        both = [r for r in meets_floor if r[1] >= sens_goal]
        if both:
            choice = max(both, key=lambda r: r[0])
        elif meets_floor:
            choice = min(meets_floor, key=lambda r: r[0])
        else:
            choice = max((r for r in rates if r[1] >= sens_goal), key=lambda r: r[0])
        t, sens, spec = choice
        thresholds.append(float(t))
        report[code] = {'threshold': float(t), 'sensitivity': sens, 'specificity': spec,
                        'target_sensitivity': sens_goal, 'specificity_floor': spec_floor,
                        'target_met': sens >= sens_goal, 'floor_met': spec >= spec_floor,
                        'positives': int((y == 1).sum()), 'negatives': int((y == 0).sum())}
    return thresholds, report
