# 阶段一 · 认证改造与用户分级

> 依赖：无（可最先落地）
> 目标：注册即可用（免审核、自动建 Profile）；role 简化为 `admin/user`；管理员可封禁/解封用户；项目按角色分级可见。

---

## 一、现状分析（基于当前代码）

### 1. `core/models.py`
- `UserProfile.ROLE_CHOICES` 为 `[('admin','管理员'),('researcher','研究者'),('viewer','访客')]`，`role` 默认 `'researcher'`。
- 有 `is_approved`（默认 **False**）、`approved_at`、`approved_by` 审核字段。
- **无** `UserProfile` 自动创建信号——注册时不建 Profile。
- `ProjectQuerySet.for_user()`（第127行）：`is_superuser` 或有 `project.view_all` 权限 → 全部；否则 `filter(owner=user)`。

### 2. `core/api/auth_views.py`
- `register`（第13行）：仅 `create_user`，**不建 Profile**，返回「注册成功，请等待管理员审核」。
- `login_view`（第40行，第47行）：校验 `not user.profile.is_approved and not is_superuser` → 403「账号尚未通过审核」。

### 3. 问题
- 新用户注册后：① 没有 Profile；② `is_approved=False` 导致**无法登录**（除非管理员手动审核）。
- role 有 3 种，与目标（admin/user 两级）不符。
- 无封禁能力。

---

## 二、改造目标

1. 注册后自动建 `UserProfile(role='user', is_approved=True)`，**注册即可登录**。
2. role 收敛为 `admin` / `user`（保留旧值定义以兼容历史数据，迁移时归并 researcher/viewer → user）。
3. 新增 `is_banned` 显式封禁开关（默认 False），登录校验改为「被封禁则 403」。
4. 新增 `concurrency_limit`（默认 2，为阶段四预留档位字段）。
5. User 创建时通过 `post_save` 信号兜底自动建 Profile（防止遗漏）。
6. `for_user()` 分级：`is_superuser` 或 `role=='admin'` → 全部；否则只看自己的。
7. 管理员 `ban`/`unban` 接口。
8. 前端：`isAdmin` 计算属性、去掉「等待审核」提示、管理员菜单按权限显示。

---

## 三、后端改动清单

### 3.1 `core/models.py` — UserProfile 模型

```python
class UserProfile(models.Model):
    ROLE_CHOICES = [
        ('admin', '管理员'),
        ('user', '普通用户'),
        # 旧值保留以兼容历史迁移，不再新用
        ('researcher', '研究者'),
        ('viewer', '访客'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile', ...)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='user', ...)  # 默认改 user
    quota_projects = models.IntegerField(default=10, ...)
    quota_storage_mb = models.IntegerField(default=5120, ...)
    # 免审核后 is_approved 语义弱化，默认改 True；新增显式封禁字段
    is_approved = models.BooleanField(default=True, verbose_name="是否已审核")
    is_banned = models.BooleanField(default=False, verbose_name="是否被封禁")     # 新增
    concurrency_limit = models.IntegerField(default=2, verbose_name="并发档位")   # 新增(阶段四用)
    approved_at = ...
    approved_by = ...
    created_at = ...
    updated_at = ...

    @property
    def is_admin(self):
        return self.role == 'admin' or self.user.is_superuser
```

### 3.2 `core/models.py` — post_save 信号（兜底建 Profile）

在 models.py 末尾（或 `core/signals.py` 并在 apps.ready 里 import）：

```python
from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=User)
def ensure_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(
            user=instance,
            defaults={'role': 'user', 'is_approved': True},
        )
```

> 注意：superuser 由 `createsuperuser` 创建时也会触发，默认给 `role='user'`；需在初始化脚本或手动把管理员 role 置为 `admin`（或信号里判断 `instance.is_superuser` 时给 `admin`）。

### 3.3 `core/api/auth_views.py` — register / login

**register**：去掉「等待审核」，显式确保 Profile 存在（信号已兜底，这里可选二次确认）：

```python
user = User.objects.create_user(username=username, password=password, email=email)
# 信号已自动建 Profile；此处不再返回"等待审核"
return Response(
    {"message": "注册成功", "user": UserSerializer(user).data},
    status=status.HTTP_201_CREATED,
)
```

**login_view**：校验从 `is_approved` 改为 `is_banned`：

```python
if user is not None:
    if hasattr(user, 'profile') and user.profile.is_banned:
        return Response({"error": "账号已被封禁，请联系管理员"},
                        status=status.HTTP_403_FORBIDDEN)
    login(request, user)
    return Response({"message": "登录成功", "user": UserSerializer(user).data})
```

### 3.4 `core/models.py` — for_user 分级

