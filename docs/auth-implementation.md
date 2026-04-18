# 认证系统实施方案

> **目标**：使用 Django + DRF 自带认证，无需额外开发
> **方案**：Session Authentication（前后端同域） + Token Authentication（备选）

---

## 一、为什么选择 Django 自带认证？

### 优势
1. ✅ **开箱即用**：Django 自带完整用户系统（User 模型、登录/注销视图）
2. ✅ **零额外开发**：无需引入第三方库（JWT/OAuth）
3. ✅ **安全可靠**：经过多年验证，安全性有保障
4. ✅ **适合当前架构**：前端 Vue + 后端 Django 同域部署

### Django 自带功能
- 用户注册/登录/注销
- 密码重置
- Session 管理
- CSRF 保护
- 权限和分组管理

---

## 二、实施步骤

### 第 1 步：配置 DRF 认证（5 分钟）

修改 `platform_backend/settings.py`，添加：

```python
# Django REST Framework 配置
REST_FRAMEWORK = {
    # 认证方式
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',  # Session 认证（推荐）
        'rest_framework.authentication.BasicAuthentication',    # HTTP Basic（调试用）
    ],
    
    # 默认权限：必须登录
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    
    # 分页配置
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
}

# 登录相关 URL
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/accounts/login/'
```

**解释**：
- `SessionAuthentication`：使用 Cookie + Session，前端无需额外处理 token
- `IsAuthenticated`：所有 API 默认要求登录（可单独放开特定接口）

---

### 第 2 步：创建认证 API（10 分钟）

创建 `core/auth_views.py`：

```python
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.views import APIView

@api_view(['POST'])
@permission_classes([AllowAny])  # 允许未登录访问
def register(request):
    """用户注册"""
    username = request.data.get('username')
    password = request.data.get('password')
    email = request.data.get('email', '')
    
    if not username or not password:
        return Response({"error": "用户名和密码不能为空"}, status=status.HTTP_400_BAD_REQUEST)
    
    if User.objects.filter(username=username).exists():
        return Response({"error": "用户名已存在"}, status=status.HTTP_400_BAD_REQUEST)
    
    # 创建用户
    user = User.objects.create_user(username=username, password=password, email=email)
    
    # 创建 Profile（自动触发 signal）
    # UserProfile 会在 post_save 信号中自动创建
    
    return Response({
        "message": "注册成功，请等待管理员审核",
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email
        }
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request):
    """用户登录"""
    username = request.data.get('username')
    password = request.data.get('password')
    
    user = authenticate(request, username=username, password=password)
    
    if user is not None:
        # 检查是否已审核通过
        if hasattr(user, 'profile') and not user.profile.is_approved:
            return Response({
                "error": "账号尚未通过审核，请联系管理员"
            }, status=status.HTTP_403_FORBIDDEN)
        
        login(request, user)
        return Response({
            "message": "登录成功",
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "is_superuser": user.is_superuser,
                "is_approved": user.profile.is_approved if hasattr(user, 'profile') else False
            }
        })
    else:
        return Response({"error": "用户名或密码错误"}, status=status.HTTP_401_UNAUTHORIZED)


@api_view(['POST'])
def logout_view(request):
    """用户注销"""
    logout(request)
    return Response({"message": "已注销"})


@api_view(['GET'])
def current_user(request):
    """获取当前登录用户信息"""
    user = request.user
    return Response({
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "is_superuser": user.is_superuser,
        "is_approved": user.profile.is_approved if hasattr(user, 'profile') else False,
        "role": user.profile.role if hasattr(user, 'profile') else 'researcher',
        "quota_projects": user.profile.quota_projects if hasattr(user, 'profile') else 10
    })


class CSRFTokenView(APIView):
    """获取 CSRF Token"""
    permission_classes = [AllowAny]
    
    @ensure_csrf_cookie
    def get(self, request):
        return Response({"message": "CSRF cookie set"})
```

---

### 第 3 步：添加 URL 路由（2 分钟）

修改 `platform_backend/urls.py`：

```python
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from core import auth_views

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # 认证 API
    path('api/auth/register/', auth_views.register, name='register'),
    path('api/auth/login/', auth_views.login_view, name='login'),
    path('api/auth/logout/', auth_views.logout_view, name='logout'),
    path('api/auth/me/', auth_views.current_user, name='current_user'),
    path('api/auth/csrf/', auth_views.CSRFTokenView.as_view(), name='csrf'),
    
    # 业务 API
    path('api/', include('core.urls')),
    
    # 前端页面
    path('', include('core.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
```

---

### 第 4 步：前端集成（15 分钟）

修改 `frontend/index.html`，添加登录逻辑：

