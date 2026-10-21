"""Shared constants and per-eye label extraction for fundus images."""
import re

# Strictly 4 target diseases:
# 1. Myopia (M)
# 2. Cataract (C)
# 3. Glaucoma (G)
# 4. Diabetic Retinopathy (D)
LABELS = ['M', 'C', 'G', 'D']
DISEASES = ['Myopia', 'Cataract', 'Glaucoma', 'Diabetic Retinopathy']

# Target value for a label that is not known for an image (ignored by loss and metrics)
UNKNOWN = -1

# Diagnostic keyword matching for target diseases
KEYWORD_PATTERNS = {
    'M': r'pathological myopia|myopia retinopathy|myopic maculopathy|myopia|myopic',
    'C': r'cataract',
    'G': r'glaucoma',
    'D': r'(non ?proliferative|proliferative|diabetic) (diabetic )?retinopathy',
}

# Images whose keywords indicate unusable image quality
UNUSABLE = re.compile(r'no fundus image|anterior segment image|low image quality|'
                      r'optic disk photographically invisible|image offset')

# Normal fundus keywords for clean negative controls
NORMAL_PATTERN = re.compile(r'\bnormal fundus\b|^normal$|^healthy$', re.I)


def split_keywords(text):
    return [k.strip() for k in re.split(r'[，,]', str(text)) if k.strip()]


def eye_labels(keywords):
    """Return (labels_dict, ambiguous, other_disease) for one eye's diagnostic keywords.

    - labels_dict: {label: 0/1} for each target disease.
    - ambiguous: True when a target disease is only 'suspected' or uncertain.
    - other_disease: True when the eye has other ocular pathologies (e.g., AMD,
      hypertensive retinopathy, epiretinal membrane, drusen, etc.) and no target disease.
      These images are deleted/excluded from training.
    """
    labels = {label: 0 for label in LABELS}
    ambiguous = False
    has_target = False
    kws = split_keywords(keywords)

    for kw in kws:
        for label, pattern in KEYWORD_PATTERNS.items():
            if re.search(pattern, kw, re.I):
                if re.search(r'suspect|suspicious', kw, re.I):
                    ambiguous = True
                else:
                    labels[label] = 1
                    has_target = True

    if has_target:
        return labels, ambiguous, False

    # Check if this is a clean normal fundus
    is_normal = any(NORMAL_PATTERN.search(kw) for kw in kws)
    has_other_pathology = any(not NORMAL_PATTERN.search(kw) and kw.lower() != 'lens dust' for kw in kws)

    if is_normal and not has_other_pathology:
        return labels, ambiguous, False

    # If it is not a target disease and not a clean normal, it is another disease/pathology
    return labels, ambiguous, True
