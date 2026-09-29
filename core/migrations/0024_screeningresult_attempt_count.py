from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0023_screening_database_storage'),
    ]

    operations = [
        migrations.AddField(
            model_name='screeningresult',
            name='attempt_count',
            field=models.PositiveSmallIntegerField(default=0, verbose_name='尝试次数'),
        ),
    ]
