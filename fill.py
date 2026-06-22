import re
import json
import pymysql
# 填空题格式统一


# ================= 1. 你的数据库连接配置 =================
DB_CONFIG = {
    "host": "101.201.178.241",
    "user": "edu_diagnosis",
    "password": "zbKfBnHZTzdP4CbH",
    "database": "edu_diagnosis",
    "port": 3306,
    "charset": "utf8mb4"
}


# ================= 2. 核心：双格式兼容清洗逻辑 =================
def unify_format(content, answer_str):
    """
    不管输入的是老格式还是新格式，最终全部统一输出为：
    content: 带 [填空1] 的文本
    answer: 标准的 单层 JSON 字符串
    """
    # -----------------------------------------------
    # 步骤 A：统一处理 content (题干)
    # -----------------------------------------------
    new_content = content
    if content:
        # 兼容判断：如果已经包含 [填空1]，说明是新格式，不重复清洗
        if "[填空1]" not in content:
            blank_pattern = re.compile(r'_{2,}|（\s*）|\(\s*\)')
            counter = 1

            def replace_match(match):
                nonlocal counter
                res = f"[填空{counter}]"
                counter += 1
                return res

            new_content = blank_pattern.sub(replace_match, content)

    # -----------------------------------------------
    # 步骤 B：统一处理 answer (答案)
    # -----------------------------------------------
    new_answer = "{}"
    if answer_str:
        answer_str = answer_str.strip()

        # 状况 1：遇到了之前改错的“套娃”格式 (预防针)
        if '{\\"1\\":' in answer_str or '["{\\"1\\":' in answer_str:
            words = re.findall(r'[\u4e00-\u9fa5\w\-\+]+', answer_str)
            clean_words = [w for w in words if not w.isdigit()]
            correct_dict = {str(i): [word] for i, word in enumerate(clean_words, start=1)}
            new_answer = json.dumps(correct_dict, ensure_ascii=False)

        # 状况 2：已经是标准的 JSON 格式了 (新格式)
        elif answer_str.startswith('{') and answer_str.endswith('}'):
            try:
                # 尝试解析，如果没有报错，说明已经是标准JSON，保持原样
                json.loads(answer_str)
                new_answer = answer_str
            except Exception:
                # 如果套着括号但解析失败，当做普通文本处理，走下面的老格式逻辑
                pass

        # 状况 3：传统文本格式，如 "面向, 传输服务" (老格式)
        else:
            answers = [ans.strip() for ans in re.split(r'[,，]', answer_str) if ans.strip()]
            answer_dict = {str(idx): [ans] for idx, ans in enumerate(answers, start=1)}
            new_answer = json.dumps(answer_dict, ensure_ascii=False)

    return new_content, new_answer


# ================= 3. 自动化批处理执行 修改处理的数据范围=================
def main():
    print("⏳ 正在连接数据库...")
    try:
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        print("🚀 连接成功！开始统一数据格式...")
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        return

    try:
        # 查询你要处理的数据范围
        sql_select = """
            SELECT id, content, answer 
            FROM learning_exercise 
            WHERE id BETWEEN 2025110809 AND 2025111156 
              AND question_type = 4;
        """
        cursor.execute(sql_select)
        rows = cursor.fetchall()

        print(f"📦 查找到目标数据: {len(rows)} 条")

        updated_count = 0
        for row in rows:
            ex_id = row['id']
            old_content = row['content']
            old_answer = row['answer']

            # 调用万能兼容清洗函数
            new_content, new_answer = unify_format(old_content, old_answer)

            # 【核心安全防线】如果清洗后的格式和数据库里的一模一样，绝对不执行 UPDATE
            if new_content == old_content and new_answer == old_answer:
                continue

            # 只有确实需要改变格式的数据，才写入数据库
            sql_update = """
                UPDATE learning_exercise 
                SET content = %s, answer = %s
                WHERE id = %s;
            """
            cursor.execute(sql_update, (new_content, new_answer, ex_id))
            updated_count += 1

        # 提交事务
        conn.commit()
        print(f"🎉 统一格式完成！本次共识别并转换了 {updated_count} 条老格式数据。")
        print(f"ℹ️ 其余已经正确的格式未受到任何影响。")

    except Exception as e:
        conn.rollback()
        print(f"❌ 运行中止并回滚！错误: {e}")
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()