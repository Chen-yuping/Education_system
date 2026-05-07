import torch
import os
import csv
import json
from collections import defaultdict
from learning.models import KnowledgePoint
from CMD_survey.model import NCDM


def infer_and_get_diagnosis_data(subject_id, model_name):
    """
    推理获取诊断数据（不写数据库），直接返回用于前端可视化

    Returns:
        dict: {
            'knowledge_points': [...],      # 知识点列表及平均掌握度
            'diagnosis_results': {...},     # 每个学生的诊断结果
            'knowledge_relations': [...]    # 知识点关系（用于知识图谱）
        }
    """
    # 1. 数据目录
    data_dir = os.path.join(os.path.dirname(__file__), 'data', str(subject_id))

    # 2. 读取配置
    with open(os.path.join(data_dir, 'config.txt'), 'r') as f:
        f.readline()  # 跳过注释
        un, en, kn = f.readline().split(',')
        un, en, kn = int(un), int(en), int(kn)

    print(f"学生数: {un}, 习题数: {en}, 知识点数: {kn}")

    # 3. 读取映射表
    user_mapping = {}  # new_id -> original_id
    kp_mapping = {}  # new_id -> original_id

    with open(os.path.join(data_dir, 'homologous.csv'), 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            if row[0]:
                user_mapping[int(row[0])] = int(row[1])
            if row[4]:
                kp_mapping[int(row[4])] = int(row[5])

    # 4. 读取 log_data.json，获取每个学生实际做过的知识点
    log_data_path = os.path.join(data_dir, 'log_data.json')
    if not os.path.exists(log_data_path):
        print(f"log_data.json 不存在，请先运行 data_export.py")
        return None

    with open(log_data_path, 'r', encoding='utf-8') as f:
        all_logs = json.load(f)

    # 构建每个学生做过的知识点集合（新ID）
    student_known_kps = defaultdict(set)
    for log in all_logs:
        student_new_id = log['user_id']
        for kp in log['knowledge_code']:
            student_known_kps[student_new_id].add(kp)

    # 5. 加载模型并推理
    device = 'cuda:0' if torch.cuda.is_available() else 'cpu'
    model_path = os.path.join(data_dir, 'models', f'{model_name}.pth')

    if not os.path.exists(model_path):
        print(f"模型文件不存在: {model_path}")
        return None

    if model_name.upper() == 'NCDM':
        from CMD_survey.model import NCDM
        cdm = NCDM.NCDM(kn, en, un)
        cdm.load(model_path)
        cdm.ncdm_net.to(device)
        cdm.ncdm_net.eval()

        with torch.no_grad():
            student_indices = torch.LongTensor(list(range(un))).to(device)
            stu_emb = cdm.ncdm_net.student_emb(student_indices)
            mastery_vectors = torch.sigmoid(stu_emb).cpu().numpy()

        print(f"掌握度矩阵形状: {mastery_vectors.shape}")
    else:
        print(f"模型 {model_name} 暂不支持推理")
        return None

    # 6. 获取原始知识点信息（用于返回）
    all_knowledge_points = KnowledgePoint.objects.filter(subject_id=subject_id)
    kp_info = {kp.id: kp.name for kp in all_knowledge_points}

    # 7. 构建知识点平均掌握度
    kp_mastery_sum = defaultdict(float)
    kp_count = defaultdict(int)

    # 构建诊断结果
    diagnosis_results = {}

    for new_student_id, known_kps in student_known_kps.items():
        student_original_id = user_mapping.get(new_student_id)
        if not student_original_id:
            continue

        # 该学生的掌握度向量
        mastery_vector = mastery_vectors[new_student_id - 1]

        student_mastery = {}
        weak_points = []

        for new_kp_id in known_kps:
            mastery = mastery_vector[new_kp_id - 1]
            kp_original_id = kp_mapping.get(new_kp_id)

            if not kp_original_id:
                continue

            # 累加知识点掌握度（用于计算平均值）
            kp_mastery_sum[kp_original_id] += mastery
            kp_count[kp_original_id] += 1

            student_mastery[str(kp_original_id)] = round(float(mastery), 3)

            if mastery < 0.6:
                weak_points.append({
                    'id': kp_original_id,
                    'name': kp_info.get(kp_original_id, '未知'),
                    'mastery': round(float(mastery), 3)
                })

        overall_score = round(float(sum(student_mastery.values()) / len(student_mastery)), 3) if student_mastery else 0.0

        # 学生名称处理
        try:
            from learning.models import User
            student_obj = User.objects.filter(id=student_original_id).first()
            student_name = student_obj.username if student_obj else f"学生{student_original_id}"
        except:
            student_name = f"学生{student_original_id}"

        diagnosis_results[student_original_id] = {
            'student_id': student_original_id,
            'student_name': student_name,
            'overall_score': overall_score,
            'knowledge_mastery': student_mastery,
            'weak_points': weak_points,
            'answer_count': len(known_kps)
        }

    # 8. 构建知识点列表（包含平均掌握度）
    knowledge_points_data = []
    for kp_id, name in kp_info.items():
        avg_mastery = round(float((kp_mastery_sum.get(kp_id, 0) / kp_count.get(kp_id, 1)) * 100), 3)
        knowledge_points_data.append({
            'id': kp_id,
            'name': name,
            'avg_mastery': avg_mastery,
            'exercise_count': 0  # 可选，后续可补充
        })

    # 9. 获取知识点关系（用于知识图谱）
    from learning.models import KnowledgeGraph
    knowledge_relations = []
    kg_relations = KnowledgeGraph.objects.filter(subject_id=subject_id).values_list('source_id', 'target_id')
    for source_id, target_id in kg_relations:
        knowledge_relations.append({'source': source_id, 'target': target_id})

    return {
        'knowledge_points': knowledge_points_data,
        'diagnosis_results': diagnosis_results,
        'knowledge_relations': knowledge_relations,
        'total_students': len(diagnosis_results),
        'total_kp_count': len(knowledge_points_data)
    }