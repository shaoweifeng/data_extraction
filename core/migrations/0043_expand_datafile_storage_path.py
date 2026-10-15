import core.models
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0042_publish_verified_model_billing_rates')]

    operations = [
        migrations.AlterField(
            model_name='datafile',
            name='file',
            field=models.FileField(
                max_length=500,
                upload_to=core.models.data_file_upload_path,
                verbose_name='文件',
            ),
        ),
    ]
