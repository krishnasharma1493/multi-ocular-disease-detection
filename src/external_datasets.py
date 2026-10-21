"""Import external fundus datasets as extra training data for the diseases they label:
glaucoma (REFUGE, ORIGA, G1020, ACRIMA, LAG, PAPILA, ...), cataract (CSDI, ...),
myopia (PALM, JSIEC, ...) and diabetic retinopathy (JSIEC, ...).

Put each dataset in its own folder under data/external/, e.g. data/external/PALM/
(folders starting with '_' or '.' are ignored).
A dataset only knows the labels it provides; the others are left empty (unknown)
and ignored by the loss and the metrics.

Each image's labels are taken from the first rule that applies:
  1. external_labels.csv in the dataset folder, columns `filename` plus any of
     D,G,C,M (0/1, blank = unknown); glaucoma_labels.csv (`filename,G`) also works
  2. the dataset's own label sheet: G1020.csv, OrigaList.csv (glaucoma),
     CSDI_annotations.csv (cataract score), PALM's classification sheets (myopia)
  3. a parent folder name: 'glaucoma', 'cataract', 'pathological myopia',
     'DR1'..'DR3' / 'diabetic retinopathy' -> that disease; 'normal' / 'healthy' / 'negative' -> no disease
  4. a file-name convention: REFUGE g0001.jpg / n0001.jpg, ACRIMA Im001_g_ACRIMA.jpg,
     PALM P0001.jpg (pathological myopia) / H0001.jpg, N0001.jpg (not)
Images matching none of these are skipped and counted in the summary. Within a
dataset, an image labelled by rules 3-4 is negative for every other disease that
dataset provides (these are single-label classification datasets).
"""
import os
import re

import numpy as np
import pandas as pd
from PIL import Image
from sklearn.model_selection import StratifiedGroupKFold

from .labels import LABELS
from .preprocessing import crop_fundus

EXTERNAL_DIR = 'data/external'
PREPROCESSED_DIR = 'data/external_preprocessed'
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.tif', '.tiff', '.bmp')

# Segmentation masks, annotations and LAG's attention maps ship alongside the photos in several datasets
SKIP_DIRS = re.compile(r'mask|ground.?truth|\bgt\b|annotation|segmentation|optic.?(disc|cup)|attention|heatmap|'
                       r'illustration|resized|predicts|__macosx', re.I)
# Folders whose diagnosis is uncertain (JSIEC 'Possible glaucoma', 'suspected PDR')
AMBIGUOUS_DIR = re.compile(r'possible|suspected', re.I)
# 'normal' / 'healthy' as whole words ('1_normal' yes, JSIEC 'Congenital disc abnormality' no)
NEGATIVE_DIR = re.compile(r'non.?glaucoma|non.?cataract|(?<![a-z])(normal|healthy)(?![a-z])|negative|^nrg$|^0$', re.I)
POSITIVE_DIRS = {
    # DR grade folders (JSIEC 'DR1'..'DR3') but not 'PDR' inside other folder names
    'D': re.compile(r'(?<![a-z])dr\d|diabetic.?retinopathy', re.I),
    'G': re.compile(r'glaucoma|positive|^rg$|^1$', re.I),
    'C': re.compile(r'cataract', re.I),
    'M': re.compile(r'patholog\w*.?myopia', re.I),
}
# CSDI scores cataract 0-10: [0, 1) no cataract, [1, 3) 'acceptable' (skipped as borderline), >= 3 cataract
CSDI_NEGATIVE, CSDI_POSITIVE = 1.0, 3.0


def _read_sheet(path):
    return pd.read_excel(path) if path.endswith(('.xlsx', '.xls')) else pd.read_csv(path)


def _sheet_rows(name, sheet):
    """(file name, {label: 0/1}) pairs from a label sheet this module knows, else None."""
    columns = {c.lower().strip(): c for c in sheet.columns}
    if name == 'external_labels.csv':
        known = [l for l in LABELS if l in sheet.columns]
        return ((f, {l: int(r[l]) for l in known if pd.notna(r[l])})
                for f, (_, r) in zip(sheet['filename'], sheet.iterrows()))
    if name == 'glaucoma_labels.csv':
        return ((f, {'G': int(g)}) for f, g in zip(sheet['filename'], sheet['G']))
    if name == 'G1020.csv':
        return ((f, {'G': int(g)}) for f, g in zip(sheet['imageID'], sheet['binaryLabels']))
    if name == 'OrigaList.csv':
        return ((f, {'G': int(g)}) for f, g in zip(sheet['Filename'], sheet['Glaucoma']))
    if name == 'CSDI_annotations.csv':
        return ((f, {'C': int(s >= CSDI_POSITIVE)}) for f, s in zip(sheet['id'], sheet['score'])
                if s < CSDI_NEGATIVE or s >= CSDI_POSITIVE)
    # PALM validation/test classification sheets: image name + 0/1 pathological myopia label
    if 'imgname' in columns and 'label' in columns:
        return ((f, {'M': int(m)}) for f, m in zip(sheet[columns['imgname']], sheet[columns['label']]))
    return None


