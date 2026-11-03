"""Training, evaluation and run management behind the `main.py` subcommands.

Each training run gets its own folder, outputs/runs/<date>-<name>/, holding its
config, log, checkpoint, validation metrics and plots. Test metrics are only
computed by `evaluate`, so experiments are compared on validation data and the
test set is scored once per finalist. `promote` copies a run's checkpoint,
metrics and report to outputs/, where the demo reads them.
"""
import contextlib
import glob
import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, WeightedRandomSampler

from preprocess_dataset import OUT_CSV, build_labels
from .analyze_dataset import analyze_dataset
from .calibration import TARGETS, expected_calibration_error, fit_temperature, target_thresholds
from .dataset import FundusDataset, train_transforms, val_transforms
from .generate_report import generate_pdf_report
from .labels import DISEASES, LABELS
from .model import calibrated_sigmoid, get_device, get_model, load_checkpoint, save_checkpoint
from .train import (MaskedBCEWithLogitsLoss, compute_metrics, predict, predict_logits, print_metrics,
                    train_model, tune_thresholds)
from .utils import plot_confusion_matrices, plot_history

RUNS_DIR = 'outputs/runs'
OUTPUTS_DIR = 'outputs'


def seed_everything(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def source_summary(data):
    """{source: {'images': n, 'positives': {disease: count}}} for the labels each source provides."""
    summary = {}
    for source, df in data.groupby('source'):
        provided = [l for l in LABELS if df[l].notna().any()]
        summary[source] = {'images': len(df),
                           'positives': {DISEASES[LABELS.index(l)]: int(df[l].sum()) for l in provided}}
    return summary


def dataset_summary(data):
    return {'images': len(data), 'patients': int(data['patient_id'].nunique()),
            **{name: int((data['split'] == name).sum()) for name in ('train', 'val', 'test')},
            'sources': source_summary(data)}


def load_labels(rebuild=False, labels_csv=OUT_CSV):
    """The labels CSV (default data/labels.csv), rebuilt if asked or if it was written by an older version.
    Only the default file is ever rebuilt here; other files come from `main.py prepare --out`."""
    data = pd.read_csv(labels_csv) if os.path.exists(labels_csv) and not rebuild else None
    if data is None or not {'source', *LABELS} <= set(data.columns):
        if labels_csv != OUT_CSV:
            sys.exit(f'{labels_csv} is missing or out of date; build it with `python main.py prepare --out {labels_csv}`.')
        data = build_labels()
    return data


def data_sha256(labels_csv):
    """Hash of the labels file plus every image's path and size: changes if any label, split or image does."""
    h = hashlib.sha256(open(labels_csv, 'rb').read())
    for path in pd.read_csv(labels_csv)['path']:
        h.update(f'{path}:{os.path.getsize(path) if os.path.exists(path) else -1}\n'.encode())
    return h.hexdigest()


def _file_md5(path):
    with open(path, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()


def _git_commit():
    try:
        out = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True, check=True)
        dirty = subprocess.run(['git', 'status', '--porcelain'], capture_output=True, text=True).stdout.strip()
        return out.stdout.strip() + ('-dirty' if dirty else '')
    except (OSError, subprocess.CalledProcessError):
        return None


class _Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for s in self.streams:
            s.write(text)

    def flush(self):
        for s in self.streams:
            s.flush()


@contextlib.contextmanager
def log_to(path):
    """Copy everything printed to stdout into a log file as well."""
    with open(path, 'a') as f, contextlib.redirect_stdout(_Tee(sys.stdout, f)):
        yield


def _loader(df, transform, args, shuffle=False, balance=0.0):
    """balance > 0 (training only): sample each image with weight 1 / (images in its dataset) ** balance,
    so large single-disease datasets can't dominate an epoch (1 = every dataset equally often)."""
    generator = torch.Generator().manual_seed(args.seed) if shuffle else None
    sampler = None
    if shuffle and balance > 0:
        counts = df['source'].map(df['source'].value_counts()).values
        sampler = WeightedRandomSampler(torch.as_tensor(counts ** -float(balance), dtype=torch.double),
                                        num_samples=len(df), replacement=True, generator=generator)
    return DataLoader(FundusDataset(df, transform), batch_size=args.batch_size, num_workers=args.workers,
                      persistent_workers=args.workers > 0, shuffle=shuffle and sampler is None,
                      sampler=sampler, drop_last=shuffle, generator=generator if sampler is None else None)


def _write_json(path, obj):
    with open(path, 'w') as f:
        json.dump(obj, f, indent=2)


def run_training(args):
    """Train one model into a new run folder; return the folder. Never touches the test split."""
    name = f'{datetime.now():%Y%m%d-%H%M}-{args.name or f"{args.model}-{args.img_size}"}'
    run_dir = os.path.join(RUNS_DIR, name)
    os.makedirs(run_dir, exist_ok=False)
    labels_csv = getattr(args, 'labels_csv', OUT_CSV)
    with log_to(os.path.join(run_dir, 'train.log')):
        seed_everything(args.seed)
        device = get_device()
        print(f'Run {run_dir} | device {device}')
        data = load_labels(args.rebuild_labels, labels_csv)
        analyze_dataset(labels_csv, out_dir=run_dir)
        splits = {name: data[data['split'] == name] for name in ('train', 'val')}
        config = {**vars(args), 'model_name': args.model, 'labels': LABELS, 'git_commit': _git_commit(),
                  'labels_csv': labels_csv, 'labels_csv_md5': _file_md5(labels_csv),
                  'data_sha256': data_sha256(labels_csv), 'run_id': name}
        config.pop('func', None)
        _write_json(os.path.join(run_dir, 'config.json'), config)

        # pos_weight > 1 up-weights the rare positives; sqrt keeps the rarest classes from dominating.
        # Counted over images where each label is known (external datasets only know some labels).
        train_df = splits['train']
        positives, labelled = train_df[LABELS].sum().values, train_df[LABELS].notna().sum().values
        pos_weight = torch.tensor(np.sqrt((labelled - positives) / positives), dtype=torch.float32)
        print('pos_weight:', dict(zip(LABELS, pos_weight.round(decimals=2).tolist())))

        train_loader = _loader(splits['train'], train_transforms(args.img_size, strong=args.strong_aug), args,
                               shuffle=True, balance=args.balance_sources)
        val_loader = _loader(splits['val'], val_transforms(args.img_size), args)
        val_odir = (splits['val']['source'] == 'ODIR').values

        model = get_model(args.model)
        if args.init_checkpoint:
            # Fine-tune: start from an earlier model's weights (same architecture and labels)
            init_model, init = load_checkpoint(args.init_checkpoint, 'cpu')
            if init['model_name'] != args.model or init['labels'] != LABELS:
                sys.exit(f'{args.init_checkpoint} is {init["model_name"]} {init["labels"]}; '
                         f'expected {args.model} {LABELS}.')
            model.load_state_dict(init_model.state_dict())
            config['init_checkpoint_md5'] = _file_md5(args.init_checkpoint)
            print(f'Fine-tuning from {args.init_checkpoint} (trained at {init["img_size"]}px)')
        criterion = MaskedBCEWithLogitsLoss(pos_weight=pos_weight.to(device))
        optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
        if args.scheduler == 'cosine':
            scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs,
                                                                   eta_min=args.lr / 100)
        else:
            scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='max', factor=0.3, patience=2)
        history = train_model(model, train_loader, val_loader, criterion, optimizer, scheduler=scheduler,
                              num_epochs=args.epochs, device=device, patience=args.patience,
                              select_mask=val_odir if args.select_on == 'odir' else None, amp=args.amp)
        plot_history(history, os.path.join(run_dir, f'{args.model}_training_history.png'))

        # Calibration and thresholds use validation data only, then go unchanged to the test set
        val_logits, val_labels, _ = predict_logits(model, val_loader, device, tta=args.tta)
        val_sources = splits['val']['source'].values
        fit_mask = val_odir if args.thresholds == 'targets' else np.ones(len(val_labels), bool)
        temperature = fit_temperature(val_logits[fit_mask], val_labels[fit_mask]) if args.calibrate else None
        val_probs = calibrated_sigmoid(torch.from_numpy(val_logits), temperature).numpy()
        uncalibrated = calibrated_sigmoid(torch.from_numpy(val_logits)).numpy()
        calibration = {'fitted_on': 'ODIR validation' if args.thresholds == 'targets' else 'all validation',
                       'temperature': temperature,
                       'ece_before': expected_calibration_error(val_labels[fit_mask], uncalibrated[fit_mask]),
                       'ece_after': expected_calibration_error(val_labels[fit_mask], val_probs[fit_mask])}
        if args.thresholds == 'targets':
            thresholds, threshold_report = target_thresholds(val_labels[val_odir], val_probs[val_odir])
            print('Thresholds for the sensitivity targets (ODIR validation):')
            for code, r in threshold_report.items():
                print(f'  {code}: t={r["threshold"]:.3f} sens {r["sensitivity"]:.3f} (goal {r["target_sensitivity"]}) '
                      f'spec {r["specificity"]:.3f} (floor {r["specificity_floor"]})'
                      f'{"" if r["target_met"] else "  TARGET NOT MET"}{"" if r["floor_met"] else "  FLOOR NOT MET"}'
                      f'  [{r["positives"]} pos / {r["negatives"]} neg]')
        else:
            thresholds, threshold_report = tune_thresholds(val_labels, val_probs), {'rule': 'max F1, all validation'}
        val_metrics = compute_metrics(val_labels, val_probs, thresholds, val_sources,
                                      splits['val']['patient_id'].astype(str).values, args.n_boot)
        print_metrics(val_metrics, 'Validation')

        config['epochs_trained'] = len(history['train_loss'])
        summary = {'validation': {d: {k: m[k] for k in ('precision', 'recall', 'ap', 'roc_auc')}
                                  for d, m in val_metrics['per_class'].items()},
                   'validation_odir': {d: {k: m[k] for k in ('precision', 'recall', 'ap', 'roc_auc')}
                                       for d, m in val_metrics.get('odir_only', {}).get('per_class', {}).items()}}
        meta = {'run_id': name, 'git_commit': config['git_commit'], 'data_sha256': config['data_sha256'],
                'labels_csv': labels_csv, 'config': config, 'thresholds': thresholds,
                'threshold_rule': args.thresholds, 'threshold_report': threshold_report,
                'calibration': calibration, 'targets': TARGETS, 'metrics': summary}
        save_checkpoint(os.path.join(run_dir, 'checkpoint.pth'), model, args.model, args.img_size, thresholds,
                        temperature=temperature, meta=meta, tta=args.tta)

        _write_json(os.path.join(run_dir, 'config.json'), config)
        _write_json(os.path.join(run_dir, 'metrics.json'), {
            'config': config, 'dataset': dataset_summary(data), 'history': history, 'validation': val_metrics,
            'thresholds': threshold_report, 'calibration': calibration})
        print(f'Run saved to {run_dir}. Compare runs with `python main.py compare`; '
              f'score the test set once with `python main.py evaluate --checkpoint {run_dir}/checkpoint.pth`.')
    return run_dir


