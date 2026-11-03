# Retraining the screening model

This guide fine-tunes the current EfficientNet-B0 on a free Kaggle GPU. It's prepared but **not run**: start it only after approval. The app keeps using `outputs/best_efficientnet_b0.pth` until a new run is promoted on purpose.

## What changes compared with the current model

| Change | Why | Flag |
|---|---|---|
| ODIR eyes with other diseases (AMD, drusen, epiretinal membrane, hypertensive retinopathy, …) become negatives for all four diseases. "Refractive media opacity" stays out because it looks like cataract. | The current model has never seen lookalikes, so drusen and exudate-like dots read as DR. | `prepare --other-disease-negatives` |
| Every patient keeps the split it had in `data/labels.csv`. New patients are split 80/10/10 by a hash of their ID. | The fine-tune starts from the current model, so its training patients must never land in validation or test. | `--keep-splits-from data/labels.csv` |
| Specialist datasets stay "unknown" for the diseases they don't label. This is already the case and is unchanged. | Without it, an ACRIMA photo would count as "no cataract" without evidence. | — |
| Fine-tune from the current weights at 512 px with a cosine learning rate and mixed precision. | The optic disc (glaucoma) and microaneurysms (mild DR) are tiny at 384 px. A warm start needs about 8 epochs, not 25. | `--init-checkpoint --img-size 512 --scheduler cosine --amp` |
| Camera-variation augmentation: exposure, colour, CLAHE, mild noise and blur, JPEG, low resolution. Blur stays mild because haze is the sign of cataract. | Helps on photos unlike the training sets. | `--strong-aug` |
| Balanced sampling across datasets (weight = 1/size^0.5). | Large single-disease datasets dominate otherwise, and the model can learn which dataset a photo came from instead of the disease. | `--balance-sources 0.5` |
| The best epoch is chosen on ODIR validation photos. | The specialist datasets score about 100% and hide a weak everyday model. | `--select-on odir` |
| Per-class temperature calibration and thresholds for the sensitivity targets, both fitted on **ODIR validation only**. | Sensitivity first. The percentages shown become honest. | `--thresholds targets --calibrate` |
| Run ID, data hash (labels file + every image's path and size), config, git commit, validation metrics, thresholds and their report, all saved **inside** the checkpoint. | Any result can be traced to one run. The app stores the run ID and checkpoint hash with every result. | automatic |

The targets are in `src/calibration.py` `TARGETS` and are scored on ODIR photos:

| Disease | Sensitivity goal | Specificity floor | Current, held-out ODIR test (95% range) |
|---|---|---|---|
| Diabetic retinopathy | ≥ 85% | ≥ 85% | 67.1% (59–74%) |
| Glaucoma | ≥ 70% | ≥ 90% | 44.4% (25–64%) |
| Cataract | ≥ 90% | ≥ 95% | 79.3% (59–96%) |
| Myopia | ≥ 92% | ≥ 97% | 88.0% (73–100%) |

If a target can't be met inside its specificity floor on validation, the run prints `TARGET NOT MET` and keeps the floor. The goal is never quietly lowered. The ODIR validation set has only about 25–30 eyes each for myopia, cataract and glaucoma, so those thresholds are noisy (one eye is about 4 points).

## The test set is untouched

`train` never reads the test split. `evaluate` scores it once per model and then refuses to run again, unless you pass `--force` after a crash. Compare candidate runs with `python main.py compare`, which uses validation scores only.

## Steps

### 1. Build the new labels file (local, about 1 minute)
This writes `data/labels_v2.csv` and leaves `data/labels.csv` unchanged.
```bash
.venv/bin/python main.py prepare --other-disease-negatives --keep-splits-from data/labels.csv --out data/labels_v2.csv
```
Expected: 9,566 images, 867 added negatives (685 train / 94 val / 88 test), 0 patients in two splits. This was checked with a dry run.

### 2. Pack code and data (local, about 2 minutes, about 560 MB)
```bash
scripts/pack_for_kaggle.sh retinascreen-kaggle.zip
```

### 3. Upload to Kaggle
kaggle.com → Datasets → New dataset → upload the zip → keep it **Private** → name it `retinascreen-data`.

### 4. Kaggle notebook (Settings: Accelerator **GPU T4 x1**, Internet **on**)
```bash
!cp -r /kaggle/input/retinascreen-data/repo /kaggle/working/repo
%cd /kaggle/working/repo
!pip install -q "albumentations==2.0.8" reportlab
!nvidia-smi --query-gpu=name,memory.total --format=csv

!python main.py train --name b0-512-ft --labels-csv data/labels_v2.csv \
    --init-checkpoint outputs/best_efficientnet_b0.pth --img-size 512 --epochs 8 --lr 1e-4 --batch-size 32 \
    --scheduler cosine --amp --strong-aug --balance-sources 0.5 --select-on odir \
    --thresholds targets --calibrate --workers 4 --patience 4
!python main.py compare
```
Estimate: about 5 minutes per epoch, so about 45 minutes in total. This is a guess; check the first epoch's time.

Then score the test set **once**, on the run you'd ship:
```bash
!python main.py evaluate --checkpoint outputs/runs/<run>/checkpoint.pth --workers 4
!cd outputs/runs && zip -qr /kaggle/working/run.zip <run>
```
Download `run.zip` from the notebook's Output panel.

Colab works the same way: upload the zip to Drive, unzip it, use `--workers 2`, and pick a T4 runtime.

### 5. Back on your machine (needs approval before going live)
```bash
unzip run.zip -d outputs/runs/
.venv/bin/python main.py compare
.venv/bin/python main.py promote outputs/runs/<run>          # makes it the app's model
cd backend && ../.venv/bin/python -m tests.golden.update     # re-record the golden set, review the diff
```
Then raise `RECALL_FLOORS` in `backend/tests/test_regression.py` to about 5 points under the new ODIR validation sensitivity. Run `cd backend && ../.venv/bin/python -m pytest tests`, and restart the app.

Promote only if every ODIR test sensitivity range overlaps or beats the current one, **and** DR false alarms on the 88 new other-disease test eyes go down. Score the current model on `data/labels_v2.csv` too, for a like-for-like comparison: `python main.py evaluate --checkpoint outputs/best_efficientnet_b0.pth --labels-csv data/labels_v2.csv --out-dir outputs/eval_v2_baseline`.

## Recommended outside test set (not added yet)

**IDRiD**, the Indian Diabetic Retinopathy Image Dataset: the "Disease Grading" part, 516 fundus photos from an eye clinic in Nanded, India, graded DR 0–4 by experts. It's licensed **CC BY 4.0** (IEEE DataPort): free to use with attribution. Check the licence on the download page before use.

Why IDRiD: none of our training sources include it. It's a different camera and clinic, from the same population the screening camps serve, and DR is the class with the most real-world volume. It tests DR only. For glaucoma, an outside set such as REFUGE needs registration and has research-only terms, so it needs a separate licence check.

How to use it: score it once per final model as a pure outside test. Never use it for training, thresholds or picking runs.
