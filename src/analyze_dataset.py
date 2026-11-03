import os

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from .labels import DISEASES, LABELS


def analyze_dataset(labels_csv='data/labels.csv', out_dir='outputs'):
    data = pd.read_csv(labels_csv)
    os.makedirs(out_dir, exist_ok=True)
    names = dict(zip(LABELS, DISEASES))

    # 1. Disease distribution per split
    counts = data.groupby('split')[LABELS].sum().T.rename(index=names)[['train', 'val', 'test']]
    ax = counts.plot(kind='bar', figsize=(12, 6))
    ax.set(title=f'Eye images per disease ({len(data)} images)', xlabel='', ylabel='Images')
    plt.xticks(rotation=20)
    plt.tight_layout()
    plt.savefig(f'{out_dir}/disease_distribution.png')
    plt.close()

    # 2. Co-occurrence: how many images carry both diseases (diagonal = total per disease)
    # Unknown labels (from external datasets) count as absent here
    known = data[LABELS].fillna(0).astype(int)
    co_occurrence = (known.T @ known).rename(index=names, columns=names)
    plt.figure(figsize=(9, 7))
    sns.heatmap(co_occurrence, annot=True, fmt='d', cmap='Blues')
    plt.title('Disease co-occurrence (images with both labels)')
    plt.tight_layout()
    plt.savefig(f'{out_dir}/co_occurrence_matrix.png')
    plt.close()

    # 3. Number of diseases per image
    odir = data[data['source'] == 'ODIR']
    per_image = odir[LABELS].sum(axis=1).astype(int).value_counts().sort_index()
    ax = per_image.plot(kind='bar', figsize=(10, 5))
    ax.set(title='Number of target diseases per ODIR eye image', xlabel='Diseases', ylabel='Images')
    plt.tight_layout()
    plt.savefig(f'{out_dir}/disease_combinations.png')
    plt.close()

    return counts


if __name__ == '__main__':
    print(analyze_dataset())
