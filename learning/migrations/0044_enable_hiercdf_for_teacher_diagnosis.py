from django.db import migrations


def enable_hiercdf(apps, schema_editor):
    DiagnosisModel = apps.get_model('learning', 'DiagnosisModel')
    model, _ = DiagnosisModel.objects.get_or_create(
        name='HierCDF',
        defaults={
            'description': '考虑知识点先修关系的层次认知诊断模型',
            'category': 'nn',
            'is_active': True,
        },
    )
    if not model.is_active:
        model.is_active = True
        model.save(update_fields=['is_active'])


class Migration(migrations.Migration):

    dependencies = [
        ('learning', '0043_alter_knowledgegraph_relationship_type'),
    ]

    operations = [
        migrations.RunPython(enable_hiercdf, migrations.RunPython.noop),
    ]
