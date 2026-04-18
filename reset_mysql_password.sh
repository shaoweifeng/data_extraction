#!/bin/bash

echo "🔧 开始重置 MySQL Root 密码..."

NEW_PASSWORD="123456"

# 1. 停止 MySQL 服务
echo "📌 步骤 1: 停止 MySQL 服务"
sudo /usr/local/mysql/support-files/mysql.server stop 2>/dev/null
sudo launchctl unload -w /Library/LaunchDaemons/com.oracle.oss.mysql.mysqld.plist 2>/dev/null
sleep 2

# 确认停止
if pgrep -x mysqld > /dev/null; then
    echo "❌ MySQL 未完全停止，强制终止..."
    sudo pkill -9 mysqld
    sleep 2
fi

echo "✅ MySQL 已停止"

# 2. 以安全模式启动
echo "📌 步骤 2: 以安全模式启动 MySQL"
sudo /usr/local/mysql/bin/mysqld_safe --skip-grant-tables --skip-networking > /tmp/mysql_safe.log 2>&1 &
echo "⏳ 等待 MySQL 启动..."
sleep 5

# 3. 重置密码
echo "📌 步骤 3: 重置 root 密码为 ${NEW_PASSWORD}"

# 关键：在 --skip-grant-tables 模式下必须先 FLUSH PRIVILEGES
mysql -uroot <<EOF
FLUSH PRIVILEGES;
ALTER USER 'root'@'localhost' IDENTIFIED BY '${NEW_PASSWORD}';
FLUSH PRIVILEGES;
EOF

# 如果上面失败，尝试旧语法（MySQL 5.7）
if [ $? -ne 0 ]; then
    echo "⚠️  尝试 MySQL 5.7 语法..."
    mysql -uroot <<EOF
FLUSH PRIVILEGES;
USE mysql;
UPDATE user SET authentication_string=PASSWORD('${NEW_PASSWORD}') WHERE User='root';
UPDATE user SET plugin='mysql_native_password' WHERE User='root';
FLUSH PRIVILEGES;
EOF
fi

echo "✅ 密码已重置"

# 4. 重启 MySQL（正常模式）
echo "📌 步骤 4: 重启 MySQL 正常模式"
sudo pkill mysqld
sleep 2

sudo /usr/local/mysql/support-files/mysql.server start
if [ $? -ne 0 ]; then
    # 尝试 launchctl
    sudo launchctl load -w /Library/LaunchDaemons/com.oracle.oss.mysql.mysqld.plist
fi

sleep 3

# 5. 验证登录
echo "📌 步骤 5: 验证登录"
if mysql -uroot -p${NEW_PASSWORD} -e "SELECT 'Login Success!' AS Status;" 2>/dev/null; then
    echo ""
    echo "🎉 成功！MySQL Root 密码已重置为: ${NEW_PASSWORD}"
    echo ""
    echo "现在可以使用以下命令登录："
    echo "  mysql -uroot -p${NEW_PASSWORD}"
    echo ""
else
    echo ""
    echo "❌ 自动验证失败，但密码可能已重置"
    echo "请手动尝试登录: mysql -uroot -p${NEW_PASSWORD}"
    echo ""
    echo "如果仍然失败，请检查日志:"
    echo "  tail -50 /usr/local/mysql/data/*.err"
    echo ""
fi
