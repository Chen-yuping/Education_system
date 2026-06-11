"""
融合关系人工审核：候选生成 + 写回（无独立审核表）
======================================================================
审核对象 = 融合 Step 1.5 四维语义对齐新产生的跨学科关系
（EquivalentTo / GeneralizeTo / ApplyTo），DB 原本不存在。

设计（不新建 MySQL 表）：
  - 候选不落库：每次调用 align_subjects 现算，候选是「内存中的对齐对」。
  - 审核身份：用 source_kp_id/target_kp_id 组成的稳定 key（方向归一，
    始终小 id 在前），不依赖任何审核表的自增主键。
  - 审核状态：直接从 KnowledgeGraph 推导——该知识点对若已存在一条
    relation_source='融合' 的边，则视为「已写回/已通过」；否则「待审核」。
  - 通过审核 -> 在 KnowledgeGraph 建一条 relationship_type='相似' /
    relation_source='融合' 的边（唯一入库路径）。
  - 拒绝 -> 不写库即可（无暂存表，天然不进图谱）。

约定：
  - 等价(EquivalentTo)/泛化/应用，按产品决策统一写成「相似」边。
  - 跨学科边只能挂在一个 subject，取源知识点所属学科。
  - 复用 KnowledgeGraph 的 unique_together 防重复，写回幂等。
"""
import logging
from django.db import transaction

logger = logging.getLogger(__name__)

FUSION_RELATION_TYPE = '相似'
FUSION_RELATION_SOURCE = '融合'

ALIGN_TYPE_LABELS = {
    'EquivalentTo': '等价',
    'GeneralizeTo': '泛化',
    'ApplyTo': '应用',
}


def _pair_key(src_id, tgt_id):
    """知识点对的稳定标识：方向归一（小 id 在前），不依赖任何表主键。"""
    a, b = (src_id, tgt_id) if src_id <= tgt_id else (tgt_id, src_id)
    return f"{a}_{b}"


def _parse_pair_key(key):
    """把 review_id（pair_key）解析回 (small_id, large_id)，非法返回 None。"""
    try:
        a, b = str(key).split('_', 1)
        return int(a), int(b)
    except (ValueError, AttributeError):
        return None


def build_candidates(subject_ids):
    """
    生成审核候选（现算，不落库）。返回 [{review_id, source_kp_id, target_kp_id,
    source, target, source_subject, target_subject, align_type,
    align_type_label, confidence, features, status, written_back}]

    status：'approved'（图谱中已存在该融合边）或 'pending'（尚未写回）。
    """
    from learning.models import KnowledgePoint, KnowledgeGraph
    from .entity_alignment import align_subjects

    if not subject_ids or len(subject_ids) < 2:
        return []

    alignments = align_subjects(subject_ids) or []

    # 一次性取出涉及的知识点，避免 N 次查询
    kp_ids = set()
    for al in alignments:
        kp_ids.add(al['source_kp_id'])
        kp_ids.add(al['target_kp_id'])
    kp_map = {
        kp.id: kp for kp in
        KnowledgePoint.objects.filter(id__in=kp_ids).select_related('subject')
    }

    # 已写回的融合边（按方向归一的 pair_key 建集合），用于推导审核状态
    written_pairs = set()
    fusion_edges = KnowledgeGraph.objects.filter(
        relation_source=FUSION_RELATION_SOURCE
    ).values_list('source_id', 'target_id')
    for s_id, t_id in fusion_edges:
        written_pairs.add(_pair_key(s_id, t_id))

    seen = set()
    results = []
    for al in alignments:
        s_kp = kp_map.get(al['source_kp_id'])
        t_kp = kp_map.get(al['target_kp_id'])
        if not s_kp or not t_kp or s_kp.id == t_kp.id:
            continue

        # 方向归一：始终用较小 id 作为 source，保证同一对去重稳定
        if s_kp.id > t_kp.id:
            s_kp, t_kp = t_kp, s_kp

        key = _pair_key(s_kp.id, t_kp.id)
        if key in seen:
            continue
        seen.add(key)

        written = key in written_pairs
        results.append({
            'review_id': key,
            'source_kp_id': s_kp.id,
            'target_kp_id': t_kp.id,
            'source': s_kp.name,
            'target': t_kp.name,
            'source_subject': s_kp.subject.name,
            'target_subject': t_kp.subject.name,
            'align_type': al['type'],
            'align_type_label': ALIGN_TYPE_LABELS.get(al['type'], al['type']),
            'confidence': round(al.get('confidence', 0.0), 4),
            'features': al.get('features') or {},
            'status': 'approved' if written else 'pending',
            'written_back': written,
        })

    # 置信度降序，待审优先
    results.sort(key=lambda r: (r['status'] != 'pending', -r['confidence']))
    return results


