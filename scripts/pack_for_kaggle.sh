#!/usr/bin/env bash
# Build one zip for a private Kaggle (or Colab) dataset: the committed code (git archive of HEAD,
# including the current checkpoint) plus the preprocessed images and label files, which are not in git.
#   scripts/pack_for_kaggle.sh [out.zip]       (run from the repo root, after committing)
set -euo pipefail
OUT="${1:-retinascreen-kaggle.zip}"
cd "$(git rev-parse --show-toplevel)"
for f in data/labels.csv data/labels_v2.csv data/full_df.csv data/preprocessed_images data/external_preprocessed; do
  [ -e "$f" ] || { echo "Missing $f (build data/labels_v2.csv first, see docs/RETRAINING.md)"; exit 1; }
done
[ -z "$(git status --porcelain -- src main.py preprocess_dataset.py)" ] || { echo "Commit the training code first"; exit 1; }
TMP="$(mktemp -d)"
git archive --format=tar --prefix=repo/ HEAD | tar -x -C "$TMP"
mkdir -p "$TMP/repo/data"
cp data/labels.csv data/labels_v2.csv data/full_df.csv "$TMP/repo/data/"
ln -s "$PWD/data/preprocessed_images" "$TMP/repo/data/preprocessed_images"
ln -s "$PWD/data/external_preprocessed" "$TMP/repo/data/external_preprocessed"
(cd "$TMP" && zip -qr "$OLDPWD/$OUT" repo)
rm -rf "$TMP"
echo "Wrote $OUT ($(du -h "$OUT" | cut -f1)); git commit $(git rev-parse --short HEAD)"