```python
def for_user(self, user):
    if user.is_superuser:
        return self
    profile = getattr(user, 'profile', None)
    if profile and profile.role == 'admin':
        return self
    # 兼容旧 RBAC：保留 view_all 权限判断
    if UserPermission.objects.filter(user=user, permission__code='project.view_all').exists():
        return self
    return self.filter(owner=user)
```

### 3.5 `core/serializers.py` — 输出新字段

`UserProfileSerializer`（若无则在 `UserSerializer` 内联）增加输出：`role`、`is_banned`、`concurrency_limit`、`is_admin`。确保 `current_user` / login 返回的 user 数据里带 `profile.role`，供前端判断。

### 3.6 `core/api/user_views.py` — ban / unban

新增两个 action（管理员权限，复用现有 `@require_permission('user.approve')` 或新增 `user.ban`）：

```python
@action(detail=True, methods=['post'])
def ban(self, request, pk=None):
    profile = self.get_object().profile
    profile.is_banned = True
    profile.save(update_fields=['is_banned'])
    return Response({'message': '已封禁'})

@action(detail=True, methods=['post'])
def unban(self, request, pk=None):
    profile = self.get_object().profile
    profile.is_banned = False
    profile.save(update_fields=['is_banned'])
    return Response({'message': '已解封'})
```

> 需确认 `user_views.py` 的 ViewSet 结构与权限装饰器现状后再定最终写法。

### 3.7 数据迁移

1. `makemigrations`：新增 `is_banned`、`concurrency_limit` 字段，`role`/`is_approved` 默认值变更。
2. 手写**数据迁移**（`RunPython`）：
   - 把现有 `role in ('researcher','viewer')` 的记录归并为 `'user'`。
   - 把现有 `is_approved=False` 的历史正常用户批量置 `True`（避免老用户被锁）。
   - 为**没有 Profile 的历史 User** 补建 Profile（`get_or_create`）。
   - 指定初始管理员（如 superuser）`role='admin'`。
3. **迁移前先备份 MySQL**。

---

## 四、前端改动清单

### 4.1 `web/src/stores/auth.js`
- 增加 `isAdmin` 计算属性：`user.is_superuser || user.profile?.role === 'admin'`。
- 确保登录/获取当前用户后，`user.profile` 数据被正确存储。

### 4.2 注册页
- 去掉「注册成功，请等待管理员审核」文案，改为「注册成功，请登录」并可自动跳转登录/直接登录。

### 4.3 菜单与项目列表
- 管理员专属菜单项（如后续「用户管理」）按 `isAdmin` 显示。
- 项目列表页无需改动（后端 `for_user` 已分级），但可加提示「管理员查看全部项目 / 我的项目」。

---

## 五、改动文件汇总

| 文件 | 改动 |
|------|------|
| `core/models.py` | UserProfile 字段(role默认/is_banned/concurrency_limit/is_admin)、post_save 信号、for_user 分级 |
| `core/api/auth_views.py` | register 去审核、login 改 is_banned 校验 |
| `core/serializers.py` | 输出 role/is_banned/concurrency_limit/is_admin |
| `core/api/user_views.py` | ban / unban action |
| `core/migrations/xxxx_*.py` | 结构迁移 + 数据迁移(role归并/补Profile/管理员置admin) |
| `web/src/stores/auth.js` | isAdmin 计算属性 |
| 注册页组件 | 去掉等待审核提示 |

---

## 六、验证标准（可逐条勾验）

- [ ] 新用户注册后**立即可登录**，无需审核。
- [ ] 注册后自动生成 `UserProfile`，`role='user'`、`is_approved=True`、`is_banned=False`、`concurrency_limit=2`。
- [ ] 管理员（superuser 或 role=admin）登录后能看到**所有**项目。
- [ ] 普通用户登录后**只看到自己**创建的项目。
- [ ] 管理员对某用户 `ban` 后，该用户登录返回 **403**「账号已被封禁」；`unban` 后恢复。
- [ ] 数据迁移后：无 `researcher/viewer` 角色残留；历史用户均有 Profile；初始管理员 role=admin。
- [ ] 前端 `isAdmin` 正确，管理员菜单按角色显示。
- [ ] 现有 AI 筛选 / 项目主流程不受影响。

---

## 七、风险与注意

1. **superuser 信号冲突**：`createsuperuser` 会触发 post_save，需保证不会把管理员误设为 user（信号里判断 `is_superuser` 或迁移中修正）。
2. **迁移顺序**：先加字段（含默认值）再跑数据迁移，避免空值报错；**务必先备份**。
3. **旧 RBAC 兼容**：`for_user` 保留 `view_all` 权限判断，避免依赖旧权限的逻辑失效。
4. **序列化器嵌套**：确认 `UserSerializer` 是否已嵌套 profile；若无需补，否则前端拿不到 role。
5. **is_approved 语义**：免审核后该字段基本废弃，保留仅为兼容，封禁统一走 `is_banned`。
