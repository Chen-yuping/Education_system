# 服务器部署指南

## 问题说明

每次上传代码修改到服务器后，需要手动清除缓存并重启应用。这是因为：

1. **Python缓存** - `.pyc` 文件和 `__pycache__` 目录
2. **Django缓存** - Django的内部缓存
3. **Gunicorn进程** - 需要重新加载新代码

## 解决方案

### 方案1：使用自动部署脚本（推荐）

#### 步骤1：上传脚本到服务器

```bash
# 在本地运行，将脚本上传到服务器
scp deploy.sh root@aikgedu.com.cn:/www/wwwroot/aikgedu.com.cn/Education_system/
```

#### 步骤2：给脚本执行权限

```bash
ssh root@aikgedu.com.cn
chmod +x /www/wwwroot/aikgedu.com.cn/Education_system/deploy.sh
```

#### 步骤3：每次部署时运行

```bash
# 在服务器上运行
bash /www/wwwroot/aikgedu.com.cn/Education_system/deploy.sh
```

或者从本地运行：

```bash
# 在本地运行
ssh root@aikgedu.com.cn "bash /www/wwwroot/aikgedu.com.cn/Education_system/deploy.sh"
```

### 方案2：使用Systemd服务（最佳实践）

这样可以自动管理gunicorn，并在系统重启时自动启动。

#### 步骤1：安装systemd服务

```bash
# 在服务器上运行
sudo cp /www/wwwroot/aikgedu.com.cn/Education_system/aikgedu.service /etc/systemd/system/

# 重新加载systemd配置
sudo systemctl daemon-reload

# 启用服务（系统启动时自动启动）
sudo systemctl enable aikgedu

# 启动服务
sudo systemctl start aikgedu

# 检查服务状态
sudo systemctl status aikgedu
```

#### 步骤2：部署新代码后重启服务

```bash
# 清除缓存
cd /www/wwwroot/aikgedu.com.cn/Education_system
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete

# 重启服务
sudo systemctl restart aikgedu

# 检查状态
sudo systemctl status aikgedu
```

或者使用一个命令：

```bash
cd /www/wwwroot/aikgedu.com.cn/Education_system && \
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true && \
find . -type f -name "*.pyc" -delete && \
sudo systemctl restart aikgedu
```

### 方案3：使用Git钩子自动部署

如果使用Git管理代码，可以创建一个post-receive钩子自动部署。

#### 步骤1：在服务器上创建裸仓库

```bash
mkdir -p /var/repo/aikgedu.git
cd /var/repo/aikgedu.git
git init --bare
```

#### 步骤2：创建post-receive钩子

```bash
cat > /var/repo/aikgedu.git/hooks/post-receive << 'EOF'
#!/bin/bash

PROJECT_PATH="/www/wwwroot/aikgedu.com.cn/Education_system"

# 检出最新代码
git --work-tree=$PROJECT_PATH --git-dir=/var/repo/aikgedu.git checkout -f

# 进入项目目录
cd $PROJECT_PATH

# 清除缓存
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete

# 重启服务
systemctl restart aikgedu

echo "✓ 部署完成"
EOF

chmod +x /var/repo/aikgedu.git/hooks/post-receive
```

#### 步骤3：在本地添加远程仓库

```bash
git remote add server ssh://root@aikgedu.com.cn/var/repo/aikgedu.git
```

#### 步骤4：部署代码

```bash
git push server main
```

## 快速参考

### 最简单的方法（每次部署）

```bash
# 1. 上传代码到服务器（使用你的部署工具）

# 2. SSH到服务器
ssh root@aikgedu.com.cn

# 3. 运行部署脚本
bash /www/wwwroot/aikgedu.com.cn/Education_system/deploy.sh
```

### 使用Systemd（推荐）

```bash
# 一次性设置
sudo cp aikgedu.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable aikgedu
sudo systemctl start aikgedu

# 每次部署
cd /www/wwwroot/aikgedu.com.cn/Education_system
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete
sudo systemctl restart aikgedu
```

## 常见问题

### Q: 为什么每次都要清除缓存？

**A:** Python和Django都会缓存已加载的模块和配置。如果不清除缓存，新代码不会被加载。

### Q: 可以自动清除缓存吗？

**A:** 可以。使用部署脚本或systemd服务都可以自动处理。

### Q: 如何检查gunicorn是否正常运行？

**A:** 
```bash
# 查看进程
ps aux | grep gunicorn

# 查看日志
tail -f /tmp/gunicorn_error.log
tail -f /tmp/gunicorn_access.log

# 使用systemd
sudo systemctl status aikgedu
```

### Q: 如何查看应用是否正常工作？

**A:**
```bash
# 访问网站
curl http://aikgedu.com.cn

# 查看nginx日志
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log
```

## 推荐工作流

1. **本地开发** - 在本地测试所有功能
2. **提交代码** - 使用Git提交代码
3. **部署到服务器** - 使用部署脚本或Git钩子
4. **验证** - 访问网站验证功能是否正常

## 脚本文件

- `deploy.sh` - 自动部署脚本
- `aikgedu.service` - Systemd服务文件

## 下一步

建议使用方案2（Systemd服务），这样可以：
- ✅ 自动管理gunicorn进程
- ✅ 系统重启时自动启动
- ✅ 简化部署流程
- ✅ 更好的日志管理
