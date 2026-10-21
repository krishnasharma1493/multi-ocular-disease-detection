import argparse
import json
import os
import random

import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader

from preprocess_dataset import OUT_CSV, build_labels
from src.analyze_dataset import analyze_dataset
from src.dataset import ODIR5KDataset, train_transforms, val_transforms
from src.generate_report import generate_pdf_report
from src.labels import DISEASES, LABELS
from src.model import get_device, get_model, save_checkpoint
from src.train import (MaskedBCEWithLogitsLoss, compute_metrics, predict, print_metrics, train_model,
                       tune_thresholds)
from src.utils import plot_confusion_matrices, plot_history


def parse_args():
    parser = argparse.ArgumentParser(description='Train and evaluate the fundus disease classifier')
    parser.add_argument('--model', default='efficientnet_b0', choices=['efficientnet_b0', 'resnet50', 'densenet121'])
    parser.add_argument('--img-size', type=int, default=384)
    parser.add_argument('--epochs', type=int, default=25)
    parser.add_argument('--batch-size', type=int, default=32)
    parser.add_argument('--lr', type=float, default=3e-4)
    parser.add_argument('--patience', type=int, default=6)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--rebuild-labels', action='store_true',
                        help='Regenerate data/labels.csv, e.g. after adding datasets to data/external/')
    parser.add_argument('--demo', action='store_true', help='Launch the Gradio demo after training')
    return parser.parse_args()


def source_summary(data):
    """{source: {'images': n, 'positives': {disease: count}}} for the labels each source provides."""
    summary = {}
    for source, df in data.groupby('source'):
        provided = [l for l in LABELS if df[l].notna().any()]
        summary[source] = {'images': len(df),
                           'positives': {DISEASES[LABELS.index(l)]: int(df[l].sum()) for l in provided}}
    return summary


def seed_everything(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def main():
    args = parse_args()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    seed_everything(args.seed)
    device = get_device()
    os.makedirs('outputs', exist_ok=True)
    print(f'Device: {device}')

    data = pd.read_csv(OUT_CSV) if os.path.exists(OUT_CSV) and not args.rebuild_labels else None
    # Rebuild labels.csv written by older versions (no source column, or missing a newer class)
    if data is None or not {'source', *LABELS} <= set(data.columns):
        data = build_labels()
    analyze_dataset(OUT_CSV)
    splits = {name: data[data['split'] == name] for name in ('train', 'val', 'test')}

    # pos_weight > 1 up-weights the rare positives; sqrt keeps the rarest classes from dominating.
    # Counted over images where each label is known (external datasets only know some labels).
    train_df = splits['train']
    positives, labelled = train_df[LABELS].sum().values, train_df[LABELS].notna().sum().values
    pos_weight = torch.tensor(np.sqrt((labelled - positives) / positives), dtype=torch.float32)
    print('pos_weight:', dict(zip(LABELS, pos_weight.round(decimals=2).tolist())))

    loader_args = dict(batch_size=args.batch_size, num_workers=args.workers,
                       persistent_workers=args.workers > 0)
    train_loader = DataLoader(ODIR5KDataset(splits['train'], train_transforms(args.img_size)),
                              shuffle=True, drop_last=True, **loader_args)
    val_loader = DataLoader(ODIR5KDataset(splits['val'], val_transforms(args.img_size)), **loader_args)
    test_loader = DataLoader(ODIR5KDataset(splits['test'], val_transforms(args.img_size)), **loader_args)

    model = get_model(args.model)
    criterion = MaskedBCEWithLogitsLoss(pos_weight=pos_weight.to(device))
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='max', factor=0.3, patience=2)

    history = train_model(model, train_loader, val_loader, criterion, optimizer, scheduler=scheduler,
                          num_epochs=args.epochs, device=device, patience=args.patience)
    plot_history(history, f'outputs/{args.model}_training_history.png')

    # Thresholds are chosen on validation data only, then applied unchanged to the test set
    val_probs, val_labels, _ = predict(model, val_loader, device)
    thresholds = tune_thresholds(val_labels, val_probs)
    val_metrics = compute_metrics(val_labels, val_probs, thresholds, splits['val']['source'].values)
    test_probs, test_labels, _ = predict(model, test_loader, device)
    test_metrics = compute_metrics(test_labels, test_probs, thresholds, splits['test']['source'].values)
    print_metrics(val_metrics, 'Validation')
    print_metrics(test_metrics, 'Test')

    checkpoint_path = f'outputs/best_{args.model}.pth'
    save_checkpoint(checkpoint_path, model, args.model, args.img_size, thresholds)
    print(f'Checkpoint saved to {checkpoint_path}')

    results = {
        'config': {**vars(args), 'model_name': args.model, 'epochs_trained': len(history['train_loss'])},
        'dataset': {'images': len(data), 'patients': int(data['patient_id'].nunique()),
                    **{name: len(df) for name, df in splits.items()},
                    'sources': source_summary(data)},
        'history': history,
        'validation': val_metrics,
        'test': test_metrics,
    }
    with open('outputs/metrics.json', 'w') as f:
        json.dump(results, f, indent=2)
    plot_confusion_matrices(test_metrics, 'outputs/confusion_matrix.png')
    generate_pdf_report(results)

    if args.demo:
        from src.demo import launch_demo
        launch_demo(checkpoint_path)


if __name__ == '__main__':
    main()
