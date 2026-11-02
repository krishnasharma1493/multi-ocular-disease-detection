"""RetinaScreen web app: the screening UI in web/ plus a JSON API over the classifier.

    python -m src.demo                # http://127.0.0.1:7860 (classic Gradio UI at /gradio)

Screenings are kept on disk in screenings/ (one JSON record and one cropped
image per screened eye), so the ledger survives restarts.
"""
import hashlib
import io
import json
import os
import re
import threading
import time
from datetime import datetime

import cv2
import numpy as np
import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel

from src.dataset import to_tensor
from src.gradcam import grad_cam, target_layer
from src.labels import DISEASES, LABELS
from src.preprocessing import crop_fundus

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, 'web')
NAMES = dict(zip(LABELS, DISEASES))

MAX_BYTES = 10 * 1024 * 1024
ACCEPTED = {'JPEG': 'JPG', 'PNG': 'PNG'}
MIN_SHARPNESS = 0.30
REVIEW_READS = ('agree', 'disagree', 'unsure')
ID_PATTERN = re.compile(r'^RS-\d{4,}$')


def _mb(n):
    return f'{max(1, round(n / 1024))} KB' if n < 102400 else f'{n / 1024 / 1024:.1f} MB'


def _capture_error(status, code, head, body, data):
    raise HTTPException(status, detail={'code': code, 'head': head, 'body': body, 'data': data})


def image_quality(square):
    """Return (sharpness 0-1, looks_like_fundus) for a crop_fundus square."""
    small = cv2.resize(square, (512, 512), interpolation=cv2.INTER_AREA)
    mask = small.max(axis=2) > 15
    inner = cv2.erode(mask.astype(np.uint8), np.ones((15, 15), np.uint8)) > 0
    if inner.sum() < 1000:
        return 0.0, False
    lap = cv2.Laplacian(cv2.cvtColor(small, cv2.COLOR_RGB2GRAY), cv2.CV_64F)
    sharpness = float(np.clip(np.log10(lap[inner].var() + 1) / 2, 0, 1))
    red, blue = small[..., 0][mask].mean(), small[..., 2][mask].mean()
    return sharpness, bool(mask.mean() > 0.2 and red > blue)


class ScreeningStore:
    """Screening records as JSON files next to their cropped input images."""

    def __init__(self, folder):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)
        self.lock = threading.Lock()

    def _path(self, sid, ext):
        return os.path.join(self.folder, f'{sid}.{ext}')

    def all(self):
        records = []
        for name in os.listdir(self.folder):
            if name.endswith('.json'):
                with open(os.path.join(self.folder, name)) as f:
                    records.append(json.load(f))
        return sorted(records, key=lambda r: r['created'])

    def get(self, sid):
        if not ID_PATTERN.match(sid) or not os.path.exists(self._path(sid, 'json')):
            return None
        with open(self._path(sid, 'json')) as f:
            return json.load(f)

    def image_path(self, sid):
        path = self._path(sid, 'jpg')
        return path if ID_PATTERN.match(sid) and os.path.exists(path) else None

    def add(self, record, square):
        with self.lock:
            numbers = [int(n[3:-5]) for n in os.listdir(self.folder) if re.match(r'^RS-\d+\.json$', n)]
            record['id'] = f'RS-{max(numbers, default=0) + 1:04d}'
            Image.fromarray(square).save(self._path(record['id'], 'jpg'), quality=92)
            self._write(record)
        return record

    def update(self, record):
        with self.lock:
            self._write(record)

    def _write(self, record):
        tmp = self._path(record['id'], 'json.tmp')
        with open(tmp, 'w') as f:
            json.dump(record, f, indent=1)
        os.replace(tmp, self._path(record['id'], 'json'))


