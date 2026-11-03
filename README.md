# Multi-Ocular Disease Detection

<p>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white">
  <img alt="PyTorch" src="https://img.shields.io/badge/PyTorch-2.0%2B-EE4C2C?logo=pytorch&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white">
  <img alt="React" src="https://img.shields.io/badge/React-TypeScript-61DAFB?logo=react&logoColor=black">
</p>

This repository contains a research prototype that screens retinal fundus photographs for pathological myopia, cataract, glaucoma, and diabetic retinopathy.

## Problem

Retinal images can show more than one disease, while public datasets often label only the conditions they were collected to study. A useful screening prototype needs to predict several conditions independently and avoid treating an unlabelled condition as a confirmed negative.

## Approach

The project fine-tunes an ImageNet-pretrained EfficientNet-B0 model for four-label prediction. Its training pipeline combines ODIR-5K with optional external fundus datasets, uses a masked loss for unknown labels, and creates patient-level train, validation, and test splits. Decision thresholds are selected on the validation split. The RetinaScreen web app (FastAPI backend + React frontend) runs the model on uploaded photos and shows a Grad-CAM attention map for positive results.

This is research software, not a medical device. Its predictions are not a diagnosis and must not be used as a substitute for clinical review.

## Requirements

- Python 3.10 or newer
- Dataset files placed locally as described below
- CUDA or Apple Silicon MPS is optional; CPU is supported

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Prepare data and train

Dataset files are not included in this repository. Download ODIR-5K from [Kaggle](https://www.kaggle.com/datasets/andrewmvd/ocular-disease-recognition-odir5k), follow its terms, and place the metadata and preprocessed images at:

```text
data/full_df.csv
data/preprocessed_images/<image files>
```

Generate per-eye labels and patient-level splits, then train and evaluate:

```bash
python preprocess_dataset.py
python main.py
```

Optional external datasets go under `data/external/<dataset-name>/`. The ingestion code recognizes several common label-sheet, folder, and filename conventions; see `src/external_datasets.py` for the supported formats. Check each dataset's license before using it. Training writes metrics, plots, and a PDF report to `outputs/`.

## Run the web app

The repository includes an EfficientNet-B0 checkpoint at `outputs/best_efficientnet_b0.pth`, so the app runs without the training data. One server on port 7860 serves the API and the built frontend.

```bash
# 1. Backend dependencies (into the repo venv from "Install")
pip install -r backend/requirements.txt

# 2. Backend settings: set JWT_SECRET (64 hex chars) and DEMO_PASSWORD (8+ chars)
cp backend/.env.example backend/.env
python -c "import secrets; print(secrets.token_hex(32))"   # paste as JWT_SECRET

# 3. Frontend build (Node 20+); set VITE_DEMO_PASSWORD to the same DEMO_PASSWORD to pre-fill sign-in
cp frontend/.env.example frontend/.env
(cd frontend && npm ci && npm run build)

# 4. Start
python src/demo.py            # = cd backend && uvicorn app.main:app --port 7860
```

Open `http://127.0.0.1:7860` and sign in as `demo@example.com` with `DEMO_PASSWORD`. The startup log says `Model loaded on <device>`.

- **Screens:** sign-in, Ledger (today's screenings, triage queue, findings by disease), Screenings (search, status filter, pages), New screening (photo upload with quality checks), the scan and result reveal with Grad-CAM regions, screening detail with reviewer reads, and the model card.
- **Data:** SQLite at `backend/app.db` and photos in `backend/uploads/` (both git-ignored). An empty database is seeded on start-up with eight ODIR **test-split** photos and fictional patient refs. `cd backend && python -m app.seed --reset` restores that state.
- **Fallbacks:** `USE_MOCKS=true` never loads the model. Seeded screenings then use results the real model produced for them (`python -m app.fixtures`), and any other photo gets "Model offline" rather than a made-up result. `AUTH_DISABLED=true` (backend) with `VITE_AUTH_DISABLED=true` (frontend) skips sign-in.
- **Development:** `cd frontend && npm run dev` serves the frontend on port 5173 with the API proxied to 7860. Backend details and tests are in [backend/README.md](backend/README.md).

## Results

Held-out test set (959 eyes from patients not seen in training). Thresholds are sensitivity-first and predictions are averaged over each photo and its mirror, so precision is lower than recall by design. Generated from `outputs/metrics.json` with:

```bash
python -c "import json; t=json.load(open('outputs/metrics.json'))['test']; [print(d, *(round(m[k],3) for k in ('precision','recall','f1','ap','roc_auc')), m['support']) for d,m in t['per_class'].items()]"
```

| Disease | Precision | Recall | F1 | AP | ROC-AUC | Positives |
|---|---|---|---|---|---|---|
| Myopia | 0.988 | 0.853 | 0.915 | 0.987 | 0.998 | 95 |
| Cataract | 0.679 | 0.864 | 0.760 | 0.906 | 0.978 | 44 |
| Glaucoma | 0.744 | 0.931 | 0.827 | 0.938 | 0.967 | 131 |
| Diabetic Retinopathy | 0.650 | 0.747 | 0.695 | 0.829 | 0.876 | 174 |

Everyday ODIR photos only (`test.by_source[<disease>]["ODIR"]`):

| Disease | AP | ROC-AUC |
|---|---|---|
| Myopia | 0.954 | 0.997 |
| Cataract | 0.832 | 0.967 |
| Glaucoma | 0.433 | 0.850 |
| Diabetic Retinopathy | 0.814 | 0.868 |

## Limitations

- Research prototype, not a medical device and not clinically validated; confirm every result with an ophthalmologist.
- Screens only these four diseases; photos showing other conditions may be flagged as one of them.
- "Myopia" means pathological myopia visible on the photo; mild myopia usually looks normal.
- Glaucoma is weak on everyday camp photos (ODIR-only AP 0.43 versus 0.94 overall).
- Performance on other cameras and populations is unknown.

## Acknowledgements

Training used public fundus datasets: [ODIR-5K](https://www.kaggle.com/datasets/andrewmvd/ocular-disease-recognition-odir5k), [PALM](https://palm.grand-challenge.org/), [JSIEC](https://www.kaggle.com/datasets/linchundan/fundusimage1000), [CSDI](https://www.kaggle.com/datasets/jr2ngb/cataractdataset), [ACRIMA](https://figshare.com/s/c2d31f850af14c5b5232), [PAPILA](https://figshare.com/articles/dataset/PAPILA/14798004), [HRF](https://www5.cs.fau.de/research/data/fundus-images/) and [HYGD](https://physionet.org/content/hygd/). Check each dataset's licence before reuse.

## Project structure

```text
.
├── assets/examples/       # Images shown in the demo
├── data/                  # Local datasets (not version-controlled)
├── outputs/               # Model checkpoint and local training outputs
├── backend/               # FastAPI API, SQLite models, seed data, tests
├── frontend/              # React + Vite + TypeScript web app
├── src/                   # Dataset, model, training, evaluation, Grad-CAM and app launcher
├── main.py                # Training and evaluation entry point
├── preprocess_dataset.py  # Label and split generation
└── requirements.txt       # Python dependencies
```

