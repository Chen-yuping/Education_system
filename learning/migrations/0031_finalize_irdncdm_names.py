from django.db import migrations


FINAL_MODELS = [
    (
        "IRDNCDM",
        "针对学习平台交互记录与认知诊断输入表示异构的问题，IRDNCDM 通过交互记录解耦构建学生-习题-知识点三元表示，并基于先修关系传播生成关系增强 Q 矩阵。",
        ["IRD-NCDM-NoGate", "IRD-NCDM-FP", "FP-IRD-NCDM"],
    ),
    (
        "SGIRDNCDM",
        "SGIRDNCDM 在交互记录解耦与关系传播框架中引入软门控机制，自适应融合原始 Q 矩阵与传播残差信号，以缓解噪声关系和过传播对掌握状态估计的影响。",
        ["IRD-NCDM-SoftGate", "IRD-NCDM-SGFP", "SG-IRD-NCDM"],
    ),
]


def finalize_irdncdm_names(apps, schema_editor):
    DiagnosisModel = apps.get_model("learning", "DiagnosisModel")

    for final_name, description, aliases in FINAL_MODELS:
        final_model = DiagnosisModel.objects.filter(name=final_name).first()
        if final_model is None:
            alias_model = DiagnosisModel.objects.filter(name__in=aliases).first()
            if alias_model:
                alias_model.name = final_name
                alias_model.description = description
                alias_model.category = "nn"
                alias_model.is_active = True
                alias_model.paper_link = ""
                alias_model.created_by = None
                alias_model.save()
            else:
                DiagnosisModel.objects.create(
                    name=final_name,
                    description=description,
                    category="nn",
                    is_active=True,
                    paper_link="",
                    created_by=None,
                )
        else:
            final_model.description = description
            final_model.category = "nn"
            final_model.is_active = True
            final_model.paper_link = ""
            final_model.created_by = None
            final_model.save()

        DiagnosisModel.objects.filter(name__in=aliases).update(
            is_active=False,
            description="旧名称已停用，请使用 %s。" % final_name,
        )


def keep_final_names(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("learning", "0030_rename_ird_ncdm_to_paper_style"),
    ]

    operations = [
        migrations.RunPython(finalize_irdncdm_names, keep_final_names),
    ]