@transaction.atomic
def apply_review(approved_ids, rejected_ids, user, allowed_subject_ids=None):
    """
    提交审核结果。通过 -> 写回 KnowledgeGraph；拒绝 -> 无需落库（不进图谱即为拒绝）。
    approved_ids / rejected_ids 为 build_candidates 返回的 review_id（pair_key）。
    allowed_subject_ids 不为 None 时，仅处理源/目标知识点属于该集合的对（权限隔离）。
    返回 {written_back, approved, rejected, skipped}
    """
    from learning.models import KnowledgePoint, KnowledgeGraph

    approved_ids = list(dict.fromkeys(approved_ids or []))
    rejected_ids = list(dict.fromkeys(rejected_ids or []))
    allowed = set(allowed_subject_ids) if allowed_subject_ids is not None else None

    written_back = approved = rejected = skipped = 0

    # 收集所有涉及的知识点 id，一次性取出
    pair_ids = {}
    for key in approved_ids + rejected_ids:
        parsed = _parse_pair_key(key)
        if parsed:
            pair_ids[key] = parsed
    kp_id_set = {i for p in pair_ids.values() for i in p}
    kp_map = {
        kp.id: kp for kp in
        KnowledgePoint.objects.filter(id__in=kp_id_set).select_related('subject')
    }

    def _permitted(s_kp, t_kp):
        if allowed is None:
            return True
        return (s_kp.subject_id in allowed) or (t_kp.subject_id in allowed)

    # 拒绝：无暂存表，不写库即为拒绝；仅做权限/合法性计数
    for key in rejected_ids:
        parsed = pair_ids.get(key)
        s_kp = kp_map.get(parsed[0]) if parsed else None
        t_kp = kp_map.get(parsed[1]) if parsed else None
        if not s_kp or not t_kp or not _permitted(s_kp, t_kp):
            skipped += 1
            continue
        rejected += 1

    # 通过：写回 KnowledgeGraph（relationship_type='相似' / relation_source='融合'）
    for key in approved_ids:
        parsed = pair_ids.get(key)
        s_kp = kp_map.get(parsed[0]) if parsed else None
        t_kp = kp_map.get(parsed[1]) if parsed else None
        if not s_kp or not t_kp or not _permitted(s_kp, t_kp):
            skipped += 1
            continue

        subject = s_kp.subject  # 跨学科边挂源学科
        _, created = KnowledgeGraph.objects.get_or_create(
            subject=subject,
            source=s_kp,
            target=t_kp,
            relation_source=FUSION_RELATION_SOURCE,
            defaults={'relationship_type': FUSION_RELATION_TYPE},
        )
        if created:
            written_back += 1
        approved += 1

    logger.info(
        "[fusion-review] 写回 %s 条，通过 %s，拒绝 %s，跳过 %s",
        written_back, approved, rejected, skipped,
    )
    return {
        'written_back': written_back,
        'approved': approved,
        'rejected': rejected,
        'skipped': skipped,
    }


# ====================== 存疑关系：人工修改 / 删除 ======================
VALID_RELATION_TYPES = {'隶属', '关联', '前置', '相似'}


@transaction.atomic
def edit_relation(relation_id, action, new_type=None, user=None, allowed_subject_ids=None):
    """
    对 DeepSeek 评估中判定「存疑」的某条 KnowledgeGraph 关系做人工处理。

    action='update'：把 relationship_type 改成 new_type（须在 VALID_RELATION_TYPES 内）。
    action='delete'：直接删除该关系（教师确认存疑关系不成立）。

    allowed_subject_ids 不为 None 时，仅允许处理源/目标知识点属于该集合的关系（权限隔离）。
    返回 {status, message, ...}；非法/越权抛出 ValueError / PermissionError。
    """
    from learning.models import KnowledgeGraph

    try:
        rel = KnowledgeGraph.objects.select_related(
            'subject', 'source', 'target', 'source__subject', 'target__subject'
        ).get(id=int(relation_id))
    except (KnowledgeGraph.DoesNotExist, ValueError, TypeError):
        raise ValueError('关系不存在或已被删除')

    if allowed_subject_ids is not None:
        allowed = set(allowed_subject_ids)
        if (rel.source.subject_id not in allowed) and (rel.target.subject_id not in allowed):
            raise PermissionError('无权修改该关系')

    src_name, tgt_name = rel.source.name, rel.target.name

    if action == 'delete':
        rel.delete()
        logger.info("[fusion-review] 删除存疑关系 #%s %s→%s by %s",
                    relation_id, src_name, tgt_name, getattr(user, 'username', '-'))
        return {'action': 'delete', 'relation_id': int(relation_id),
                'message': f'已删除关系：{src_name} → {tgt_name}'}

    if action == 'update':
        if new_type not in VALID_RELATION_TYPES:
            raise ValueError(f'关系类型非法，仅支持：{", ".join(sorted(VALID_RELATION_TYPES))}')
        old_type = rel.relationship_type
        rel.relationship_type = new_type
        rel.save(update_fields=['relationship_type'])
        logger.info("[fusion-review] 修改存疑关系 #%s %s→%s 类型 %s→%s by %s",
                    relation_id, src_name, tgt_name, old_type, new_type,
                    getattr(user, 'username', '-'))
        return {'action': 'update', 'relation_id': int(relation_id),
                'new_type': new_type,
                'message': f'已将「{src_name} → {tgt_name}」关系修改为「{new_type}」'}

    raise ValueError('不支持的操作类型')
