from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('research', '0002_versioned_extraction_algorithm'),
    ]

    operations = [
        migrations.AddField(
            model_name='documentversion',
            name='processing_started_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='documentversion',
            name='processing_error',
            field=models.CharField(blank=True, max_length=240),
        ),
        migrations.AddField(
            model_name='documentversion',
            name='processing_attempt',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
