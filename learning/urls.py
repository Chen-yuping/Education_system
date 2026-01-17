from . import views_student,views_teacher,views_researcher
from django.urls import path, include
from .exercise_file import views_exercisefile
from .diagnosis import views_diagnosis,views_personalized_recommendations
from .knowledge import views_teacherknowledge,views_studentknowledge

urlpatterns = [

#学生功能
    path('dashboard/', views_student.dashboard, name='dashboard'),#用户身份判断
    path('student/dashboard/', views_student.student_dashboard, name='student_dashboard'),#学生面板
    path('student/course-management/', views_student.student_course_management, name='student_course_management'),#课程管理
    path('student/subject/', views_student.student_subject, name='student_subject'),#所有科目
    path('student/my-subjects/', views_student.my_subjects, name='my_subjects'),  # 学生我的科目
    path('student/subjects/select/', views_student.student_subject_selection, name='student_subject_selection'),#课程选择

    #学习诊断
    path('diagnosis/',views_studentknowledge.student_knowledge_diagnosis,name='student_diagnosis'),
    path('student/api/knowledge-points/<int:subject_id>/',views_studentknowledge.student_knowledge_data_api,name='knowledge_points_api'),

    # 收藏功能
    path('favorite/add/', views_student.add_favorite, name='add_favorite'),
    path('favorite/remove/', views_student.remove_favorite, name='remove_favorite'),
    path('my-favorites/', views_student.my_favorites, name='my_favorites'),
    path('subject/<int:subject_id>/favorites/', views_student.subject_favorites, name='subject_favorites'),  # 科目收藏页面

    # 个性化推荐
    path('personalized-recommendations/',views_personalized_recommendations.personalized_recommendations,name='personalized_recommendations'),
    path('personalized-recommendations/<int:subject_id>/',views_personalized_recommendations.personalized_recommendations,name='personalized_recommendations'),
    # 推荐完成页面
    path('recommendation-result/<int:subject_id>/',views_personalized_recommendations.recommendation_result, name='recommendation_result'),

    #课程-做题-做题结果
    path('subject/<int:subject_id>/learning/', views_student.subject_learning, name='subject_learning'),  # 新的学习页面
    path('subject/<int:subject_id>/exercises/', views_student.exercise_list, name='exercise_list'),
    path('exercise/<int:exercise_id>/take/', views_student.take_exercise, name='take_exercise'),
    path('exercise/result/<int:log_id>/', views_student.exercise_result, name='exercise_result'),
    path('subject/<int:subject_id>/exercise-logs/', views_student.subject_exercise_logs, name='subject_exercise_logs'),# 单个科目的答题log

    path('subject/<int:subject_id>/knowledge/', views_student.knowledge_points, name='knowledge_points'),

#老师功能
    path('teacher/dashboard/', views_teacher.teacher_dashboard, name='teacher_dashboard'),#教师面板
    path('teacher/upload/exercise/', views_exercisefile.upload_exercise, name='upload_exercise'),#上传习题页面

    # 知识点关系图页面,知识点数据接口
    path('teacher/knowledge-graph/',views_teacherknowledge.knowledge_graph,name='teacher_knowledge_graph'),#知识点关系图
    path('teacher/api/knowledge-points/<int:subject_id>/',views_teacherknowledge.knowledge_points_api,name='knowledge_points_api'),

    path('teacher/subjects/', views_teacher.teacher_subject_management, name='teacher_subject_management'),#老师选择授课

    path('teacher/upload/knowledge/', views_teacher.upload_knowledge, name='upload_knowledge'),
    path('teacher/qmatrix/', views_teacher.q_matrix_management, name='q_matrix_management'),

    # 题库管理
    path('exercise-management/', views_teacher.exercise_management, name='exercise_management'),
    path('exercise-management/add/', views_teacher.exercise_add, name='exercise_add'),
    path('exercise-management/add-json/', views_teacher.exercise_add_json, name='exercise_add_json'),
    path('exercise-management/delete/<int:exercise_id>/', views_teacher.exercise_delete, name='exercise_delete'),
    path('exercise-management/detail/<int:exercise_id>/', views_teacher.exercise_detail_json,name='exercise_detail_json'),
    path('exercise-management/update/<int:exercise_id>/', views_teacher.exercise_update_json, name='exercise_update_json'),
    path('exercise-management/batch-delete/', views_teacher.exercise_batch_delete, name='exercise_batch_delete'),
    path('exercise-management/export/', views_teacher.export_exercises, name='export_exercises'),
    #查看学生信息
    path('teacher/students/', views_teacher.student_info, name='student_info'),
    path('teacher/api/student/<int:student_id>/answer-records/', views_teacher.get_student_answer_records, name='get_student_answer_records'),
    #诊断
    path('teacher/diagnosis/', views_diagnosis.diagnosis, name='diagnosis'),
    path('teacher/api/diagnosis/run/', views_diagnosis.run_diagnosis, name='run_diagnosis'),
    path('teacher/api/diagnosis/<int:diagnosis_id>/', views_diagnosis.get_diagnosis_result, name='get_diagnosis_result'),
    path('teacher/api/student/<int:student_id>/diagnosis/<int:subject_id>/', views_diagnosis.get_student_diagnosis_detail, name='student_diagnosis_detail'),
    path('teacher/api/diagnosis/summary/<int:subject_id>/', views_diagnosis.get_diagnosis_summary,name='get_diagnosis_summary'),

    # 批改作业
    path('teacher/grade-subjective/', views_teacher.grade_subjective, name='grade_subjective'),
    path('teacher/api/answer/<int:log_id>/', views_teacher.get_answer_detail, name='get_answer_detail'),
    path('teacher/api/answer/<int:log_id>/grade/', views_teacher.grade_answer, name='grade_answer'),

    #研究者功能
    path('researcher/dashboard/', views_researcher.researcher_dashboard, name='researcher_dashboard'),
]