```javascript
const { createApp, ref, onMounted, computed } = Vue;
const API_BASE = '/api';

createApp({
    setup() {
        const currentUser = ref(null);
        const showLoginModal = ref(false);
        const loginForm = ref({ username: '', password: '' });
        const registerForm = ref({ username: '', password: '', email: '' });
        const showRegisterModal = ref(false);
        
        // 获取 CSRF Token
        const getCSRFToken = () => {
            return document.cookie.split('; ')
                .find(row => row.startsWith('csrftoken='))
                ?.split('=')[1];
        };
        
        // 获取当前用户信息
        const fetchCurrentUser = async () => {
            try {
                const res = await fetch(`${API_BASE}/auth/me/`, {
                    credentials: 'include'  // 携带 Cookie
                });
                
                if (res.ok) {
                    currentUser.value = await res.json();
                } else {
                    // 未登录，显示登录框
                    showLoginModal.value = true;
                }
            } catch (err) {
                console.error('获取用户信息失败', err);
                showLoginModal.value = true;
            }
        };
        
        // 登录
        const login = async () => {
            try {
                const res = await fetch(`${API_BASE}/auth/login/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCSRFToken()
                    },
                    body: JSON.stringify(loginForm.value),
                    credentials: 'include'
                });
                
                const data = await res.json();
                
                if (res.ok) {
                    currentUser.value = data.user;
                    showLoginModal.value = false;
                    alert('登录成功！');
                    location.reload();  // 刷新页面
                } else {
                    alert(data.error || '登录失败');
                }
            } catch (err) {
                alert(`登录出错: ${err.message}`);
            }
        };
        
        // 注册
        const register = async () => {
            try {
                const res = await fetch(`${API_BASE}/auth/register/`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCSRFToken()
                    },
                    body: JSON.stringify(registerForm.value),
                    credentials: 'include'
                });
                
                const data = await res.json();
                
                if (res.ok) {
                    alert(data.message);
                    showRegisterModal.value = false;
                    showLoginModal.value = true;
                } else {
                    alert(data.error || '注册失败');
                }
            } catch (err) {
                alert(`注册出错: ${err.message}`);
            }
        };
        
        // 注销
        const logout = async () => {
            if (!confirm('确定要退出登录吗？')) return;
            
            try {
                await fetch(`${API_BASE}/auth/logout/`, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': getCSRFToken() },
                    credentials: 'include'
                });
                
                currentUser.value = null;
                location.reload();
            } catch (err) {
                alert(`注销出错: ${err.message}`);
            }
        };
        
        // 初始化 CSRF Token
        const initCSRF = async () => {
            await fetch(`${API_BASE}/auth/csrf/`, {
                credentials: 'include'
            });
        };
        
        onMounted(async () => {
            await initCSRF();
            await fetchCurrentUser();
        });
        
        return {
            currentUser,
            showLoginModal,
            loginForm,
            login,
            logout,
            showRegisterModal,
            registerForm,
            register
        };
    }
}).mount('#app');
```

**登录框 HTML**（在 `#app` 内添加）：

```html
<!-- 登录框 -->
<div v-if="showLoginModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
    <div class="bg-white rounded-2xl w-full max-w-md p-8">
        <h2 class="text-2xl font-bold mb-6">用户登录</h2>
        <div class="space-y-4">
            <input v-model="loginForm.username" type="text" placeholder="用户名" 
                   class="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500">
            <input v-model="loginForm.password" type="password" placeholder="密码" 
                   class="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500"
                   @keyup.enter="login">
        </div>
        <div class="mt-6 flex space-x-3">
            <button @click="login" class="flex-1 bg-blue-600 text-white py-2 rounded-lg hover:bg-blue-700">
                登录
            </button>
        </div>
        <div class="mt-4 text-center">
            <button @click="showRegisterModal = true; showLoginModal = false" 
                    class="text-blue-600 hover:underline text-sm">
                还没有账号？立即注册
            </button>
        </div>
    </div>
</div>

<!-- 注册框 -->
<div v-if="showRegisterModal" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
    <div class="bg-white rounded-2xl w-full max-w-md p-8">
        <h2 class="text-2xl font-bold mb-6">用户注册</h2>
        <div class="space-y-4">
            <input v-model="registerForm.username" type="text" placeholder="用户名" 
                   class="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500">
            <input v-model="registerForm.email" type="email" placeholder="邮箱（可选）" 
                   class="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500">
            <input v-model="registerForm.password" type="password" placeholder="密码" 
                   class="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500">
        </div>
        <div class="mt-6 flex space-x-3">
            <button @click="showRegisterModal = false; showLoginModal = true" 
                    class="flex-1 border py-2 rounded-lg hover:bg-gray-50">
                取消
            </button>
            <button @click="register" class="flex-1 bg-blue-600 text-white py-2 rounded-lg hover:bg-blue-700">
                注册
            </button>
        </div>
    </div>
</div>

<!-- Header 右上角显示用户信息 -->
<header class="...">
    <div class="flex items-center space-x-4">
        <span v-if="currentUser" class="text-sm text-gray-600">
            欢迎，{{ currentUser.username }}
        </span>
        <button v-if="currentUser" @click="logout" 
                class="text-sm text-gray-600 hover:text-red-600">
            退出登录
        </button>
    </div>
</header>
```

