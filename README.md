# Multi-Ocular Disease Detection

<p>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white">
  <img alt="PyTorch" src="https://img.shields.io/badge/PyTorch-2.0%2B-EE4C2C?logo=pytorch&logoColor=white">
  <img alt="Gradio" src="https://img.shields.io/badge/Gradio-interface-F97316?logo=gradio&logoColor=white">
</p>

This repository contains a research prototype that screens retinal fundus photographs for pathological myopia, cataract, glaucoma, and diabetic retinopathy.

## Problem

Retinal images can show more than one disease, while public datasets often label only the conditions they were collected to study. A useful screening prototype needs to predict several conditions independently and avoid treating an unlabelled condition as a confirmed negative.

## Approach

The project fine-tunes an ImageNet-pretrained EfficientNet-B0 model for four-label prediction. Its training pipeline combines ODIR-5K with optional external fundus datasets, uses a masked loss for unknown labels, and creates patient-level train, validation, and test splits. Decision thresholds are selected on the validation split. A Gradio app runs inference on an uploaded image.

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

## Run the demo

The repository includes an EfficientNet-B0 checkpoint at `outputs/best_efficientnet_b0.pth`, so the demo can be run without downloading training data:

```bash
python src/demo.py
```

Open `http://127.0.0.1:7860` and upload a fundus image. Options include `--checkpoint PATH`, `--port N`, and `--share`; sharing creates a public Gradio link.

## Project structure

```text
.
├── assets/examples/       # Images shown in the demo
├── data/                  # Local datasets (not version-controlled)
├── outputs/               # Model checkpoint and local training outputs
├── src/                   # Dataset, model, training, evaluation, and demo code
├── main.py                # Training and evaluation entry point
├── preprocess_dataset.py  # Label and split generation
└── requirements.txt       # Python dependencies
```

