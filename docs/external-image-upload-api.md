# 外部图片上传 API 使用说明

本文档供外部调用方接入图片上传接口。该接口只负责接收并私有保存图片，不提供前端页面或公开图片 URL。

## 1. 接口信息

```text
POST /api/external/images/
Content-Type: multipart/form-data
```

地址示例：

```text
本地：http://127.0.0.1:8000/api/external/images/
生产：http://39.97.32.181:8000/api/external/images/
```

接口支持以下图片格式：

- JPEG；
- PNG；
- WebP。

服务端会根据图片真实内容识别格式，不信任客户端声明的扩展名或 MIME 类型。通过校验后，图片会被重新编码并移除 EXIF 等元数据。

## 2. 鉴权

请求必须携带 Bearer API Key：

```http
Authorization: Bearer <API_KEY>
```

注意 `Bearer` 和 API Key 之间必须有一个空格。API Key 由接口维护方单独提供，禁止提交到代码仓库或写入前端代码。

## 3. 幂等请求标识

每次上传必须携带 UUID 格式的 `Idempotency-Key`：

```http
Idempotency-Key: 4d65891d-bb89-4e30-a3cd-7e23c6620825
```

使用规则：

- 每张新图片使用一个新的 UUID；
- 同一次上传发生超时或网络错误时，重试必须沿用原 UUID；
- 相同 `Idempotency-Key` 不会重复保存图片；
- 即使重试时发送了不同文件，只要 Key 相同，仍会返回第一次上传的记录，不会覆盖原图。

调用方可以使用以下方式生成 UUID：

```python
import uuid

idempotency_key = str(uuid.uuid4())
```

## 4. 请求字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `image` | 文件 | 是 | 单张 JPEG、PNG 或 WebP 图片 |
| `source` | 字符串 | 否 | 调用来源标识，最长 100 个字符，例如 `private-tool` |

默认限制：

- 单张图片最大 10 MiB；
- 单次请求体最大 12 MiB；
- 解码后最大 2500 万像素；
- 每次请求只接受一张图片。

## 5. cURL 调用示例

### 5.1 本地调用

```bash
curl -X POST "http://127.0.0.1:8000/api/external/images/" \
  -H "Authorization: Bearer 你的API密钥" \
  -H "Idempotency-Key: 4d65891d-bb89-4e30-a3cd-7e23c6620825" \
  -F "source=private-tool" \
  -F "image=@/Users/example/Desktop/test.png"
```

多行命令中，每行末尾的反斜杠 `\` 后面不能再有空格。也可以写成单行：

```bash
curl -X POST "http://127.0.0.1:8000/api/external/images/" -H "Authorization: Bearer 你的API密钥" -H "Idempotency-Key: 4d65891d-bb89-4e30-a3cd-7e23c6620825" -F "source=private-tool" -F "image=@/Users/example/Desktop/test.png"
```

### 5.2 生产环境调用

```bash
curl -X POST "https://你的域名/api/external/images/" \
  -H "Authorization: Bearer 你的API密钥" \
  -H "Idempotency-Key: $(uuidgen)" \
  -F "source=private-tool" \
  -F "image=@/path/to/test.png"
```

## 6. Python 调用示例

```python
import uuid

import requests


url = "http://127.0.0.1:8000/api/external/images/"
api_key = "由接口维护方提供的API密钥"

with open("/path/to/test.png", "rb") as image_file:
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
        data={"source": "private-tool"},
        files={"image": ("test.png", image_file, "image/png")},
        timeout=60,
    )

response.raise_for_status()
print(response.json())
```

如果因网络超时需要重试，应在第一次请求前生成并保存 `Idempotency-Key`，重试时继续使用同一个值，不要在每次重试中重新生成。

## 7. 成功响应

首次成功保存返回 HTTP `201 Created`：

```json
{
  "id": "b6a1e06c-0434-4735-9877-3ba72f5543b6",
  "path": "/root/data_extraction/private_media/external_images/2026/10/10/b6a1e06c0434473598773ba72f5543b6.png",
  "relative_path": "2026/10/10/b6a1e06c0434473598773ba72f5543b6.png",
  "mime_type": "image/png",
  "file_size": 18342,
  "width": 1280,
  "height": 720,
  "sha256": "图片内容的SHA-256摘要",
  "source": "private-tool",
  "created_at": "2026-10-10T14:30:00+08:00"
}
```

返回字段说明：

| 字段 | 说明 |
|---|---|
| `id` | 图片记录 UUID |
| `path` | 图片在服务器上的完整绝对路径 |
| `relative_path` | 相对于 `EXTERNAL_IMAGE_UPLOAD_ROOT` 的存储路径 |
| `mime_type` | 服务端识别并重新编码后的 MIME 类型 |
| `file_size` | 重新编码后的字节数 |
| `width` / `height` | 处理后的图片尺寸 |
| `sha256` | 重新编码后文件内容的 SHA-256 |
| `source` | 请求传入的来源标识 |
| `created_at` | 首次成功上传时间 |

使用相同 `Idempotency-Key` 重试时返回 HTTP `200 OK`，响应中的 `id`、`path` 和 `relative_path` 与第一次上传相同。

`path` 是服务器文件系统路径，不是可以通过浏览器直接访问的 URL。

## 8. 错误响应

错误响应统一包含：

```json
{
  "code": "ERROR_CODE",
  "error": "错误说明"
}
```

常见状态码：

| HTTP 状态码 | 常见错误码 | 说明 |
|---:|---|---|
| `400` | `INVALID_IDEMPOTENCY_KEY` | 缺少幂等键或不是合法 UUID |
| `400` | `IMAGE_REQUIRED` | 请求中缺少 `image` 文件 |
| `400` | `INVALID_SOURCE` | `source` 超过 100 个字符 |
| `401` | `INVALID_API_KEY` | 缺少 API Key、未使用 Bearer 格式或密钥错误 |
| `413` | `PAYLOAD_TOO_LARGE` | 请求体超过限制 |
| `422` | `INVALID_IMAGE` | 文件损坏、格式不支持、图片过大或像素数超限 |
| `503` | `IMAGE_UPLOAD_DISABLED` | 服务端未启用该接口 |

收到 `401` 时，首先检查请求头是否包含完整前缀：

```text
Authorization: Bearer <API_KEY>
```

## 9. 服务端部署配置

接口维护方需要在 `.env` 中配置：

```dotenv
EXTERNAL_IMAGE_UPLOAD_ENABLED=true
EXTERNAL_IMAGE_UPLOAD_ROOT=/root/data_extraction/private_media/external_images
EXTERNAL_IMAGE_UPLOAD_API_KEY=至少32个字符的随机密钥
EXTERNAL_IMAGE_UPLOAD_MAX_IMAGE_BYTES=10485760
EXTERNAL_IMAGE_UPLOAD_MAX_REQUEST_BYTES=12582912
EXTERNAL_IMAGE_UPLOAD_MAX_PIXELS=25000000
```

首次部署执行：

```bash
python manage.py migrate external_images
```

修改环境变量后需要重启 Django 服务。API Key 不应通过聊天记录、日志、截图或代码仓库传递；如果发生泄露，应立即更换并重启服务。
