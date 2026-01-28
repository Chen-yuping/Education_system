# 部署自动化设置指南

## 问题

每次上传代码修改到服务器后，都需要手动运行这些命令：

```bash
cd /www/wwwroot/aikgedu.com.cn/Education_system
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete
pkill -f "gunicorn.*edu_system.wsgi"
sleep 2
/usr/bin/python3.6 /usr/local/bin/gunicorn --workers 3 --bind unix:/www/wwwroot/aikgedu.com.cn/Education_system/Education_system.sock edu_system.wsgi:application &
```

这很麻烦！

## 解决方案

### 推荐方案：使用Systemd服务 + 快速部署脚本

#### 第一步：在服务器上安装Systemd服务（一次性）

```bash
# 1. SSH到服务器
ssh root@aikgedu.com.cn

# 2. 复制服务文件
cp /www/wwwroot/aikgedu.com.cn/Education_system/aikgedu.service /etc/systemd/system/

# 3. 重新加载systemd
sudo systemctl daemon-reload

# 4. 启用服务（系统启动时自动启动）
sudo systemctl enable aikgedu

# 5. 启动服务
sudo systemctl start aikgedu

# 6. 检查状态
sudo systemctl status aikgedu
```

#### 第二步：以后每次部署只需运行一个命令

**方法A：使用快速部署脚本（推荐）**

```bash
# 在本地运行
bash quick-deploy.sh
```

这个脚本会自动：
1. 检查是否有未提交的更改
2. 推送代码到服务器
3. 清除服务器上的缓存
4. 重启应用

**方法B：手动部署**

```bash
# 1. 推送代码
git push origin main

# 2. SSH到服务器
ssh root@aikgedu.com.cn

# 3. 清除缓存并重启
cd /www/wwwroot/aikgedu.com.cn/Education_system && \
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true && \
find . -type f -name "*.pyc" -delete && \
sudo systemctl restart aikgedu
```

## 文件说明

### 1. `aikgedu.service`
Systemd服务文件，用于自动管理gunicorn进程。

**安装方法：**
```bash
sudo cp aikgedu.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable aikgedu
sudo systemctl start aikgedu
```

**常用命令：**
```bash
# 启动服务
sudo systemctl start aikgedu

# 停止服务
sudo systemctl stop aikgedu

# 重启服务
sudo systemctl restart aikgedu

# 查看状态
sudo systemctl status aikgedu

# 查看日志
sudo journalctl -u aikgedu -f
```

### 2. `deploy.sh`
完整的部署脚本，包括清除缓存、检查代码、重启应用等步骤。

**使用方法：**
```bash
bash deploy.sh
```

### 3. `quick-deploy.sh`
快速部署脚本，自动推送代码并部署到服务器。

**使用方法：**
```bash
bash quick-deploy.sh
```

**前提条件：**
- 已配置SSH密钥认证（无需输入密码）
- 已配置Git远程仓库

## 快速开始

### 第一次设置（5分钟）

```bash
# 1. 在服务器上安装systemd服务
ssh root@aikgedu.com.cn
sudo cp /www/wwwroot/aikgedu.com.cn/Education_system/aikgedu.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable aikgedu
sudo systemctl start aikgedu
exit

# 2. 在本地给脚本执行权限
chmod +x quick-deploy.sh
```

### 以后每次部署（10秒）

```bash
# 在本地运行
bash quick-deploy.sh
```

## 验证部署

部署完成后，验证应用是否正常运行：

```bash
# 1. 检查服务状态
ssh root@aikgedu.com.cn "sudo systemctl status aikgedu"

# 2. 查看日志
ssh root@aikgedu.com.cn "sudo journalctl -u aikgedu -n 50"

# 3. 访问网站
curl http://aikgedu.com.cn

# 4. 检查特定功能
curl http://aikgedu.com.cn/learning/teacher/upload/exercise/?subject_id=1
```

## 故障排除

### 问题1：部署后仍然报错

**解决方案：**
```bash
# 1. 检查服务状态
sudo systemctl status aikgedu

# 2. 查看详细日志
sudo journalctl -u aikgedu -n 100

# 3. 手动清除缓存
cd /www/wwwroot/aikgedu.com.cn/Education_system
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete

# 4. 重启服务
sudo systemctl restart aikgedu
```

### 问题2：快速部署脚本无法连接服务器

**解决方案：**
```bash
# 1. 检查SSH密钥
ssh-keygen -t rsa -b 4096

# 2. 复制公钥到服务器
ssh-copy-id root@aikgedu.com.cn

# 3. 测试连接
ssh root@aikgedu.com.cn "echo 'SSH连接成功'"
```

### 问题3：权限不足

**解决方案：**
```bash
# 确保脚本有执行权限
chmod +x deploy.sh
chmod +x quick-deploy.sh

# 确保systemd服务文件有正确权限
sudo chmod 644 /etc/systemd/system/aikgedu.service
```

## 监控应用

### 实时查看日志

```bash
# 查看最近50行日志
ssh root@aikgedu.com.cn "sudo journalctl -u aikgedu -n 50"

# 实时跟踪日志
ssh root@aikgedu.com.cn "sudo journalctl -u aikgedu -f"
```

### 检查应用状态

```bash
# 查看进程
ssh root@aikgedu.com.cn "ps aux | grep gunicorn"

# 查看端口占用
ssh root@aikgedu.com.cn "netstat -tlnp | grep gunicorn"
```

## 总结

| 任务 | 命令 | 时间 |
|------|------|------|
| 第一次设置 | 见"第一次设置"部分 | 5分钟 |
| 每次部署 | `bash quick-deploy.sh` | 10秒 |
| 查看日志 | `ssh root@aikgedu.com.cn "sudo journalctl -u aikgedu -f"` | 即时 |
| 重启应用 | `ssh root@aikgedu.com.cn "sudo systemctl restart aikgedu"` | 5秒 |

## 下一步

1. ✅ 在服务器上安装systemd服务
2. ✅ 在本地给脚本执行权限
3. ✅ 配置SSH密钥认证
4. ✅ 测试快速部署脚本
5. ✅ 开始使用自动化部署！
