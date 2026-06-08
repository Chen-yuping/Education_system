"""
实体质量启发式评估器
======================================================================
移植自 Learn/edu-knowledge-graph/backend/knowledge_quality_evaluator.py
用于在「融合图谱评估」中给出实体质量（高/中/低）分布与有效实体占比，
作为融合质量评分的一个维度（不依赖大模型，纯本地启发式，速度快）。
"""
import re
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class EntityQualityEvaluator:
    """知识点实体质量评估器（启发式打分）"""

    def __init__(self):
        # 常见技术术语（命中加分）
        self.common_tech_terms = [
            '数据', '算法', '线性表', '存储结构', '顺序存储', '链式存储',
            '数据结构', '顺序表', '链表', '栈', '队列', '树', '二叉树', '图',
            '排序', '查找', 'CPU', 'RAM', 'ROM', 'TCP', 'IP', 'HTTP', 'HTTPS', 'SQL', 'DBMS',
            '函数', '导数', '积分', '矩阵', '向量', '概率', '方程',
            '力', '能量', '电场', '磁场', '动量', '原子', '分子', '反应',
        ]
        # 无效短语（命中扣分）
        self.invalid_phrases = [
            '量算法', '和存储', '用二进制', '的数据', '的方法', '的技术',
            '的概念', '的理论', '的应用', '和系统', '和网络', '和算法',
            '和结构', '和模型', '和协议',
        ]
        # 不完整术语后缀（命中扣分）
        self.incomplete_suffixes = [
            '编', '括', '反', '加', '方', '性', '问', '储', '据', '素', '法', '表', '构',
            '原', '量', '算', '和', '存', '式', '化', '度', '力',
        ]
        # 例外术语（即使命中不完整后缀也保留）
        self.exception_terms = [
            '数据结构', '顺序存储结构', '链式存储结构', '存储结构',
            '线性表', '时间复杂度', '空间复杂度', '数据元素',
        ]
        # 句子片段（命中扣分）
        self.sentence_fragments = [
            '二者都是', '每个协议栈', '从技术', '一开始就试图',
            '的意思', '的精确定义', '的实现方法', '的协议栈', '的网络结构',
        ]
        # 通用词汇（过于宽泛，轻微扣分）
        self.common_words = [
            '系统', '技术', '方法', '原理', '概念', '理论', '应用', '分析',
            '公式', '定理', '公理', '定律', '变量', '常量', '操作', '指令',
            '网络', '存储', '进程', '线程', '文件', '程序', '语言',
        ]

    def evaluate_quality(self, knowledge_point: str) -> Dict:
        """评估单个知识点质量，返回 {knowledge_point, score, quality, reasons}"""
        score = 0
        reasons = []
        clean_kp = (knowledge_point or '').strip(' ,.；，。！？')

        # 1. 长度检查
        if len(clean_kp) < 2:
            score -= 2
            reasons.append('长度不足')
        elif len(clean_kp) > 15:
            score -= 1
            reasons.append('长度过长')
        else:
            score += 2

        # 2. 完整性检查
        if clean_kp.endswith(tuple(self.incomplete_suffixes)) and clean_kp not in self.exception_terms:
            score -= 2
            reasons.append('不完整术语')
        else:
            score += 1

        # 3. 领域相关性（命中常见技术术语加分）
        is_relevant = False
        if clean_kp in self.common_tech_terms:
            score += 2
            is_relevant = True
        else:
            for term in self.common_tech_terms:
                if term in clean_kp and len(term) >= 2:
                    score += 1
                    is_relevant = True
                    break
        if not is_relevant:
            if clean_kp.isupper() and len(clean_kp) >= 2:
                score += 1
            else:
                score -= 1
                reasons.append('领域相关性低')

        # 4. 句子片段检查
        if any(frag in clean_kp for frag in self.sentence_fragments):
            score -= 2
            reasons.append('句子片段')

        # 5. 无效短语检查
        if any(p in clean_kp for p in self.invalid_phrases):
            score -= 2
            reasons.append('包含无效短语')

        # 6. 特殊字符检查
        if any(ch in '!@#$%^&*()_+{}|[]\\;"<>?/~`\'' for ch in clean_kp):
            score -= 1
            reasons.append('包含特殊字符')

        # 7. 纯数字检查
        if clean_kp.isdigit():
            score -= 2
            reasons.append('纯数字')

        # 8. 过于通用检查
        if clean_kp in self.common_words:
            score -= 1
            reasons.append('过于通用')

        # 质量等级
        if score >= 4:
            quality = 'high'
        elif score >= 0:
            quality = 'medium'
        else:
            quality = 'low'

        return {
            'knowledge_point': clean_kp,
            'score': score,
            'quality': quality,
            'reasons': reasons,
        }

    def batch_statistics(self, names: List[str]) -> Dict:
        """批量评估并汇总统计：高/中/低数量、平均分、有效实体占比"""
        evals = [self.evaluate_quality(n) for n in names]
        total = len(evals) or 1
        high = sum(1 for e in evals if e['quality'] == 'high')
        medium = sum(1 for e in evals if e['quality'] == 'medium')
        low = sum(1 for e in evals if e['quality'] == 'low')
        avg = sum(e['score'] for e in evals) / total

        return {
            'total': len(evals),
            'highQuality': high,
            'mediumQuality': medium,
            'lowQuality': low,
            'averageScore': round(avg, 2),
            'highQualityPercentage': round(high / total * 100, 2),
            'mediumQualityPercentage': round(medium / total * 100, 2),
            'lowQualityPercentage': round(low / total * 100, 2),
            # 有效实体占比 = (高 + 中) / 总
            'validEntityPercentage': round((high + medium) / total * 100, 2),
            'lowQualitySamples': [e['knowledge_point'] for e in evals if e['quality'] == 'low'][:20],
        }
