from django.db import migrations


MODEL_TARGETS = [
    {
        "name": "DNCDM",
        "description": "DNCDM（Decoupling NCDM）中的 D 表示交互记录解耦（Decoupling）。该模型先修关系传播生成关系增强 Q 矩阵，以提升认知状态估计的可解释性与稳定性。",
    },
    {
        "name": "GDNCDM",
        "description": "GDNCDM（Gated Decoupling NCDM）中的 D 表示交互记录解耦（Decoupling），G 表示门控融合（Gated Fusion）。该模型在解耦表示与先修关系正向传播框架上进一步引入软门控机制，自适应融合原始 Q 矩阵与传播残差信号，以缓解噪声关系和过传播对认知状态估计的干扰。",
    },
]


DATASET_TARGETS = [
    {
        "old_name": "IRD-math",
        "new_name": "Math-PR",
        "description": "基于 math 作答日志构建的交互记录解耦认知诊断数据集，提供学生-习题作答记录、题目知识点关联以及显式先修关系。PR 表示 Prerequisite Relation，即该数据集包含先修关系。",
        "order": -40,
    },
    {
        "old_name": "IRD-assist-115",
        "new_name": "Assist115-PR",
        "description": "基于 ASSISTments 2009-2010 作答日志构建的 115 知识点交互记录解耦数据集，提供学生-习题作答记录、题目知识点关联以及显式先修关系。PR 表示 Prerequisite Relation，即该数据集包含先修关系。",
        "order": -39,
    },
    {
        "old_name": "IRD-assist-175",
        "new_name": "Assist175-PR",
        "description": "基于 ASSISTments 2009-2010 作答日志构建的 175 知识点交互记录解耦数据集，提供学生-习题作答记录、题目知识点关联以及显式先修关系。PR 表示 Prerequisite Relation，即该数据集包含先修关系。",
        "order": -38,
    },
    {
        "old_name": "IRD-eedi",
        "new_name": "Eedi-PR",
        "description": "基于 Eedi 作答日志构建的交互记录解耦认知诊断数据集，提供学生-习题作答记录、题目知识点关联以及显式先修关系。PR 表示 Prerequisite Relation，即该数据集包含先修关系。",
        "order": -37,
    },
]


def update_dncdm_dataset_names(apps, schema_editor):
    DiagnosisModel = apps.get_model("learning", "DiagnosisModel")
    Dataset = apps.get_model("learning", "Dataset")

    for target in MODEL_TARGETS:
        DiagnosisModel.objects.filter(name=target["name"]).update(
            description=target["description"],
            category="nn",
            is_active=True,
        )

    for target in DATASET_TARGETS:
        old_dataset = Dataset.objects.filter(name=target["old_name"]).first()
        new_dataset = Dataset.objects.filter(name=target["new_name"]).first()

        defaults = {
            "description": target["description"],
            "student_info": "False",
            "exercise_info": "False",
            "knowledge_relation": "True",
            "order": target["order"],
        }

        if old_dataset and not new_dataset:
            old_dataset.name = target["new_name"]
            for field, value in defaults.items():
                setattr(old_dataset, field, value)
            old_dataset.save()
        else:
            Dataset.objects.update_or_create(
                name=target["new_name"],
                defaults=defaults,
            )


def keep_dncdm_dataset_names(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("learning", "0032_finalize_dncdm_labels"),
    ]

    operations = [
        migrations.RunPython(update_dncdm_dataset_names, keep_dncdm_dataset_names),
    ]
