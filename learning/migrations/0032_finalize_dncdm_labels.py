from django.db import migrations


MODEL_TARGETS = [
    {
        "final_name": "DNCDM",
        "description": "DNCDM（Decoupling NCDM）中的 D 表示交互记录解耦（Decoupling）。该模型先修关系传播生成关系增强 Q 矩阵，以提升认知状态估计的可解释性与稳定性。",
        "aliases": [
            "IRDNCDM",
            "IRD-NCDM-NoGate",
            "IRD-NCDM-FP",
            "FP-IRD-NCDM",
        ],
    },
    {
        "final_name": "GDNCDM",
        "description": "GDNCDM（Gated Decoupling NCDM）中的 D 表示交互记录解耦（Decoupling），G 表示门控融合（Gated Fusion）。该模型在解耦表示与先修关系正向传播框架上进一步引入软门控机制，自适应融合原始 Q 矩阵与传播残差信号，以缓解噪声关系和过传播对认知状态估计的干扰。",
        "aliases": [
            "SGIRDNCDM",
            "IRD-NCDM-SoftGate",
            "IRD-NCDM-SGFP",
            "SG-IRD-NCDM",
        ],
    },
]


DATASET_TARGETS = [
    {
        "name": "IRD-math",
        "description": "基于 math 作答日志构建的交互记录解耦认知诊断数据集，提供学生-习题作答记录、题目知识点关联以及显式先修关系。",
        "student_info": "False",
        "exercise_info": "False",
        "knowledge_relation": "True",
        "order": -40,
    },
    {
        "name": "IRD-assist-115",
        "description": "基于 ASSISTments 2009-2010 作答日志构建的 115 知识点交互记录解耦数据集，提供学生-习题作答记录、题目知识点关联以及显式先修关系。",
        "student_info": "False",
        "exercise_info": "False",
        "knowledge_relation": "True",
        "order": -39,
    },
    {
        "name": "IRD-assist-175",
        "description": "基于 ASSISTments 2009-2010 作答日志构建的 175 知识点交互记录解耦数据集，提供学生-习题作答记录、题目知识点关联以及显式先修关系。",
        "student_info": "False",
        "exercise_info": "False",
        "knowledge_relation": "True",
        "order": -38,
    },
    {
        "name": "IRD-eedi",
        "description": "基于 Eedi 作答日志构建的交互记录解耦认知诊断数据集，提供学生-习题作答记录、题目知识点关联以及显式先修关系。",
        "student_info": "False",
        "exercise_info": "False",
        "knowledge_relation": "True",
        "order": -37,
    },
]


def finalize_dncdm_labels(apps, schema_editor):
    DiagnosisModel = apps.get_model("learning", "DiagnosisModel")
    Dataset = apps.get_model("learning", "Dataset")

    for target in MODEL_TARGETS:
        final_model = DiagnosisModel.objects.filter(name=target["final_name"]).first()
        if final_model is None:
            alias_model = DiagnosisModel.objects.filter(name__in=target["aliases"]).first()
            if alias_model:
                alias_model.name = target["final_name"]
                alias_model.description = target["description"]
                alias_model.category = "nn"
                alias_model.is_active = True
                alias_model.paper_link = ""
                alias_model.created_by = None
                alias_model.save()
            else:
                DiagnosisModel.objects.create(
                    name=target["final_name"],
                    description=target["description"],
                    category="nn",
                    is_active=True,
                    paper_link="",
                    created_by=None,
                )
        else:
            final_model.description = target["description"]
            final_model.category = "nn"
            final_model.is_active = True
            final_model.paper_link = ""
            final_model.created_by = None
            final_model.save()

        DiagnosisModel.objects.filter(name__in=target["aliases"]).exclude(name=target["final_name"]).update(
            is_active=False,
            description="旧名称已停用，请使用 %s。" % target["final_name"],
        )

    for target in DATASET_TARGETS:
        Dataset.objects.update_or_create(
            name=target["name"],
            defaults={
                "description": target["description"],
                "student_info": target["student_info"],
                "exercise_info": target["exercise_info"],
                "knowledge_relation": target["knowledge_relation"],
                "order": target["order"],
            },
        )


def keep_dncdm_labels(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("learning", "0031_finalize_irdncdm_names"),
    ]

    operations = [
        migrations.RunPython(finalize_dncdm_labels, keep_dncdm_labels),
    ]