def _sheet_labels(dataset_dir):
    """{file name: {label: 0/1}} from every recognised label sheet in the dataset folder."""
    labels = {}
    for root, dirs, files in os.walk(dataset_dir):
        dirs[:] = [d for d in dirs if d.lower() != '__macosx']
        for name in files:
            if not name.lower().endswith(('.csv', '.xlsx', '.xls')) or name.startswith('.'):
                continue
            try:
                rows = _sheet_rows(name, _read_sheet(os.path.join(root, name)))
            except (KeyError, ValueError):
                rows = None
            for filename, label in rows or ():
                labels[os.path.basename(str(filename))] = label
    return labels


def _path_label(dataset, relative_path):
    """{label: 0/1} from folder names or file-name conventions, None if unknown, 'ambiguous' to skip.
    A negative folder returns {} (negative for whatever the dataset provides)."""
    *folders, filename = relative_path.split(os.sep)
    for folder in reversed(folders):
        if AMBIGUOUS_DIR.search(folder):
            return 'ambiguous'
        if NEGATIVE_DIR.search(folder):
            return {}
        for label, pattern in POSITIVE_DIRS.items():
            if pattern.search(folder):
                return {label: 1}
    stem = os.path.splitext(filename)[0]
    if 'refuge' in dataset.lower() and re.fullmatch(r'[gn]\d+', stem, re.I):
        return {'G': int(stem[0].lower() == 'g')}
    if 'acrima' in dataset.lower():
        return {'G': int('_g_' in stem.lower())}
    if 'palm' in dataset.lower() and re.fullmatch(r'[hnp]\d+', stem, re.I):
        return {'M': int(stem[0].lower() == 'p')}
    return None


def scan_external(external_dir=EXTERNAL_DIR):
    """Return (DataFrame of source/original_path/<labels>, {dataset: skipped count})."""
    rows, skipped = [], {}
    if not os.path.isdir(external_dir):
        return pd.DataFrame(columns=['source', 'original_path', *LABELS]), skipped
    for dataset in sorted(os.listdir(external_dir)):
        dataset_dir = os.path.join(external_dir, dataset)
        # _downloads/ etc. hold archives still to be unpacked, not a dataset
        if not os.path.isdir(dataset_dir) or dataset.startswith(('_', '.')):
            continue
        sheet = _sheet_labels(dataset_dir)
        dataset_rows, skipped[dataset] = [], 0
        for root, dirs, files in os.walk(dataset_dir):
            dirs[:] = sorted(d for d in dirs if not SKIP_DIRS.search(d))
            for name in sorted(files):
                if not name.lower().endswith(IMAGE_EXTENSIONS) or name.startswith('.'):
                    continue
                path = os.path.join(root, name)
                label = sheet.get(name)
                if label is None:
                    label = _path_label(dataset, os.path.relpath(path, dataset_dir))
                if label is None or label == 'ambiguous':
                    skipped[dataset] += 1
                    continue
                dataset_rows.append({'source': dataset, 'original_path': path, **label})
        # Negatives from 'normal' folders (and positives for one disease) are negative
        # for the other diseases this dataset labels
        provided = [l for l in LABELS if any(l in r for r in dataset_rows)]
        rows += [{**{l: 0 for l in provided}, **r} for r in dataset_rows]
    data = pd.DataFrame(rows, columns=['source', 'original_path', *LABELS])
    return data, skipped


