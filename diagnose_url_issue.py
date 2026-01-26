#!/usr/bin/env python3.6
"""
Diagnostic script to identify NoReverseMatch issues
Run this on the server: python3.6 diagnose_url_issue.py
"""

import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'edu_system.settings')
sys.path.insert(0, '/www/wwwroot/aikgedu.com.cn/Education_system')

django.setup()

from django.urls import reverse, get_resolver
from django.urls.exceptions import NoReverseMatch

print("=" * 60)
print("Django URL Configuration Diagnostic")
print("=" * 60)

# Test 1: Check if URL pattern exists
print("\n[TEST 1] Checking if 'student_course_management' URL pattern exists...")
try:
    url = reverse('student_course_management')
    print(f"✓ SUCCESS: URL pattern found")
    print(f"  Reversed URL: {url}")
except NoReverseMatch as e:
    print(f"✗ FAILED: {e}")
    print("\n  This means the URL pattern is NOT registered in Django.")
    print("  Possible causes:")
    print("  1. learning/urls.py not deployed to server")
    print("  2. Django cache not cleared after deployment")
    print("  3. Application not restarted after deployment")

# Test 2: List all registered URL patterns
print("\n[TEST 2] Listing all registered URL patterns...")
resolver = get_resolver()
patterns = resolver.url_patterns

learning_patterns = [p for p in patterns if 'learning' in str(p.pattern)]
print(f"Found {len(learning_patterns)} learning-related patterns:")
for pattern in learning_patterns[:5]:
    print(f"  - {pattern.pattern}")
if len(learning_patterns) > 5:
    print(f"  ... and {len(learning_patterns) - 5} more")

# Test 3: Check if learning.urls is properly included
print("\n[TEST 3] Checking if learning.urls is included...")
try:
    from learning import urls as learning_urls
    print("✓ learning.urls module imported successfully")
    
    # Check if student_course_management is in the urlpatterns
    has_pattern = any('student_course_management' in str(p.name) for p in learning_urls.urlpatterns)
    if has_pattern:
        print("✓ 'student_course_management' pattern found in learning.urls")
    else:
        print("✗ 'student_course_management' pattern NOT found in learning.urls")
        print("  Available patterns in learning.urls:")
        for p in learning_urls.urlpatterns[:10]:
            print(f"    - {p.name}")
except Exception as e:
    print(f"✗ Error importing learning.urls: {e}")

# Test 4: Check if view exists
print("\n[TEST 4] Checking if student_course_management view exists...")
try:
    from learning.views_student import student_course_management
    print("✓ View imported successfully")
except ImportError as e:
    print(f"✗ Failed to import view: {e}")

# Test 5: Check Python cache
print("\n[TEST 5] Checking for Python cache files...")
import subprocess
result = subprocess.run(
    "find /www/wwwroot/aikgedu.com.cn/Education_system -name '*.pyc' | wc -l",
    shell=True,
    capture_output=True,
    text=True
)
pyc_count = int(result.stdout.strip())
if pyc_count > 0:
    print(f"⚠ WARNING: Found {pyc_count} .pyc cache files")
    print("  Run: find . -type f -name '*.pyc' -delete")
else:
    print("✓ No .pyc cache files found")

print("\n" + "=" * 60)
print("Diagnostic Complete")
print("=" * 60)
