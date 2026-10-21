import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns


def plot_history(history, save_path):
    epochs = range(1, len(history['train_loss']) + 1)
    fig, (ax_loss, ax_map) = plt.subplots(1, 2, figsize=(12, 4.5))
    ax_loss.plot(epochs, history['train_loss'], label='Training loss')
    ax_loss.plot(epochs, history['val_loss'], label='Validation loss')
    ax_loss.set(xlabel='Epoch', ylabel='Weighted BCE loss', title='Loss')
    ax_loss.legend()
    ax_map.plot(epochs, history['val_map'], color='tab:green')
    ax_map.set(xlabel='Epoch', ylabel='mAP', title='Validation mean average precision')
    fig.tight_layout()
    fig.savefig(save_path, dpi=120)
    plt.close(fig)


def plot_confusion_matrices(metrics, save_path):
    per_class = metrics['per_class']
    fig, axes = plt.subplots(1, len(per_class), figsize=(4 * len(per_class), 4))
    for ax, (disease, m) in zip(axes, per_class.items()):
        sns.heatmap(np.array(m['confusion_matrix']), annot=True, fmt='d', cmap='Blues', cbar=False,
                    xticklabels=['Neg', 'Pos'], yticklabels=['Neg', 'Pos'], ax=ax)
        ax.set(title=disease, xlabel='Predicted', ylabel='True')
    fig.suptitle(f'Test set confusion matrices ({metrics["num_images"]} images)')
    fig.tight_layout()
    fig.savefig(save_path, dpi=120)
    plt.close(fig)
