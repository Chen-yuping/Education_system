import json
from accounts.models import User
from learning.models import Choice, Exercise


def populate_choices_from_file(json_file_path):
    """
    从JSON文件批量填充Choice表
    """
    try:
        with open(json_file_path, 'r', encoding='utf-8') as file:
            data_list = json.load(file)

        success_count = 0
        error_count = 0

        for data in data_list:
            try:
                # 提取exercise_id - 根据你的数据结构调整
                exercise_id = data.get('detail', {}).get('exercise_id')

                if not exercise_id:
                    print("跳过: 未找到exercise_id")
                    error_count += 1
                    continue

                # 获取Exercise对象
                try:
                    exercise = Exercise.objects.get(id=exercise_id)
                except Exercise.DoesNotExist:
                    print(f"跳过: 习题ID {exercise_id} 不存在")
                    error_count += 1
                    continue

                # 获取选项数据
                option_data = data.get('option') or data.get('detail', {}).get('option', {})
                answer_data = data.get('answer') or data.get('detail', {}).get('answer', [])

                if not option_data:
                    print(f"跳过: 习题 {exercise_id} 无选项数据")
                    error_count += 1
                    continue

                # 清空现有选项
                Choice.objects.filter(exercise=exercise).delete()

                # 添加新选项
                order = 0
                for option_key, option_content in option_data.items():
                    order += 1
                    is_correct = option_key in answer_data or f'"{option_key}"' in answer_data

                    Choice.objects.create(
                        exercise=exercise,
                        content=option_content,
                        is_correct=is_correct,
                        order=order
                    )

                success_count += 1
                print(f"成功: 习题 {exercise_id} - 添加了 {order} 个选项")

            except Exception as e:
                print(f"处理数据时出错: {e}")
                error_count += 1

        print(f"处理完成: 成功 {success_count} 条, 失败 {error_count} 条")

    except Exception as e:
        print(f"读取文件时出错: {e}")

# 使用示例
populate_choices_from_file('problem.json')