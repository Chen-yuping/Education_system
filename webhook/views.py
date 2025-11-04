import subprocess
import os
import json
import threading
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST


@csrf_exempt
@require_POST
def github_webhook(request):
    log_file = "/www/wwwroot/aikgedu.com.cn/Education_system/webhook_debug.log"

    try:
        with open(log_file, 'a') as f:
            f.write("\n" + "=" * 50 + "\n")
            f.write("🆕 收到GitHub Webhook请求\n")

        payload = json.loads(request.body.decode('utf-8'))
        ref = payload.get('ref', '')
        event = request.headers.get('X-GitHub-Event', '')

        with open(log_file, 'a') as f:
            f.write(f"事件: {event}, 分支: {ref}\n")

        # 只处理main分支的push事件
        if event == 'push' and ref == 'refs/heads/main':
            # 立即返回响应，避免超时
            with open(log_file, 'a') as f:
                f.write("✅ 立即返回202响应，开始后台部署\n")

            # 在后台线程中执行部署
            deploy_thread = threading.Thread(target=execute_deployment)
            deploy_thread.daemon = True
            deploy_thread.start()

            return JsonResponse({
                'status': 'accepted',
                'message': '部署任务已开始执行'
            }, status=202)  # 202 Accepted

        else:
            return JsonResponse({
                'status': 'ignored',
                'message': f'忽略事件: {event}'
            })

    except Exception as e:
        with open(log_file, 'a') as f:
            f.write(f"💥 Webhook处理异常: {str(e)}\n")
        return JsonResponse({
            'status': 'error',
            'message': f'服务器内部错误: {str(e)}'
        }, status=500)


def execute_deployment():
    """在后台执行部署任务"""
    log_file = "/www/wwwroot/aikgedu.com.cn/Education_system/webhook_debug.log"
    deploy_script = "/www/wwwroot/aikgedu.com.cn/Education_system/deploy.sh"
    project_dir = os.path.dirname(deploy_script)

    try:
        with open(log_file, 'a') as f:
            f.write("🚀 开始后台部署任务\n")

        # 执行部署脚本
        process = subprocess.Popen(
            ['/bin/bash', deploy_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=project_dir
        )

        stdout, stderr = process.communicate()
        returncode = process.returncode

        # 解码输出
        stdout_str = stdout.decode('utf-8') if stdout else ""
        stderr_str = stderr.decode('utf-8') if stderr else ""

        with open(log_file, 'a') as f:
            f.write(f"后台部署完成，返回码: {returncode}\n")
            if stdout_str:
                f.write(f"输出: {stdout_str[-300:]}\n")  # 只记录最后300字符
            if stderr_str:
                f.write(f"错误: {stderr_str[-300:]}\n")
            f.write("✅ 后台部署任务结束\n")

    except Exception as e:
        with open(log_file, 'a') as f:
            f.write(f"💥 后台部署异常: {str(e)}\n")