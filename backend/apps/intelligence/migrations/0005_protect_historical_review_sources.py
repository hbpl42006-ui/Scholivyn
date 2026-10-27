from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('intelligence', '0004_current_prompt_version_default')]

    operations = [
        migrations.AlterField(
            model_name='analysisjob', name='project',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                    related_name='analysis_jobs', to='research.researchproject'),
        ),
        migrations.AlterField(
            model_name='analysisjob', name='document',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                    related_name='analysis_jobs', to='research.researchdocument'),
        ),
        migrations.AlterField(
            model_name='analysisjob', name='document_version',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                    related_name='analysis_jobs', to='research.documentversion'),
        ),
        migrations.AlterField(
            model_name='writingsuggestion', name='document_version',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                    related_name='writing_suggestions', to='research.documentversion'),
        ),
    ]
