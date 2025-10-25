from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.dashboard, name='dashboard'),
    path('student/dashboard/', views.student_dashboard, name='student_dashboard'),
    path('teacher/dashboard/', views.teacher_dashboard, name='teacher_dashboard'),

    path('subject/<int:subject_id>/exercises/', views.exercise_list, name='exercise_list'),
    path('exercise/<int:exercise_id>/take/', views.take_exercise, name='take_exercise'),
    path('exercise/result/<int:log_id>/', views.exercise_result, name='exercise_result'),

    path('diagnosis/', views.student_diagnosis, name='student_diagnosis'),
    path('subject/<int:subject_id>/knowledge/', views.knowledge_points, name='knowledge_points'),

    path('teacher/upload/exercise/', views.upload_exercise, name='upload_exercise'),
    path('teacher/upload/knowledge/', views.upload_knowledge, name='upload_knowledge'),
    path('teacher/qmatrix/', views.q_matrix_management, name='q_matrix_management'),
]