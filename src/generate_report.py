"""Build outputs/eye_disease_report.pdf from outputs/metrics.json (written by main.py)."""
import json
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _metrics_table(metrics):
    rows = [['Disease', 'Precision', 'Recall', 'F1', 'AP', 'ROC-AUC', 'Positives', 'Threshold']]
    for disease, m in metrics['per_class'].items():
        rows.append([disease, *(f'{m[k]:.3f}' for k in ('precision', 'recall', 'f1', 'ap', 'roc_auc')),
                     m['support'], f'{m["threshold"]:.2f}'])
    macro = metrics['macro']
    rows.append(['Macro average', *(f'{macro[k]:.3f}' for k in ('precision', 'recall', 'f1', 'mAP', 'roc_auc')),
                 '', ''])
    table = Table(rows)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f4e79')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
    ]))
    return table


def generate_pdf_report(results, out_path='outputs/eye_disease_report.pdf', out_dir='outputs'):
    styles = getSampleStyleSheet()
    config, data, test = results['config'], results['dataset'], results['test']
    story = [
        Paragraph('Multi-Ocular Disease Detection from Fundus Images', styles['Title']),
        Paragraph('1. Setup', styles['Heading2']),
        Paragraph(
            f'Model: {config["model_name"]} (ImageNet-pretrained, fine-tuned), input {config["img_size"]}px, '
            f'AdamW lr {config["lr"]}, batch {config["batch_size"]}, trained {config["epochs_trained"]} epochs '
            f'(best validation mAP kept). Loss: BCEWithLogits with pos_weight = sqrt(negatives / positives) '
            f'from the training split. Decision thresholds tuned per disease on the validation split.',
            styles['BodyText']),
        Paragraph('2. Data', styles['Heading2']),
        Paragraph(
            f'{data["sources"]["ODIR"]["images"]} ODIR-5K eye images, labelled per eye from the diagnostic '
            f'keywords, plus {data["images"] - data["sources"]["ODIR"]["images"]} images from external '
            f'datasets. Split by patient: '
            f'{data["train"]} train / {data["val"]} validation / {data["test"]} test images, so no patient '
            f'appears in more than one split.',
            styles['BodyText']),
    ]
    external = {k: v for k, v in data['sources'].items() if k != 'ODIR'}
    if external:
        listing = ', '.join(
            f'{k} ({v["images"]} images; ' + ', '.join(f'{n} {d.lower()}' for d, n in v['positives'].items()) + ')'
            for k, v in external.items())
        story.append(Paragraph(
            f'Extra data: {listing}. Each of these datasets only labels the diseases listed, so its images '
            f'train and score those outputs only; each is split 80/10/10 on its own. Diseases labelled by '
            f'more than one dataset are also reported per dataset below, since pooled scores can be '
            f'inflated when datasets differ in prevalence.',
            styles['BodyText']))
    for name in ('disease_distribution.png', 'co_occurrence_matrix.png'):
        if os.path.exists(f'{out_dir}/{name}'):
            story += [Image(f'{out_dir}/{name}', width=5.5 * inch, height=3 * inch), Spacer(1, 8)]

    story += [
        Paragraph(f'3. Test set results ({test["num_images"]} held-out images)', styles['Heading2']),
        _metrics_table(test),
        Spacer(1, 6),
        Paragraph(f'Micro average: precision {test["micro"]["precision"]:.3f}, recall '
                  f'{test["micro"]["recall"]:.3f}, F1 {test["micro"]["f1"]:.3f}.', styles['BodyText']),
    ]
    by_source = test.get('by_source', {})
    if by_source:
        rows = [['Test set', 'Images', 'Positives', 'Precision', 'Recall', 'F1', 'AP', 'ROC-AUC']]
        rows += [[f'{disease} @ {source}', m['num_images'], m['support'],
                  *(f'{m[k]:.3f}' for k in ('precision', 'recall', 'f1', 'ap', 'roc_auc'))]
                 for disease, sources in by_source.items() for source, m in sources.items()]
        table = Table(rows)
        table.setStyle(TableStyle([('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                                   ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                                   ('FONTSIZE', (0, 0), (-1, -1), 9)]))
        story += [Spacer(1, 8), table]
    for name, height in ((f'{config["model_name"]}_training_history.png', 2.5),
                         ('confusion_matrix.png', 1.6)):
        if os.path.exists(f'{out_dir}/{name}'):
            story += [Spacer(1, 8), Image(f'{out_dir}/{name}', width=6.5 * inch, height=height * inch)]

    story += [
        Paragraph('4. Limitations', styles['Heading2']),
        Paragraph('Research prototype, not a medical device. Scores for classes or datasets with few test '
                  'positives have wide uncertainty. "Myopia" means myopic changes visible on the fundus '
                  '(pathological / high myopia); ordinary low myopia usually looks normal on a fundus photo '
                  'and cannot be detected this way. AMD, hypertensive retinopathy and other findings are not '
                  'predicted. The model has only seen the training datasets listed above and may be less '
                  'reliable on other cameras or populations.',
                  styles['BodyText']),
    ]
    SimpleDocTemplate(out_path, pagesize=letter).build(story)
    print(f'Report written to {out_path}')


if __name__ == '__main__':
    with open('outputs/metrics.json') as f:
        generate_pdf_report(json.load(f))
