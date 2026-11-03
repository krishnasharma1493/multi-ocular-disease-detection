"""Command-line entry point for the fundus disease classifier (M, C, G, D).

    python main.py prepare                 # build data/labels.csv and dataset plots
    python main.py train --name b0-384     # train into outputs/runs/<date>-b0-384/
    python main.py compare                 # validation scores of all runs
    python main.py evaluate --checkpoint outputs/runs/<run>/checkpoint.pth   # test set, once per finalist
    python main.py promote outputs/runs/<run>   # publish to outputs/ for the demo

Fine-tune (see docs/RETRAINING.md):
    python main.py prepare --other-disease-negatives --keep-splits-from data/labels.csv --out data/labels_v2.csv
    python main.py train --name b0-512-ft --labels-csv data/labels_v2.csv \
        --init-checkpoint outputs/best_efficientnet_b0.pth --img-size 512 --epochs 8 --lr 1e-4 \
        --scheduler cosine --amp --strong-aug --balance-sources 0.5 --select-on odir --thresholds targets --calibrate
"""
import argparse
import os

from preprocess_dataset import OUT_CSV, build_labels


def add_train_args(parser):
    parser.add_argument('--name', help='Run name (default: <model>-<img-size>)')
    parser.add_argument('--model', default='efficientnet_b0', choices=['efficientnet_b0', 'resnet50', 'densenet121'])
    parser.add_argument('--img-size', type=int, default=384)
    parser.add_argument('--epochs', type=int, default=25)
    parser.add_argument('--batch-size', type=int, default=32)
    parser.add_argument('--lr', type=float, default=3e-4)
    parser.add_argument('--patience', type=int, default=6)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--n-boot', type=int, default=1000, help='Bootstrap resamples for confidence intervals')
    parser.add_argument('--rebuild-labels', action='store_true',
                        help='Regenerate data/labels.csv first, e.g. after adding datasets to data/external/')
    parser.add_argument('--labels-csv', default=OUT_CSV, help='Labels file to train on (default data/labels.csv)')
    parser.add_argument('--init-checkpoint', help='Fine-tune: start from this checkpoint\'s weights')
    parser.add_argument('--strong-aug', action='store_true', help='Camera-variation augmentation (see dataset.py)')
    parser.add_argument('--balance-sources', type=float, default=0.0,
                        help='Sample images with weight 1/(dataset size)^x; 0 = off, 0.5 = soften, 1 = equal')
    parser.add_argument('--scheduler', default='plateau', choices=['plateau', 'cosine'])
    parser.add_argument('--amp', action='store_true', help='Mixed precision on CUDA')
    parser.add_argument('--select-on', default='all', choices=['all', 'odir'],
                        help='Validation images used to pick the best epoch')
    parser.add_argument('--thresholds', default='f1', choices=['f1', 'targets'],
                        help='f1: max F1 on all validation; targets: sensitivity targets on ODIR validation')
    parser.add_argument('--calibrate', action='store_true',
                        help='Fit per-class temperature scaling on validation (ODIR only with --thresholds targets)')


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)

    prepare = commands.add_parser('prepare', help='Build data/labels.csv (per-eye labels, patient-level splits) and plots')
    prepare.add_argument('--out', default=OUT_CSV, help='Where to write the labels file')
    prepare.add_argument('--other-disease-negatives', action='store_true',
                         help='Keep ODIR eyes with other diseases (AMD, drusen, ...) as negatives for all four')
    prepare.add_argument('--keep-splits-from',
                         help='Existing labels file: its patients keep their split; external rows are reused')
    commands.add_parser('analyze', help='Redraw the dataset plots in outputs/ from data/labels.csv')
    add_train_args(commands.add_parser('train', help='Train a model into a new run folder'))
    commands.add_parser('compare', help='Print validation scores of all runs')

    evaluate = commands.add_parser('evaluate', help='Score a saved checkpoint with its stored thresholds')
    evaluate.add_argument('--checkpoint', default='outputs/best_efficientnet_b0.pth')
    evaluate.add_argument('--split', default='test', choices=['val', 'test'])
    evaluate.add_argument('--out-dir', help='Where to write eval_<split>.json (default: next to the checkpoint)')
    evaluate.add_argument('--n-boot', type=int, default=1000)
    evaluate.add_argument('--workers', type=int, default=4)
    evaluate.add_argument('--labels-csv', help='Labels file (default: the one the model was trained on)')
    evaluate.add_argument('--force', action='store_true', help='Re-score a split that was already scored')

    promote = commands.add_parser('promote', help='Copy a run to outputs/ as the published model')
    promote.add_argument('run_dir')
    return parser.parse_args()


def main():
    args = parse_args()
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    # Imported here so `prepare` works without loading torch-heavy modules first
    from src import pipeline
    from src.analyze_dataset import analyze_dataset

    if args.command == 'prepare':
        build_labels(out_csv=args.out, other_disease_negatives=args.other_disease_negatives,
                     keep_splits_from=args.keep_splits_from)
        if args.out == OUT_CSV:
            analyze_dataset(OUT_CSV)
    elif args.command == 'analyze':
        analyze_dataset(OUT_CSV)
    elif args.command == 'train':
        pipeline.run_training(args)
    elif args.command == 'compare':
        pipeline.compare()
    elif args.command == 'evaluate':
        pipeline.run_evaluation(args.checkpoint, args.split, args.out_dir, args.n_boot, workers=args.workers,
                                labels_csv=args.labels_csv, force=args.force)
    elif args.command == 'promote':
        pipeline.promote(args.run_dir)


if __name__ == '__main__':
    main()