---

### 第 5 步：创建超级管理员（首次部署）

```bash
# 服务器上执行
python manage.py createsuperuser

# 输入：
# Username: admin
# Email: admin@example.com
# Password: ********
```

然后通过 Django Admin 管理用户：`http://your-domain/admin/`

---

## 三、工作流程

### 1. 新用户注册
```
用户访问网站 → 点击"注册" → 填写表单 → 提交
  ↓
后端创建 User + UserProfile (is_approved=False)
  ↓
前端提示："注册成功，请等待管理员审核"
```

### 2. 管理员审核
```
管理员登录 Django Admin (/admin/)
  ↓
找到待审核用户（Users → UserProfiles 中筛选 is_approved=False）
  ↓
点击用户 → 勾选 "is_approved" → 保存
  ↓
（可选）调整 quota_projects / quota_storage_mb
  ↓
（可选）授予特定权限（通过后台或 API）
```

### 3. 用户登录
```
用户输入账号密码 → 后端验证
  ↓
检查 is_approved
  ↓
  ├─ True：登录成功，返回 Session Cookie
  └─ False：返回 403 "账号尚未通过审核"
```

### 4. 访问 API
```
前端发起请求（携带 Cookie）
  ↓
DRF SessionAuthentication 自动验证
  ↓
检查权限（如 @require_permission('project.create')）
  ↓
返回数据或拒绝访问
```

---

## 四、安全加固

### 1. HTTPS（生产环境必备）
```python
# settings.py
SECURE_SSL_REDIRECT = True          # 强制 HTTPS
SESSION_COOKIE_SECURE = True        # Cookie 仅 HTTPS 传输
CSRF_COOKIE_SECURE = True           # CSRF Cookie 仅 HTTPS
```

### 2. CSRF 保护
```python
# 已默认开启，前端需要：
headers: {
    'X-CSRFToken': getCSRFToken()   # 从 Cookie 读取
}
```

### 3. 限制登录尝试（可选）
安装 `django-axes`：
```bash
pip install django-axes
```

---

## 五、对比其他方案

| 方案 | 优点 | 缺点 | 是否推荐 |
|------|------|------|---------|
| **Session Auth（当前）** | 开箱即用、安全、无需前端存储 token | 需要同域部署 | ✅ **强烈推荐** |
| JWT Token | 无状态、支持跨域 | 需安装库、前端存储 token、注销复杂 | 🟡 未来扩展 |
| OAuth 2.0 | 支持第三方登录 | 配置复杂、依赖外部服务 | ❌ 当前不需要 |

---

## 六、开发清单

### 后端（30 分钟）
- [ ] 修改 `settings.py` 添加 `REST_FRAMEWORK` 配置
- [ ] 创建 `core/auth_views.py`
- [ ] 修改 `platform_backend/urls.py` 添加认证路由
- [ ] 创建 `UserProfile` 模型（已在设计文档中）
- [ ] 添加 `post_save` 信号自动创建 Profile

### 前端（20 分钟）
- [ ] 添加登录/注册弹窗 HTML
- [ ] 添加登录/注销 JS 逻辑
- [ ] 所有 API 请求携带 `credentials: 'include'`
- [ ] Header 显示当前用户

### 测试（10 分钟）
- [ ] 注册新用户 → 验证 is_approved=False
- [ ] 未审核用户登录 → 验证被拒绝
- [ ] 管理员审核通过 → 用户可登录
- [ ] 登录后访问 API → 验证权限检查
- [ ] 注销 → 验证 Session 清除

---

## 七、常见问题

**Q: 前后端分离部署怎么办？**  
A: 如果跨域，改用 Token Authentication（JWT），需额外开发。当前方案适合同域部署。

**Q: 忘记密码怎么办？**  
A: Django 自带密码重置功能，配置邮件后即可使用。或管理员通过 Admin 手动重置。

**Q: 可以集成微信/GitHub 登录吗？**  
A: 可以，使用 `django-allauth` 库，但需额外配置。当前先用账号密码登录。

**Q: Session 会过期吗？**  
A: 默认 2 周过期（可在 settings.py 配置 `SESSION_COOKIE_AGE`）。

---

**总结**：Django 自带认证足够用，无需引入额外库。只需配置 + 创建几个视图即可完成！