def model_card(checkpoint, checkpoint_path):
    """Checkpoint facts plus held-out test metrics from outputs/metrics.json when present."""
    stat = os.stat(checkpoint_path)
    with open(checkpoint_path, 'rb') as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    card = {
        'model_name': checkpoint['model_name'],
        'img_size': checkpoint['img_size'],
        'diseases': [NAMES.get(label, label) for label in checkpoint['labels']],
        'thresholds': [float(t) for t in checkpoint['thresholds']],
        'checkpoint': {'file': os.path.basename(checkpoint_path), 'sha256': digest,
                       'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(timespec='seconds')},
        'metrics': None,
    }
    metrics_path = os.path.join(os.path.dirname(checkpoint_path), 'metrics.json')
    if os.path.exists(metrics_path):
        with open(metrics_path) as f:
            metrics = json.load(f)
        test = metrics.get('test') or {}
        per_class = {name: {k: test['per_class'][name].get(k) for k in ('roc_auc', 'ap', 'precision', 'recall', 'threshold')}
                     for name in card['diseases'] if name in test.get('per_class', {})}
        sources = []
        for name, info in (metrics.get('dataset', {}).get('sources') or {}).items():
            positives = {d: n for d, n in (info.get('positives') or {}).items() if n}
            sources.append({'name': name, 'images': info.get('images'), 'diseases': sorted(positives, key=positives.get, reverse=True)})
        card['metrics'] = {'test_images': test.get('num_images'), 'per_class': per_class, 'sources': sources}
    return card


def create_app(model, checkpoint, device, checkpoint_path, store_dir=None, gradio_blocks=None):
    store = ScreeningStore(store_dir or os.path.join(ROOT, 'screenings'))
    names = [NAMES.get(label, label) for label in checkpoint['labels']]
    thresholds = [float(t) for t in checkpoint['thresholds']]
    layer_name, layer = target_layer(model, checkpoint['model_name'])
    infer_lock = threading.Lock()
    card = model_card(checkpoint, checkpoint_path)
    app = FastAPI(title='RetinaScreen', docs_url=None, redoc_url=None)

    def screen(image):
        x = to_tensor(image, checkpoint['img_size']).to(device)
        with infer_lock:
            start = time.perf_counter()
            with torch.no_grad():
                probs = torch.sigmoid(model(x))[0].cpu().tolist()
            ms = (time.perf_counter() - start) * 1000
            results, maps = [], []
            for i, (name, prob, thr) in enumerate(zip(names, probs, thresholds)):
                positive = prob >= thr
                results.append({'disease': name, 'probability': prob, 'threshold': thr, 'positive': positive})
                if positive:
                    cam = grad_cam(model, x, layer, i)
                    maps.append({'disease': name, 'method': 'Grad-CAM', 'layer': layer_name,
                                 'available': cam is not None,
                                 'grid': None if cam is None else np.round(cam, 4).tolist()})
        return results, maps, ms

    @app.get('/api/health')
    def health():
        return {'ok': True, 'time': datetime.now().isoformat(timespec='seconds')}

    @app.get('/api/model')
    def get_model_card():
        return card

    @app.get('/api/screenings')
    def list_screenings(date: str = None):
        day = date or datetime.now().date().isoformat()
        return {'date': day, 'screenings': [r for r in store.all() if r['created'].startswith(day)]}

    @app.post('/api/screenings', status_code=201)
    def create_screening(image: UploadFile = File(...), ref: str = Form(...), eye: str = Form(...),
                         notes: str = Form('')):
        ref, eye, notes = ref.strip().upper(), eye.strip().upper(), notes.strip()[:2000]
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9-]{0,19}', ref):
            raise HTTPException(422, detail={'code': 'ref', 'head': 'Patient ref is missing or invalid.',
                                             'body': 'Use the format P-0000, from the camp register.', 'data': ref})
        if eye not in ('L', 'R'):
            raise HTTPException(422, detail={'code': 'eye', 'head': 'Choose one eye.', 'body': 'Pick L or R.', 'data': eye})
        data = image.file.read(MAX_BYTES + 1)
        fname = image.filename or 'upload'
        if len(data) > MAX_BYTES:
            size = image.size or len(data)
            _capture_error(413, 'ERR · FILE TOO LARGE', f'This photo is {_mb(size)}. The limit is 10 MB.',
                           'Save it at a lower resolution on the camera, or use the compressed copy, then try again.',
                           f'{fname} · {_mb(size)}')
        try:
            pil = Image.open(io.BytesIO(data))
            kind = pil.format
            pil = pil.convert('RGB')
        except (UnidentifiedImageError, OSError):
            kind = None
        if kind not in ACCEPTED:
            ext = os.path.splitext(fname)[1].lstrip('.').upper() or 'an unknown type'
            _capture_error(415, 'ERR · FILE TYPE', f'This file is {ext}, not JPG or PNG.',
                           'Export the photo from the camera as JPG or PNG, then place it in the lens again.',
                           f'{fname} · {_mb(len(data))}')
        square = crop_fundus(pil)
        sharpness, fundus = image_quality(square)
        if sharpness < MIN_SHARPNESS or not fundus:
            _capture_error(422, 'ERR · IMAGE QUALITY', 'Too blurred to screen, or not a fundus photo.',
                           'Refocus on the optic disc and retake. Check the lens cap and that the camera is in fundus mode.',
                           f'SHARPNESS {sharpness:.2f} · MINIMUM {MIN_SHARPNESS:.2f}' if fundus
                           else 'NO FUNDUS FOUND IN THE PHOTO')
        results, maps, ms = screen(pil)
        record = {
            'ref': ref, 'eye': eye, 'notes': notes,
            'created': datetime.now().isoformat(timespec='seconds'),
            'image': {'name': fname, 'width': pil.width, 'height': pil.height, 'type': ACCEPTED[kind], 'bytes': len(data)},
            'quality': {'sharpness': round(sharpness, 2), 'minimum': MIN_SHARPNESS, 'pass': True},
            'model': {'name': checkpoint['model_name'], 'img_size': checkpoint['img_size'], 'ms': round(ms)},
            'results': results, 'maps': maps, 'review': None,
        }
        return store.add(record, square)

    @app.get('/api/screenings/{sid}')
    def get_screening(sid: str):
        record = store.get(sid)
        if record is None:
            raise HTTPException(404, detail=f'{sid} is not in the ledger')
        return record

    @app.get('/api/screenings/{sid}/image')
    def get_image(sid: str):
        path = store.image_path(sid)
        if path is None:
            raise HTTPException(404, detail=f'{sid} has no image')
        return FileResponse(path, media_type='image/jpeg')

    class Review(BaseModel):
        read: str

    @app.put('/api/screenings/{sid}/review')
    def set_review(sid: str, review: Review):
        record = store.get(sid)
        if record is None:
            raise HTTPException(404, detail=f'{sid} is not in the ledger')
        if review.read not in REVIEW_READS:
            raise HTTPException(422, detail=f'read must be one of {", ".join(REVIEW_READS)}')
        record['review'] = {'read': review.read, 'at': datetime.now().isoformat(timespec='seconds')}
        store.update(record)
        return record

    @app.get('/api/{rest:path}')
    def api_not_found(rest: str):
        return JSONResponse({'detail': 'Not found'}, status_code=404)

    if gradio_blocks is not None:
        import gradio as gr
        app = gr.mount_gradio_app(app, gradio_blocks, path='/gradio')

    app.mount('/static', StaticFiles(directory=WEB_DIR), name='static')

    @app.get('/')
    def index():
        return FileResponse(os.path.join(WEB_DIR, 'index.html'), headers={'Cache-Control': 'no-cache'})

    return app