def preprocess_image(src, dst, size=512):
    """Crop the black border and resize to the same 512px square as the ODIR images."""
    if not os.path.exists(dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        image = Image.fromarray(crop_fundus(Image.open(src))).resize((size, size), Image.LANCZOS)
        image.save(dst, quality=95)
    return dst


def _patient_key(relative_path):
    """Group all photos of one patient: RET004OD / RET004OS (PAPILA), MAQ-OD / MAQ-OS and
    initials plus eye number LXW1 / LXW2 (CSDI), patient_photo 12_3 (HYGD).
    Other images are their own group."""
    folder, filename = os.path.split(relative_path)
    stem = os.path.splitext(filename)[0]
    stem = re.sub(r'[-_ ]?o[ds]$', '', stem, flags=re.I)
    stem = re.sub(r'^([A-Z]{2,4})\d$', r'\1', stem)
    stem = re.sub(r'^(\d+)_\d+$', r'\1', stem)
    return os.path.join(folder, stem)


def _thumbnail(path, size=64):
    return np.asarray(Image.open(path).convert('L').resize((size, size), Image.BILINEAR), dtype=np.float32)


def _merge_duplicates(paths, groups, max_diff=3.0):
    """Put near-identical images (same photo stored twice under different names) in one group.
    Candidates come from a difference hash and are confirmed on pixels, since hazy cataract
    photos can share a hash without being the same image."""
    thumbs = np.stack([_thumbnail(p) for p in paths])
    small = thumbs.reshape(len(paths), 16, 4, 16, 4).mean(axis=(2, 4))
    hashes = (small[:, :, 1:] > small[:, :, :-1]).reshape(len(paths), -1)
    parent = list(range(len(paths)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    merged = 0
    for i in range(len(paths)):
        close = np.nonzero((hashes[i + 1:] != hashes[i]).sum(axis=1) <= 8)[0] + i + 1
        for j in close:
            if np.abs(thumbs[i] - thumbs[j]).mean() < max_diff and root(i) != root(j):
                parent[root(j)] = root(i)
                merged += 1
    # Group by the root's own patient group so eye-pair grouping is kept too
    key_parent = {}
    for i, g in enumerate(groups):
        key_parent.setdefault(g, root(i))
    for i, g in enumerate(groups):
        a, b = root(i), root(key_parent[g])
        if a != b:
            parent[a] = b
    return [groups[root(i)] for i in range(len(paths))], merged


def build_external_labels(external_dir=EXTERNAL_DIR, out_dir=PREPROCESSED_DIR, seed=42):
    """Rows for labels.csv: preprocessed external images with their known labels (others unknown),
    split 80/10/10 within each dataset and stratified by label."""
    data, skipped = scan_external(external_dir)
    if data.empty:
        return None
    print(f'External images: {len(data)} (unlabelled or ambiguous, skipped: {skipped})')

    data['path'] = [
        preprocess_image(src, os.path.join(out_dir, source, os.path.splitext(
            os.path.relpath(src, os.path.join(external_dir, source)))[0] + '.jpg'))
        for source, src in zip(data['source'], data['original_path'])]
    data['filename'] = data['path'].map(os.path.basename)
    # Dataset-prefixed so ids never collide with ODIR's integer patient ids. Both eyes of a
    # patient, and copies of the same photo, share an id so they always land in the same split.
    data['patient_id'] = data['source'] + ':' + data['path'].str.slice(len(out_dir) + 1).map(_patient_key)
    for source, subset in data.groupby('source'):
        ids, merged = _merge_duplicates(subset['path'].tolist(), subset['patient_id'].tolist())
        data.loc[subset.index, 'patient_id'] = ids
        if merged:
            print(f'{source}: {merged} near-duplicate images grouped with their copies')

    # Each dataset is split on its own, so adding a dataset never moves another's images between splits
    positive = data[LABELS].fillna(0).astype(bool)
    strat = positive.apply(lambda r: ''.join(l for l in LABELS if r[l]) or 'none', axis=1)
    folds = StratifiedGroupKFold(n_splits=10, shuffle=True, random_state=seed)
    data['split'] = 'train'
    for _, subset in data.groupby('source'):
        for fold, (_, idx) in enumerate(folds.split(subset, strat[subset.index], groups=subset['patient_id'])):
            if fold == 0:
                data.loc[subset.index[idx], 'split'] = 'test'
            elif fold == 1:
                data.loc[subset.index[idx], 'split'] = 'val'

    # Per dataset: images in each split, and positives / labelled images for each disease it provides
    summary = data.groupby('source')['split'].value_counts().unstack(fill_value=0)
    for label in LABELS:
        known = data[label].notna()
        if known.any():
            counts = data[known].groupby('source')[label].agg(['sum', 'size'])
            summary[label] = (counts['sum'].astype(int).astype(str) + '/' + counts['size'].astype(str))
    print(summary.fillna('').to_string())
    return data.drop(columns='original_path')
