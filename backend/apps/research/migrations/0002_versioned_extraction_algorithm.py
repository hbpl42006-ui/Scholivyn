from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('research', '0001_initial')]

    operations = [
        migrations.AddField(
            model_name='documentversion',
            name='extraction_algorithm',
            field=models.CharField(default='legacy-v1', max_length=40),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='documentversion',
            name='reprocessed_from',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                                    related_name='extraction_revisions', to='research.documentversion'),
        ),
        migrations.AddConstraint(
            model_name='documentversion',
            constraint=models.UniqueConstraint(condition=models.Q(('reprocessed_from__isnull', False)),
                                               fields=('reprocessed_from', 'extraction_algorithm'),
                                               name='research_reprocess_algo_unique'),
        ),
        migrations.AlterField(
            model_name='documentversion',
            name='extraction_algorithm',
            field=models.CharField(default='academic-docx-v2', max_length=40),
        ),
    ]