def _run_info(checkpoint_path, checkpoint):
    """Config / history / dataset recorded next to a checkpoint, or a minimal config from the checkpoint."""
    path = os.path.join(os.path.dirname(checkpoint_path), 'metrics.json')
    info = json.load(open(path)) if os.path.exists(path) else {}
    config = info.get('config') or {'model_name': checkpoint['model_name'], 'img_size': checkpoint['img_size'],
                                    'lr': 'n/a', 'batch_size': 'n/a', 'epochs_trained': 'n/a'}
    return config, info.get('history')


def run_evaluation(checkpoint_path, split='test', out_dir=None, n_boot=1000, batch_size=32, workers=4,
                   labels_csv=None, force=False):
    """Score a saved checkpoint on one split with its stored thresholds (and calibration); write
    eval_<split>.json (and, for the test split, the confusion matrices and PDF report) to out_dir.

    The test split is scored once per model: a second run stops unless force=True, so the test set
    can't quietly become a tuning set.
    """
    out_dir = out_dir or os.path.dirname(checkpoint_path)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f'eval_{split}.json')
    if split == 'test' and os.path.exists(out_path) and not force:
        sys.exit(f'{out_path} exists: this model has already been scored on the test set. '
                 f'Read that file; pass --force only to re-create it (e.g. after a crash).')
    device = get_device()
    model, checkpoint = load_checkpoint(checkpoint_path, device)
    if checkpoint['labels'] != LABELS:
        sys.exit(f'{checkpoint_path} predicts {checkpoint["labels"]}, but the labels are now {LABELS}.')
    config, history = _run_info(checkpoint_path, checkpoint)
    labels_csv = labels_csv or config.get('labels_csv') or OUT_CSV
    if config.get('labels_csv_md5') and config['labels_csv_md5'] != _file_md5(labels_csv):
        print(f'Warning: {labels_csv} has changed since this model was trained, so the {split} split may '
              f'contain images it was trained on.')

    data = load_labels(labels_csv=labels_csv)
    df = data[data['split'] == split]
    loader = DataLoader(FundusDataset(df, val_transforms(checkpoint['img_size'])), batch_size=batch_size,
                        num_workers=workers, persistent_workers=workers > 0)
    probs, labels, _ = predict(model, loader, device, temperature=checkpoint.get('temperature'),
                               tta=checkpoint.get('tta', False))
    metrics = compute_metrics(labels, probs, checkpoint['thresholds'], df['source'].values,
                              df['patient_id'].astype(str).values, n_boot)
    print_metrics(metrics, f'{split.capitalize()} ({checkpoint_path})')

    _write_json(out_path, {'checkpoint': checkpoint_path, 'checkpoint_md5': _file_md5(checkpoint_path),
                           'run_id': checkpoint.get('meta', {}).get('run_id'), 'labels_csv': labels_csv,
                           'labels_csv_md5': _file_md5(labels_csv), split: metrics})
    if split == 'test':
        plot_confusion_matrices(metrics, os.path.join(out_dir, 'confusion_matrix.png'))
        analyze_dataset(labels_csv, out_dir=out_dir)
        generate_pdf_report({'config': config, 'dataset': dataset_summary(data), 'history': history,
                             'test': metrics},
                            out_path=os.path.join(out_dir, 'eye_disease_report.pdf'), out_dir=out_dir)
    return metrics


