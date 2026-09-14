export const valuePillars = [
  { icon: 'fas fa-diagram-project', label: '结构化研究流程' },
  { icon: 'fas fa-layer-group', label: '多模型交叉验证' },
  { icon: 'fas fa-user-check', label: '人工复核优先' },
  { icon: 'fas fa-clock-rotate-left', label: '操作过程留痕' },
]

export const featureCards = [
  {
    icon: 'fas fa-file-import',
    tone: 'blue',
    eyebrow: '准备',
    title: '文献导入与智能去重',
    description: '将文献资料导入项目，完成解析、重复项识别和结果检查，为后续筛选建立干净的数据基础。',
  },
  {
    icon: 'fas fa-list-check',
    tone: 'violet',
    eyebrow: '规则',
    title: '纳排标准结构化管理',
    description: '集中维护纳入与排除条件，并将标准直接传递给 AI 初筛，减少研究过程中规则漂移。',
  },
  {
    icon: 'fas fa-wand-magic-sparkles',
    tone: 'indigo',
    eyebrow: 'AI 初筛',
    title: '单模型与多模型筛选',
    description: '按项目选择模型执行批量初筛，保留每个模型的结论、排除理由与用量记录。',
  },
  {
    icon: 'fas fa-code-compare',
    tone: 'amber',
    eyebrow: '共识',
    title: '分歧识别与人工裁定',
    description: '多模型意见不一致时自动进入分歧队列，研究者可以逐篇查看依据并作出最终判断。',
  },
  {
    icon: 'fas fa-shield-halved',
    tone: 'emerald',
    eyebrow: '质量评价',
    title: '方法配置与 AI 辅助评价',
    description: '从初筛结果导入文献、上传全文、配置评价方法，再对 AI 结果进行人工确认。',
  },
  {
    icon: 'fas fa-file-export',
    tone: 'rose',
    eyebrow: '交付',
    title: '结果汇总与规范导出',
    description: '汇总纳入、排除、待定与分歧结果，输出可继续分析和归档的结构化文件与图表。',
  },
]

export const screeningSteps = [
  { number: '01', title: '导入解析', text: '解析文献文件并建立项目数据。' },
  { number: '02', title: '文献去重', text: '识别重复记录并保留处理依据。' },
  { number: '03', title: '设定标准', text: '维护明确的纳入与排除条件。' },
  { number: '04', title: '提取字段', text: '按研究需要定义附加信息字段。' },
  { number: '05', title: 'AI 初筛', text: '选择一个或多个模型批量判断。' },
  { number: '06', title: '人工审阅', text: '复核结论、理由与模型分歧。' },
  { number: '07', title: '结果导出', text: '按最终决定汇总并导出结果。' },
]

export const qualitySteps = [
  { icon: 'fas fa-arrow-right-to-bracket', title: '导入纳入文献', text: '从初筛结果建立质量评价文献集。' },
  { icon: 'fas fa-file-pdf', title: '补充研究全文', text: '上传 PDF，为逐项评价提供原文依据。' },
  { icon: 'fas fa-sliders', title: '配置评价方法', text: '选择方法并确认信号问题和评价设置。' },
  { icon: 'fas fa-microchip', title: 'AI 辅助评价', text: '批量生成逐项判断及其理由。' },
  { icon: 'fas fa-clipboard-check', title: '人工确认', text: '研究者审核并修订评价结果。' },
  { icon: 'fas fa-chart-simple', title: '图表与导出', text: '生成汇总图表并导出 Excel 结果。' },
]

export const trustCards = [
  {
    icon: 'fas fa-fingerprint',
    title: 'AI 结论与人工判断分开保存',
    description: '人工复核不会抹去 AI 原始判断，最终决定、覆写关系和理由都有独立记录。',
  },
  {
    icon: 'fas fa-route',
    title: '任务状态可以持续追踪',
    description: '解析、去重、初筛和评价均通过任务状态展示进度，支持必要的暂停、恢复和问题排查。',
  },
  {
    icon: 'fas fa-box-archive',
    title: '项目数据相互隔离',
    description: '文献、任务、结果和操作记录均归属于具体项目，普通用户只能访问自己的项目。',
  },
  {
    icon: 'fas fa-magnifying-glass-chart',
    title: '关键操作保留记录',
    description: '文件、标准、模型、Prompt 和任务操作形成时间线，便于还原研究过程与定位异常。',
  },
]

