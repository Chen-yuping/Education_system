# Fix NoReverseMatch Error on Server

## Problem
The server is throwing: `NoReverseMatch: Reverse for 'student_course_management' not found`

However, the URL pattern IS defined in `learning/urls.py` and works locally.

## Root Cause
This is a deployment/caching issue. The server is using outdated code or cached Python bytecode.

## Solution Steps

### Step 1: Clear Python Cache
SSH into the server and run:

```bash
# Navigate to project directory
cd /www/wwwroot/aikgedu.com.cn/Education_system

# Remove all Python cache files
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete

# Clear Django cache (if using cache backend)
python3.6 manage.py clear_cache 2>/dev/null || true
```

### Step 2: Verify Latest Code is Deployed
Ensure the latest `learning/urls.py` is on the server:

```bash
# Check if student_course_management is in the file
grep -n "student_course_management" /www/wwwroot/aikgedu.com.cn/Education_system/learning/urls.py
```

Expected output:
```
6:    path('student/course-management/', views_student.student_course_management, name='student_course_management'),#课程管理
```

If NOT found, you need to redeploy the code.

### Step 3: Restart Django Application
Restart the Django application server:

```bash
# If using systemd
sudo systemctl restart aikgedu

# If using supervisor
sudo supervisorctl restart aikgedu

# If using gunicorn directly
pkill -f gunicorn
# Then restart gunicorn
```

### Step 4: Verify Fix
Test the URL in browser:
```
http://aikgedu.com.cn/learning/student/course-management/
```

Should load without NoReverseMatch error.

## If Problem Persists

### Check 1: Verify URL Pattern Syntax
```bash
python3.6 manage.py check
```

Should show no errors.

### Check 2: Test URL Reverse in Django Shell
```bash
python3.6 manage.py shell
>>> from django.urls import reverse
>>> reverse('student_course_management')
'/learning/student/course-management/'
```

Should return the URL without error.

### Check 3: Check for Duplicate URL Names
```bash
grep -r "name='student_course_management'" /www/wwwroot/aikgedu.com.cn/Education_system/
```

Should only appear once in `learning/urls.py`.

### Check 4: Verify View Exists
```bash
python3.6 manage.py shell
>>> from learning.views_student import student_course_management
>>> student_course_management
<function student_course_management at 0x...>
```

Should import without error.

## Prevention for Future Deployments

1. **Always clear cache after deployment:**
   ```bash
   find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
   find . -type f -name "*.pyc" -delete
   ```

2. **Restart application after deployment:**
   ```bash
   sudo systemctl restart aikgedu
   ```

3. **Run Django checks:**
   ```bash
   python3.6 manage.py check
   ```

4. **Test critical URLs after deployment:**
   - Dashboard: `/learning/student/dashboard/`
   - Course Management: `/learning/student/course-management/`
   - My Subjects: `/learning/student/my-subjects/`
