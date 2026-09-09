from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('learning', '0042_subjectcomment'),
    ]

    operations = [
        migrations.AlterField(
            model_name='knowledgegraph',
            name='relationship_type',
            field=models.CharField(
                choices=[('先修', '先修'), ('层级', '层级'), ('相似', '相似')],
                default='相似',
                max_length=10,
                verbose_name='关系类型',
            ),
        ),
    ]
