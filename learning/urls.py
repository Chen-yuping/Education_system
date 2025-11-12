from django.urls import path
from . import views_student,views_teacher

urlpatterns = [
    path('dashboard/', views_student.dashboard, name='dashboard'),
    path('student/dashboard/', views_student.student_dashboard, name='student_dashboard'),
    path('teacher/dashboard/', views_teacher.teacher_dashboard, name='teacher_dashboard'),

    path('student/subject/', views_student.student_subject, name='student_subject'),
    path('subject/<int:subject_id>/exercises/', views_student.exercise_list, name='exercise_list'),
    path('exercise/<int:exercise_id>/take/', views_student.take_exercise, name='take_exercise'),
    path('exercise/result/<int:log_id>/', views_student.exercise_result, name='exercise_result'),

    path('diagnosis/', views_student.student_diagnosis, name='student_diagnosis'),
    path('subject/<int:subject_id>/knowledge/', views_student.knowledge_points, name='knowledge_points'),

    path('teacher/upload/exercise/', views_teacher.upload_exercise, name='upload_exercise'),
    path('teacher/upload/knowledge/', views_teacher.upload_knowledge, name='upload_knowledge'),
    path('teacher/qmatrix/', views_teacher.q_matrix_management, name='q_matrix_management'),
]