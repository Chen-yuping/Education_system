"""
LLM-based grading utility for subjective answers
Supports multiple LLM providers: OpenAI, Qwen, Claude
"""
import requests
import json
from django.conf import settings
from typing import Dict, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class LLMGrader:
    """LLM grading service"""
    
    def __init__(self):
        self.config = settings.LLM_CONFIG
        self.provider = self.config.get('provider', 'openai')
        self.api_key = self.config.get('api_key', '')
        self.model = self.config.get('model', 'gpt-3.5-turbo')
        self.temperature = self.config.get('temperature', 0.3)
        self.max_tokens = self.config.get('max_tokens', 500)
        self.timeout = self.config.get('timeout', 30)
    
    def grade_answer(self, exercise_content: str, reference_answer: str, 
                    student_answer: str, exercise_solution: str = '') -> Dict:
        """
        Grade a subjective answer using LLM
        
        Args:
            exercise_content: The exercise/question content
            reference_answer: The reference/model answer
            student_answer: The student's answer
            exercise_solution: Optional solution/explanation
        
        Returns:
            Dict with keys:
            - is_correct: bool (True/False/None if uncertain)
            - score: float (0-100)
            - feedback: str (feedback for student)
            - reasoning: str (reasoning from LLM)
            - confidence: float (0-1, confidence level)
            - error: str (error message if failed)
        """
        
        if not self.api_key:
            return {
                'is_correct': None,
                'score': None,
                'feedback': '未配置LLM API密钥',
                'reasoning': '',
                'confidence': 0,
                'error': 'LLM_API_KEY not configured'
            }
        
        try:
            if self.provider == 'openai':
                return self._grade_with_openai(exercise_content, reference_answer, 
                                              student_answer, exercise_solution)
            elif self.provider == 'qwen':
                return self._grade_with_qwen(exercise_content, reference_answer, 
                                            student_answer, exercise_solution)
            elif self.provider == 'claude':
                return self._grade_with_claude(exercise_content, reference_answer, 
                                              student_answer, exercise_solution)
            else:
                return {
                    'is_correct': None,
                    'score': None,
                    'feedback': f'不支持的LLM提供商: {self.provider}',
                    'reasoning': '',
                    'confidence': 0,
                    'error': f'Unsupported provider: {self.provider}'
                }
        except Exception as e:
            logger.error(f"LLM grading error: {str(e)}")
            return {
                'is_correct': None,
                'score': None,
                'feedback': '评分服务暂时不可用',
                'reasoning': '',
                'confidence': 0,
                'error': str(e)
            }
    
    def _grade_with_openai(self, exercise_content: str, reference_answer: str,
                          student_answer: str, exercise_solution: str) -> Dict:
        """Grade using OpenAI API"""
        
        prompt = self._build_grading_prompt(exercise_content, reference_answer, 
                                           student_answer, exercise_solution)
        
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        data = {
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': '你是一个专业的教育评分专家。请根据题目、参考答案和学生答案进行评分。'},
                {'role': 'user', 'content': prompt}
            ],
            'temperature': self.temperature,
            'max_tokens': self.max_tokens
        }
        
        response = requests.post(
            'https://api.openai.com/v1/chat/completions',
            headers=headers,
            json=data,
            timeout=self.timeout
        )
        
        if response.status_code != 200:
            raise Exception(f"OpenAI API error: {response.text}")
        
        result = response.json()
        content = result['choices'][0]['message']['content']
        
        return self._parse_grading_response(content)
    
    def _grade_with_qwen(self, exercise_content: str, reference_answer: str,
                        student_answer: str, exercise_solution: str) -> Dict:
        """Grade using Alibaba Qwen API"""
        
        prompt = self._build_grading_prompt(exercise_content, reference_answer, 
                                           student_answer, exercise_solution)
        
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }
        
        data = {
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': '你是一个专业的教育评分专家。请根据题目、参考答案和学生答案进行评分。'},
                {'role': 'user', 'content': prompt}
            ],
            'temperature': self.temperature,
            'max_tokens': self.max_tokens
        }
        
        response = requests.post(
            'https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation',
            headers=headers,
            json=data,
            timeout=self.timeout
        )
        
        if response.status_code != 200:
            raise Exception(f"Qwen API error: {response.text}")
        
        result = response.json()
        content = result['output']['text']
        
        return self._parse_grading_response(content)
    
    def _grade_with_claude(self, exercise_content: str, reference_answer: str,
                          student_answer: str, exercise_solution: str) -> Dict:
        """Grade using Anthropic Claude API"""
        
        prompt = self._build_grading_prompt(exercise_content, reference_answer, 
                                           student_answer, exercise_solution)
        
        headers = {
            'x-api-key': self.api_key,
            'Content-Type': 'application/json',
            'anthropic-version': '2023-06-01'
        }
        
        data = {
            'model': self.model,
            'max_tokens': self.max_tokens,
            'system': '你是一个专业的教育评分专家。请根据题目、参考答案和学生答案进行评分。',
            'messages': [
                {'role': 'user', 'content': prompt}
            ]
        }
        
        response = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers=headers,
            json=data,
            timeout=self.timeout
        )
        
        if response.status_code != 200:
            raise Exception(f"Claude API error: {response.text}")
        
        result = response.json()
        content = result['content'][0]['text']
        
        return self._parse_grading_response(content)
    
    def _build_grading_prompt(self, exercise_content: str, reference_answer: str,
                             student_answer: str, exercise_solution: str) -> str:
        """Build the grading prompt"""
        
        prompt = f"""请评分以下学生答案。

【题目】
{exercise_content}

【参考答案】
{reference_answer}

【学生答案】
{student_answer}
"""
        
        if exercise_solution:
            prompt += f"""
【答案解析】
{exercise_solution}
"""
        
        prompt += """
请按以下JSON格式返回评分结果（只返回JSON，不要其他内容）：
{
    "is_correct": true/false,
    "score": 85,
    "feedback": "学生的答案...",
    "reasoning": "评分理由：...",
    "confidence": 0.95
}

其中：
- is_correct: 答案是否正确（true/false）
- score: 评分（0-100）
- feedback: 对学生的反馈
- reasoning: 评分理由
- confidence: 评分置信度（0-1）
"""
        
        return prompt
    
    def _parse_grading_response(self, response_text: str) -> Dict:
        """Parse LLM response and extract grading result"""
        
        try:
            # Try to extract JSON from response
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start == -1 or json_end == 0:
                raise ValueError("No JSON found in response")
            
            json_str = response_text[json_start:json_end]
            result = json.loads(json_str)
            
            # Validate and normalize result
            return {
                'is_correct': result.get('is_correct'),
                'score': min(100, max(0, result.get('score', 0))),
                'feedback': result.get('feedback', ''),
                'reasoning': result.get('reasoning', ''),
                'confidence': min(1.0, max(0, result.get('confidence', 0.5))),
                'error': None
            }
        except Exception as e:
            logger.error(f"Failed to parse LLM response: {str(e)}")
            return {
                'is_correct': None,
                'score': None,
                'feedback': '评分结果解析失败',
                'reasoning': response_text[:200],
                'confidence': 0,
                'error': str(e)
            }


def grade_subjective_answer(exercise_content: str, reference_answer: str,
                           student_answer: str, exercise_solution: str = '') -> Dict:
    """
    Convenience function to grade a subjective answer
    
    Args:
        exercise_content: The exercise/question content
        reference_answer: The reference/model answer
        student_answer: The student's answer
        exercise_solution: Optional solution/explanation
    
    Returns:
        Dict with grading result
    """
    grader = LLMGrader()
    return grader.grade_answer(exercise_content, reference_answer, 
                              student_answer, exercise_solution)
