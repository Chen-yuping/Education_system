#!/bin/bash

# 自动部署脚本 - 用于服务器部署
# 使用方法: bash deploy.sh

PROJECT_PATH="/www/wwwroot/aikgedu.com.cn/Education_system"
GUNICORN_SOCK="$PROJECT_PATH/Education_system.sock"

echo "=========================================="
echo "开始部署 Education System"
echo "=========================================="

# 进入项目目录
cd $PROJECT_PATH || exit 1

echo ""
echo "[1/4] 清除Python缓存..."
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete
echo "✓ Python缓存已清除"

echo ""
echo "[2/4] 清除Django缓存..."
python3.6 manage.py clear_cache 2>/dev/null || true
echo "✓ Django缓存已清除"

echo ""
echo "[3/4] 运行Django检查..."
python3.6 manage.py check
if [ $? -ne 0 ]; then
    echo "✗ Django检查失败！"
    exit 1
fi
echo "✓ Django检查通过"

echo ""
echo "[4/4] 重启Gunicorn..."
# 杀死旧的gunicorn进程
pkill -f "gunicorn.*edu_system.wsgi"
sleep 2

# 启动新的gunicorn进程
/usr/bin/python3.6 /usr/local/bin/gunicorn \
    --workers 3 \
    --bind unix:$GUNICORN_SOCK \
    edu_system.wsgi:application &

sleep 2

# 检查gunicorn是否启动成功
if pgrep -f "gunicorn.*edu_system.wsgi" > /dev/null; then
    echo "✓ Gunicorn已启动"
else
    echo "✗ Gunicorn启动失败！"
    exit 1
fi

echo ""
echo "=========================================="
echo "✓ 部署完成！"
echo "=========================================="
echo ""
echo "访问地址: http://aikgedu.com.cn"
echo ""
