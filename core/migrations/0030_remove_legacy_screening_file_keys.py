from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0029_move_screening_reference_raw_metadata'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='manualreview',
            name='source_xml',
        ),
        migrations.RemoveField(
            model_name='qareference',
            name='source_ref_id',
        ),
    ]
