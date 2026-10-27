from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('intelligence', '0003_usage_reasoning_tokens'),
    ]

    operations = [
        migrations.AlterField(
            model_name='analysisjob',
            name='prompt_version',
            field=models.CharField(default='academic-review-v2', max_length=32),
        ),
    ]
