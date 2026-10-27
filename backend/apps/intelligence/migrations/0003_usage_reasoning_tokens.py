from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('intelligence', '0002_resumable_groq_quota_processing'),
    ]

    operations = [
        migrations.AddField(
            model_name='aiusagerecord',
            name='reasoning_tokens',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
