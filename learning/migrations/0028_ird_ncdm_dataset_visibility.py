from django.db import migrations


IRD_MODELS = [
    (
        "IRDNCDM",
        "针对学习平台交互记录与认知诊断输入表示异构的问题，IRDNCDM 通过交互记录解耦构建学生-习题-知识点三元表示，并基于先修关系传播生成关系增强 Q 矩阵。",
    ),
    (
        "SGIRDNCDM",
        "SGIRDNCDM 在交互记录解耦与关系传播框架中引入软门控机制，自适应融合原始 Q 矩阵与传播残差信号，以缓解噪声关系和过传播对掌握状态估计的影响。",
    ),
]

IRD_DATASETS = [
    ("IRD-math", "IRD-NCDM math dataset.", -40),
    ("IRD-assist-115", "IRD-NCDM ASSIST 115 dataset.", -39),
    ("IRD-assist-175", "IRD-NCDM ASSIST 175 dataset.", -38),
    ("IRD-eedi", "IRD-NCDM Eedi dataset.", -37),
]


def ensure_ird_ncdm_visible(apps, schema_editor):
    DiagnosisModel = apps.get_model("learning", "DiagnosisModel")
    Dataset = apps.get_model("learning", "Dataset")

    for name, description in IRD_MODELS:
        model = DiagnosisModel.objects.filter(name=name).first()
        if model is None:
            DiagnosisModel.objects.create(
                name=name,
                description=description,
                category="nn",
                is_active=True,
                paper_link="",
                created_by=None,
            )
        else:
            model.description = description
            model.category = "nn"
            model.is_active = True
            model.paper_link = ""
            model.created_by = None
            model.save()

    for name, description, order in IRD_DATASETS:
        Dataset.objects.update_or_create(
            name=name,
            defaults={
                "description": description,
                "student_info": "True",
                "exercise_info": "True",
                "knowledge_relation": "True",
                "order": order,
            },
        )


def keep_remote_rows(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("learning", "0027_dual_relation_ncdm_seed"),
    ]

    operations = [
        migrations.RunPython(ensure_ird_ncdm_visible, keep_remote_rows),
    ]
