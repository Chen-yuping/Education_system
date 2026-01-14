from django.contrib.auth.decorators import login_required, user_passes_test
from .models import *
from .forms import ExerciseForm, KnowledgePointForm, QMatrixForm
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db.models import Q
from django.core.paginator import Paginator
import json
from datetime import datetime, timedelta
from .models import Exercise, Subject, KnowledgePoint, Choice, QMatrix
from accounts.models import *
from .forms import ExerciseForm

from django.db.models import Count, Q
from django.db import transaction
import csv
from datetime import datetime
#研究者身份判断
def is_researcher(user):
    return user.user_type == 'researcher'



#研究者面板
@login_required
@user_passes_test(is_researcher)
def researcher_dashboard(request):
    subjects = Subject.objects.all()
    total_exercises = Exercise.objects.filter(creator=request.user).count()
    total_knowledge_points = KnowledgePoint.objects.count()

    return render(request, 'researcher/researcher_dashboard.html', {
        'subjects': subjects,
        'total_exercises': total_exercises,
        'total_knowledge_points': total_knowledge_points,
    })


    return response