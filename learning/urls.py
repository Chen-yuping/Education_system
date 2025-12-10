from django.urls import path
from . import views_student,views_teacher
from django.urls import path, include
from .exercise_file import views_exercisefile
from .diagnosis import views_diagnosis


urlpatterns = [

    path('dashboard/', views_student.dashboard, name='dashboard'),
    path('student/dashboard/', views_student.student_dashboard, name='student_dashboard'),
    path('teacher/dashboard/', views_teacher.teacher_dashboard, name='teacher_dashboard'),

    path('student/subject/', views_student.student_subject, name='student_subject'),
    path('subject/<int:subject_id>/exercises/', views_student.exercise_list, name='exercise_list'),
    path('exercise/<int:exercise_id>/take/', views_student.take_exercise, name='take_exercise'),
    path('exercise/result/<int:log_id>/', views_student.exercise_result, name='exercise_result'),

    #学生诊断
    path('diagnosis/', views_diagnosis.student_diagnosis, name='student_diagnosis'),

    path('subject/<int:subject_id>/knowledge/', views_student.knowledge_points, name='knowledge_points'),

    #上传习题页面
    path('teacher/upload/exercise/', views_exercisefile.upload_exercise, name='upload_exercise'),

    path('teacher/upload/knowledge/', views_teacher.upload_knowledge, name='upload_knowledge'),
    path('teacher/qmatrix/', views_teacher.q_matrix_management, name='q_matrix_management'),

    #单个科目的答题log
    path('subject/<int:subject_id>/exercise-logs/', views_student.subject_exercise_logs, name='subject_exercise_logs'),
    #单个科目的学生诊断
    path('subject/<int:subject_id>/diagnosis/', views_student.student_subject_diagnosis, name='student_subject_diagnosis'),

    # 题库管理
    path('exercise-management/', views_teacher.exercise_management, name='exercise_management'),
    path('exercise-management/add/', views_teacher.exercise_add, name='exercise_add'),
    path('exercise-management/edit/<int:exercise_id>/', views_teacher.exercise_edit, name='exercise_edit'),
    path('exercise-management/delete/<int:exercise_id>/', views_teacher.exercise_delete, name='exercise_delete'),
    path('exercise-management/detail/<int:exercise_id>/', views_teacher.exercise_detail, name='exercise_detail'),
    path('exercise-management/batch-delete/', views_teacher.exercise_batch_delete, name='exercise_batch_delete'),
    path('exercise-management/export/', views_teacher.export_exercises, name='export_exercises'),


]