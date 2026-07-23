/**
 * frontend/js/api/task.js
 *
 * 任务相关 API 调用层。
 * 通过 window.AppTaskApi 暴露，供 index.html 的 Vue setup() 使用。
 *
 * 所有函数都是工厂模式——接收 (http, state, apiBase) 三个参数，
 * 不直接持有 Vue reactive 对象，由调用方注入。
 *
 * 使用示例（setup 内）：
 *   const taskApi = AppTaskApi.create(http, state, API_BASE);
 *   await taskApi.fetchRecentTasks();
 *   await taskApi.toggleTaskDetail(taskId);
 */

(function (global) {
    'use strict';

    /**
     * 创建任务 API 客户端。
     *
     * @param {object} http      AppHttp.create() 返回的客户端
     * @param {object} state     Vue setup 中的 reactive 引用（具名 .value 属性）
     * @param {string} apiBase   API 前缀
     * @returns {object}
     */
    function create(http, state, apiBase) {
        const { extractListData } = global.AppUtils;

        /**
         * 获取当前项目的最近任务列表（排除 superseded），并同步 ai_screen 任务状态。
         */
        async function fetchRecentTasks() {
            if (!state.currentProject.value) return;
            state.isLoadingTasks.value = true;
            try {
                const res = await http.request(
                    `${apiBase}/tasks/?project=${state.currentProject.value.id}`
                );
                if (!res.ok) return;
                const data = await res.json();
                // 过滤掉 superseded（被续传替代的旧任务），只取最近 10 条
                const tasks = extractListData(data).filter(t => t.status !== 'superseded');
                state.recentTasks.value = tasks.slice(0, 10);

                // 同步更新最新的 ai_screen 任务（排除 superseded）
                const aiTask = tasks.find(t => t.task_type === 'ai_screen');
                if (aiTask) {
                    state.latestAiScreenTask.value = aiTask;
                }

                // 断点续传场景：从 stagesData 中 ai_screen step 的 metadata 恢复进度数据
                // （Task 模型没有 metadata 字段，进度信息存于 step.metadata）
                const stage = state.stagesData.value.find(s => s.stage_key === 'SCREEN_1');
                const aiStep = stage?.steps.find(s => s.step_key === 'ai_screen');
                if (aiStep?.metadata && aiTask?.status === 'stopped') {
                    state.totalRefs.value = aiStep.metadata.total_refs || state.totalRefs.value;
                    state.processedCount.value = aiStep.metadata.processed_refs || 0;
                    state.screeningProgressValue.value = aiTask.progress_percentage || 0;
                }
            } catch (err) {
                console.error('获取任务列表失败', err);
            } finally {
                state.isLoadingTasks.value = false;
            }
        }

        /**
         * 切换任务详情展开/收起，并在首次展开时从 API 加载日志。
         * @param {number|string} taskId
         */
        async function toggleTaskDetail(taskId) {
            if (state.expandedTaskId.value === taskId) {
                state.expandedTaskId.value = null;
            } else {
                state.expandedTaskId.value = taskId;
                // 如果还没有缓存日志，则从 API 获取
                if (!state.taskLogs.value[taskId]) {
                    try {
                        const res = await http.request(
                            `${apiBase}/tasks/${taskId}/logs/`
                        );
                        if (res.ok) {
                            const data = await res.json();
                            state.taskLogs.value = {
                                ...state.taskLogs.value,
                                [taskId]: data,
                            };
                        }
                    } catch (err) {
                        console.error('获取日志失败', err);
                    }
                }
            }
        }

        /**
         * 从缓存的日志数据中提取任务日志显示内容。
         * @param {object} task
         * @returns {string}
         */
        function getLogDisplay(task) {
            const cachedLog = state.taskLogs.value[task.id];
            if (!cachedLog) return '加载中...';
            if (cachedLog.error) return `错误: ${cachedLog.error}`;
            return cachedLog.log_content || '暂无日志';
        }

        return { fetchRecentTasks, toggleTaskDetail, getLogDisplay };
    }

    // ── 导出 ──────────────────────────────────────────────────────────────

    global.AppTaskApi = { create };

})(window);
