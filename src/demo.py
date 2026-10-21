"""Gradio app: upload a fundus photo and screen for:
1. Myopia
2. Cataract
3. Glaucoma
4. Diabetic Retinopathy

    .venv/bin/python src/demo.py                       # http://127.0.0.1:7860
    .venv/bin/python src/demo.py --checkpoint outputs/best_efficientnet_b0.pth --share
"""
import argparse
import os
import sys

import gradio as gr
import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT)
from src.dataset import to_tensor
from src.labels import DISEASES, LABELS
from src.model import get_device, load_checkpoint

NAMES = dict(zip(LABELS, DISEASES))


def _resolve(path):
    return path if os.path.isabs(path) else os.path.join(ROOT, path)


def load_model(checkpoint_path, device='cpu'):
    """Return (model, checkpoint info) for the 4-disease classifier."""
    path = _resolve(checkpoint_path)
    if not os.path.exists(path):
        sys.exit(f'No checkpoint at {path}. Train one with `python main.py`.')
    raw = torch.load(path, map_location='cpu', weights_only=False)
    if 'state_dict' not in raw:
        sys.exit(f'{path} is a legacy checkpoint with non-target classes. '
                 'Train a new model with `python main.py` to target the 4 diseases.')
    return load_checkpoint(path, device)


@torch.no_grad()
def predict(image, model, checkpoint, device='cpu'):
    """Return ({disease: probability}, {disease: details}) for one image."""
    if image is None:
        raise gr.Error('Upload a fundus image first.')
    probs = torch.sigmoid(model(to_tensor(image, checkpoint['img_size']).to(device)))[0].cpu()

    probabilities, results = {}, {}
    for label, prob, threshold in zip(checkpoint['labels'], probs.tolist(), checkpoint['thresholds']):
        disease = NAMES.get(label, label)
        probabilities[disease] = prob
        results[disease] = {
            'Prediction': 'Positive' if prob >= threshold else 'Negative',
            'Confidence': f'{prob:.2%}',
            'Threshold': f'{threshold:.2%}',
        }
    return probabilities, results


def summarize(results):
    found = [disease for disease, r in results.items() if r['Prediction'] == 'Positive']
    screened = f'Screened for: {", ".join(results)}. Other conditions are not checked.'
    if not found:
        return f'**None of the screened diseases detected.**\n\n{screened}'
    return '**Possible findings:** ' + ', '.join(found) + f'\n\n{screened}'


def build_interface(model, checkpoint, device):
    diseases = ', '.join(NAMES.get(label, label) for label in checkpoint['labels'])
    examples_dir = os.path.join(ROOT, 'assets', 'examples')
    examples = sorted(os.path.join(examples_dir, f) for f in os.listdir(examples_dir)
                       if f.lower().endswith(('.jpg', '.jpeg', '.png'))) if os.path.isdir(examples_dir) else None

    def run(image):
        probabilities, results = predict(image, model, checkpoint, device)
        return summarize(results), probabilities, results

    description = (f'Upload a colour fundus (retina) photograph to screen for: {diseases}. '
                   'A disease is marked Positive when its probability passes the threshold tuned on '
                   'validation data.')
    return gr.Interface(
        fn=run,
        inputs=gr.Image(type='pil', label='Upload Fundus Image'),
        outputs=[gr.Markdown(label='Summary'),
                 gr.Label(label='Probability per disease', num_top_classes=len(checkpoint['labels'])),
                 gr.JSON(label='Prediction Results')],
        title='Eye Disease Detection System',
        description=description,
        article='Research prototype, not a medical device. Do not use for diagnosis.',
        examples=[[e] for e in examples] if examples else None,
        flagging_mode='never',
    )


def launch_demo(checkpoint_path='outputs/best_efficientnet_b0.pth', share=False, port=7860):
    """Launch the Gradio demo interface"""
    device = get_device()
    model, checkpoint = load_model(checkpoint_path, device)
    build_interface(model, checkpoint, device).launch(share=share, server_port=port)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--checkpoint', default='outputs/best_efficientnet_b0.pth')
    parser.add_argument('--share', action='store_true', help='Create a public gradio.live link')
    parser.add_argument('--port', type=int, default=7860)
    args = parser.parse_args()
    launch_demo(args.checkpoint, share=args.share, port=args.port)
