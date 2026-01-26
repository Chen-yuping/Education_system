#!/usr/bin/env python
"""
Test script for LLM grading functionality
Run this to verify your LLM configuration is working correctly
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'edu_system.settings')
sys.path.insert(0, os.path.dirname(__file__))
django.setup()

from learning.llm_grading import grade_subjective_answer


def test_llm_grading():
    """Test the LLM grading functionality"""
    
    print("=" * 60)
    print("LLM Grading Test")
    print("=" * 60)
    
    # Test data
    exercise_content = "请解释什么是光合作用？"
    reference_answer = "光合作用是植物利用光能将二氧化碳和水转化为葡萄糖和氧气的过程。"
    student_answer = "光合作用是植物通过阳光把二氧化碳和水变成糖和氧气的过程。"
    exercise_solution = "光合作用包括光反应和暗反应两个阶段。光反应发生在类囊体膜上，暗反应发生在基质中。"
    
    print("\n测试数据:")
    print(f"题目: {exercise_content}")
    print(f"参考答案: {reference_answer}")
    print(f"学生答案: {student_answer}")
    print(f"答案解析: {exercise_solution}")
    
    print("\n正在调用LLM进行评分...")
    print("-" * 60)
    
    result = grade_subjective_answer(
        exercise_content=exercise_content,
        reference_answer=reference_answer,
        student_answer=student_answer,
        exercise_solution=exercise_solution
    )
    
    print("\n评分结果:")
    print("-" * 60)
    print(f"是否正确: {result.get('is_correct')}")
    print(f"分数: {result.get('score')}/100")
    print(f"置信度: {result.get('confidence', 0) * 100:.0f}%")
    print(f"反馈: {result.get('feedback')}")
    print(f"理由: {result.get('reasoning')}")
    
    if result.get('error'):
        print(f"\n错误: {result.get('error')}")
        return False
    
    print("\n" + "=" * 60)
    print("✓ 测试成功！LLM评分功能正常工作。")
    print("=" * 60)
    return True


if __name__ == '__main__':
    try:
        success = test_llm_grading()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