def promote(run_dir):
    """Make a run the published model: copy its checkpoint, metrics and report to outputs/."""
    with open(os.path.join(run_dir, 'metrics.json')) as f:
        results = json.load(f)
    test_path = os.path.join(run_dir, 'eval_test.json')
    if not os.path.exists(test_path):
        run_evaluation(os.path.join(run_dir, 'checkpoint.pth'), 'test', run_dir)
    with open(test_path) as f:
        results['test'] = json.load(f)['test']

    model_name = results['config']['model_name']
    shutil.copy(os.path.join(run_dir, 'checkpoint.pth'), os.path.join(OUTPUTS_DIR, f'best_{model_name}.pth'))
    _write_json(os.path.join(OUTPUTS_DIR, 'metrics.json'), {**results, 'run': run_dir})
    for name in ('eye_disease_report.pdf', 'confusion_matrix.png', f'{model_name}_training_history.png',
                 'disease_distribution.png', 'co_occurrence_matrix.png', 'disease_combinations.png'):
        if os.path.exists(os.path.join(run_dir, name)):
            shutil.copy(os.path.join(run_dir, name), os.path.join(OUTPUTS_DIR, name))
    print(f'Promoted {run_dir} to {OUTPUTS_DIR}/best_{model_name}.pth and {OUTPUTS_DIR}/metrics.json')


def compare(runs_dir=RUNS_DIR):
    """Print one row per run: validation mAP (all images and ODIR only) and per-class validation AP."""
    rows = []
    for path in sorted(glob.glob(os.path.join(runs_dir, '*', 'metrics.json'))):
        with open(path) as f:
            m = json.load(f)
        val, config = m['validation'], m['config']
        row = {'run': os.path.basename(os.path.dirname(path)), 'model': config['model_name'],
               'px': config['img_size'], 'epochs': config.get('epochs_trained'),
               'val mAP': val['macro']['mAP'], 'val mAP ODIR': val.get('odir_only', {}).get('macro', {}).get('mAP')}
        for disease, cm in val['per_class'].items():
            row[f'AP {disease.split()[0]}'] = cm['ap']
        test_path = os.path.join(os.path.dirname(path), 'eval_test.json')
        if os.path.exists(test_path):
            with open(test_path) as f:
                row['test mAP'] = json.load(f)['test']['macro']['mAP']
        rows.append(row)
    if not rows:
        print(f'No runs in {runs_dir}/ yet. Train one with `python main.py train`.')
        return None
    table = pd.DataFrame(rows).set_index('run')
    print(table.to_string(float_format=lambda x: f'{x:.3f}'))
    return table
