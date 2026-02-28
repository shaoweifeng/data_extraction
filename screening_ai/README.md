# PDF医学病例分析工具

## 功能描述
本工具使用DeepSeek API对医学病例PDF文件进行智能分析，提取患者基本信息、诊疗过程和细胞因子检查数据。

**✨ 新功能：支持增量处理**
- 自动跟踪已处理的PDF文件，避免重复处理
- 智能识别新增PDF文件，只处理未处理的文件
- 提供强制重新处理选项，灵活应对不同需求
- 实时显示处理状态和进度

## 文件结构
```
├── 1.py                    # 主程序文件
├── config.py              # API配置文件
├── requirements.txt       # 依赖包列表
├── processed_files.json   # 处理记录文件（自动生成）
├── datasets/             # PDF文件存放目录
├── prompts/              # 提示词文件目录
│   ├── prompt1.txt       # 患者基本信息提取
│   ├── prompt2.txt       # irAE事件信息提取
│   └── prompt3.txt       # 细胞因子检查提取
└── results/              # 分析结果输出目录
    └── [PDF文件名]/      # 每个PDF文件对应一个子目录
```

## 环境准备

### 创建虚拟环境
推荐使用虚拟环境来管理项目依赖，避免与系统Python环境冲突：

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate
```

### 安装依赖
```bash
pip install -r requirements.txt
```

## 使用方法

### 基本使用
1. 确保PDF文件放在 `datasets/` 目录下
2. 确保 `config.py` 中配置了正确的DeepSeek API密钥
3. 运行程序：
```bash
python 1.py
```

### 处理选项
程序运行后会显示所有PDF文件的处理状态，并提供以下选项：

**选项1：只处理新增的PDF文件（推荐）**
- 自动跳过已处理的文件
- 只处理新增或未处理的PDF文件
- 节省时间和API调用次数

**选项2：强制重新处理所有PDF文件**
- 重新处理所有PDF文件
- 会覆盖现有的处理结果
- 需要用户确认操作

**选项3：只查看状态，不进行处理**
- 仅显示文件处理状态
- 不执行任何处理操作

### 处理状态说明
- ✓ 表示文件已处理（显示处理时间）
- ○ 表示文件未处理

## 输出结果
程序会在 `results/` 目录下为每个PDF文件创建对应的子目录，生成以下文件：
- `prompt1_result_时间戳.txt` - 患者基本信息分析结果
- `prompt2_result_时间戳.txt` - irAE事件分析结果  
- `prompt3_result_时间戳.txt` - 细胞因子检查分析结果
- `complete_analysis_时间戳.json` - 完整分析结果汇总

## 处理记录
程序会自动创建 `processed_files.json` 文件来记录处理状态：
```json
{
  "文件名.pdf": {
    "processed_time": "20240924_180003",
    "status": "completed"
  }
}
```

## 注意事项
- 确保网络连接正常，能够访问DeepSeek API
- PDF文件应为可提取文本的格式
- API调用可能需要一定时间，请耐心等待
- 首次运行会处理所有PDF文件，后续运行只处理新增文件
- 如需重新处理已处理的文件，请选择"强制重新处理"选项
- 处理记录文件 `processed_files.json` 请勿手动删除，以免影响增量处理功能

## 常见问题

### Q: 如何添加新的PDF文件？
A: 直接将新的PDF文件放入 `datasets/` 目录，程序会自动识别并处理新文件。

### Q: 如何重新处理某个文件？
A: 运行程序时选择"强制重新处理所有PDF文件"选项，或手动删除 `processed_files.json` 中对应文件的记录。

### Q: 处理失败的文件会被记录吗？
A: 只有成功处理的文件才会被记录到 `processed_files.json` 中，失败的文件下次运行时会重新尝试处理。