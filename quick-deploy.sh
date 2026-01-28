#!/bin/bash

# 快速部署脚本 - 一键部署到服务器
# 使用方法: bash quick-deploy.sh

SERVER="root@aikgedu.com.cn"
PROJECT_PATH="/www/wwwroot/aikgedu.com.cn/Education_system"

echo "=========================================="
echo "快速部署到服务器"
echo "=========================================="
echo ""

# 检查是否有未提交的更改
if [ -n "$(git status --porcelain)" ]; then
    echo "⚠ 警告：有未提交的更改"
    echo "请先提交所有更改："
    echo "  git add ."
    echo "  git commit -m '你的提交信息'"
    exit 1
fi

echo "[1/3] 推送代码到服务器..."
git push origin main
if [ $? -ne 0 ]; then
    echo "✗ 推送失败"
    exit 1
fi
echo "✓ 代码已推送"

echo ""
echo "[2/3] 在服务器上清除缓存..."
ssh $SERVER "cd $PROJECT_PATH && \
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true && \
find . -type f -name "*.pyc" -delete && \
echo '✓ 缓存已清除'"

echo ""
echo "[3/3] 重启应用..."
ssh $SERVER "sudo systemctl restart aikgedu && sleep 2 && sudo systemctl status aikgedu"

echo ""
echo "=========================================="
echo "✓ 部署完成！"
echo "=========================================="
echo ""
echo "访问地址: http://aikgedu.com.cn"
echo ""
