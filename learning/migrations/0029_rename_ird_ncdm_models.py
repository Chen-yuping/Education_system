from django.db import migrations


MODEL_RENAMES = [
    (
        "IRD-NCDM-NoGate",
        "IRDNCDM",
        "针对学习平台交互记录与认知诊断输入表示异构的问题，IRDNCDM 通过交互记录解耦构建学生-习题-知识点三元表示，并基于先修关系传播生成关系增强 Q 矩阵。",
    ),
    (
        "IRD-NCDM-SoftGate",
        "SGIRDNCDM",
        "SGIRDNCDM 在交互记录解耦与关系传播框架中引入软门控机制，自适应融合原始 Q 矩阵与传播残差信号，以缓解噪声关系和过传播对掌握状态估计的影响。",
    ),
]


def rename_ird_ncdm_models(apps, schema_editor):
    DiagnosisModel = apps.get_model("learning", "DiagnosisModel")

    for old_name, new_name, description in MODEL_RENAMES:
        old_model = DiagnosisModel.objects.filter(name=old_name).first()
        new_model = DiagnosisModel.objects.filter(name=new_name).first()

        if old_model and not new_model:
            old_model.name = new_name
            old_model.description = description
            old_model.category = "nn"
            old_model.is_active = True
            old_model.paper_link = ""
            old_model.created_by = None
            old_model.save()
        elif new_model:
            new_model.description = description
            new_model.category = "nn"
            new_model.is_active = True
            new_model.paper_link = ""
            new_model.created_by = None
            new_model.save()
        else:
            DiagnosisModel.objects.create(
                name=new_name,
                description=description,
                category="nn",
                is_active=True,
                paper_link="",
                created_by=None,
            )

        DiagnosisModel.objects.filter(name=old_name).update(
            is_active=False,
            description="旧名称已停用，请使用 %s。" % new_name,
        )


def keep_model_names(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("learning", "0028_ird_ncdm_dataset_visibility"),
    ]

    operations = [
        migrations.RunPython(rename_ird_ncdm_models, keep_model_names),
    ]
