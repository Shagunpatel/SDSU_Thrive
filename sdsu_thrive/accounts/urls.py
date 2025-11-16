from django.urls import path
from . import views

urlpatterns = [
    path('', views.front_page, name='front_page'),
    path('signup/', views.signup, name='signup'),
    path('login/', views.login_view, name='login'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('logout/', views.logout_view, name='logout'),

    # NEW
    path('quiz/', views.quiz, name='quiz'),
    path('quiz/result/', views.quiz_result, name='quiz_result'),

    path('study/', views.study_home, name='study_home'),
    path('study/add/', views.study_add_subject, name='study_add'),
    path('study/<slug:subject>/', views.study_subject, name='study_subject'),
]
