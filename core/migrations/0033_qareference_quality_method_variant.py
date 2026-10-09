from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0032_qa_fulltext_extraction_chunks'),
    ]

    operations = [
        migrations.AddField(
            model_name='qareference',
            name='quality_method_variant',
            field=models.CharField(
                blank=True,
                default='',
                max_length=30,
                verbose_name='质量评价方法研究设计',
            ),
        ),
    ]
