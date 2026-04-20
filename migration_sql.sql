-- ============================================
-- 数据库迁移 SQL 脚本
-- 用途：在本地 MySQL 中创建旧版表结构
-- 执行前请确保已备份数据！
-- ============================================

USE data_extraction;

-- ============================================
-- 步骤 1: 备份新版 core_project 表
-- ============================================
DROP TABLE IF EXISTS `core_project_backup`;
CREATE TABLE `core_project_backup` LIKE `core_project`;
INSERT INTO `core_project_backup` SELECT * FROM `core_project`;

-- 验证备份
SELECT COUNT(*) AS backup_count FROM `core_project_backup`;

-- ============================================
-- 步骤 2: 删除依赖旧 core_project 的表（如果存在）
-- ============================================
-- 注意：这会删除所有依赖数据！请提前备份！
SET FOREIGN_KEY_CHECKS = 0;
DROP TABLE IF EXISTS `core_extractiontask`;
DROP TABLE IF EXISTS `core_stage`;
DROP TABLE IF EXISTS `core_stagedata`;
DROP TABLE IF EXISTS `core_document`;
DROP TABLE IF EXISTS `core_project`;
SET FOREIGN_KEY_CHECKS = 1;

-- ============================================
-- 步骤 3: 创建旧版 core_project 表
-- ============================================
CREATE TABLE `core_project` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `name` varchar(255) NOT NULL,
  `description` longtext,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  `creator_id` int NOT NULL,
  PRIMARY KEY (`id`),
  KEY `core_project_creator_id_fk` (`creator_id`),
  CONSTRAINT `core_project_creator_id_fk` FOREIGN KEY (`creator_id`) REFERENCES `auth_user` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ============================================
-- 步骤 4: 创建 core_stage 表
-- ============================================
CREATE TABLE `core_stage` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `project_id` bigint NOT NULL,
  `stage_type` varchar(20) NOT NULL,
  `status` varchar(20) NOT NULL DEFAULT 'PENDING',
  `metadata` json NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `core_stage_project_id_stage_type_uniq` (`project_id`, `stage_type`),
  KEY `core_stage_project_id_fk` (`project_id`),
  CONSTRAINT `core_stage_project_id_fk` FOREIGN KEY (`project_id`) REFERENCES `core_project` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ============================================
-- 步骤 5: 创建 core_stagedata 表
-- ============================================
CREATE TABLE `core_stagedata` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `stage_id` bigint NOT NULL,
  `file` varchar(100) NOT NULL,
  `filename` varchar(255) NOT NULL,
  `data_type` varchar(10) NOT NULL DEFAULT 'INPUT',
  `description` longtext,
  `uploaded_at` datetime(6) NOT NULL,
  `source` varchar(50) NOT NULL DEFAULT 'UPLOAD',
  PRIMARY KEY (`id`),
  KEY `core_stagedata_stage_id_fk` (`stage_id`),
  CONSTRAINT `core_stagedata_stage_id_fk` FOREIGN KEY (`stage_id`) REFERENCES `core_stage` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ============================================
-- 步骤 6: 创建 core_document 表（向后兼容）
-- ============================================
CREATE TABLE `core_document` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `project_id` bigint NOT NULL,
  `file` varchar(100) NOT NULL,
  `filename` varchar(255) NOT NULL,
  `uploaded_at` datetime(6) NOT NULL,
  `is_processed` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  KEY `core_document_project_id_fk` (`project_id`),
  CONSTRAINT `core_document_project_id_fk` FOREIGN KEY (`project_id`) REFERENCES `core_project` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ============================================
-- 步骤 7: 创建 core_extractiontask 表（含新增的 log_file 字段）
-- ============================================
CREATE TABLE `core_extractiontask` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `project_id` bigint NOT NULL,
  `celery_task_id` varchar(255) DEFAULT NULL,
  `status` varchar(20) NOT NULL DEFAULT 'PENDING',
  `result_excel` varchar(100) DEFAULT NULL,
  `logs` longtext,
  `log_file` varchar(500) DEFAULT NULL COMMENT '日志文件路径（方案二优化）',
  `created_at` datetime(6) NOT NULL,
  `completed_at` datetime(6) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `core_extractiontask_project_id_fk` (`project_id`),
  CONSTRAINT `core_extractiontask_project_id_fk` FOREIGN KEY (`project_id`) REFERENCES `core_project` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- ============================================
-- 步骤 8: 从备份迁移数据到新的 core_project（可选）
-- ============================================
-- 注意：字段映射需要手动调整，这里提供示例：
-- INSERT INTO `core_project` (id, name, description, created_at, updated_at, creator_id)
-- SELECT id, name, description, created_at, updated_at, owner_id 
-- FROM `core_project_backup`;

-- ============================================
-- 步骤 9: 验证表结构
-- ============================================
SHOW TABLES LIKE 'core_%';

-- 查看表结构
DESCRIBE core_project;
DESCRIBE core_stage;
DESCRIBE core_stagedata;
DESCRIBE core_extractiontask;
DESCRIBE core_document;

-- ============================================
-- 完成！
-- ============================================
-- 提示：
-- 1. 备份数据已保存在 core_project_backup 表
-- 2. 如需恢复，可以执行步骤 8 的数据迁移
-- 3. 执行完成后，请运行 Django 迁移确认：
--    python manage.py migrate --fake
-- ============================================
