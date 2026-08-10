-- Urban Renewal Management System - MariaDB schema
--
-- Intentionally has no CREATE DATABASE / USE statement: the target database is selected
-- by the caller, not hardcoded here. That keeps this file safe to apply against any
-- database name - the local docker-entrypoint-initdb.d flow picks it up via
-- MARIADB_DATABASE, and it can also be applied to a differently-named database on a
-- shared MariaDB instance (e.g. `mysql -u... -p... some_db_name < schema.sql`) without
-- risk of it creating/touching a database with a different name than intended.

SET NAMES utf8mb4;

-- 1. users
CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    role ENUM('admin','staff','public') NOT NULL DEFAULT 'staff',
    email VARCHAR(255),
    phone VARCHAR(30),
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    last_login_at DATETIME NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. projects
CREATE TABLE projects (
    id INT AUTO_INCREMENT PRIMARY KEY,
    project_code VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    address VARCHAR(255),
    district VARCHAR(100),
    status ENUM('active','closed','suspended') NOT NULL DEFAULT 'active',
    current_stage TINYINT NOT NULL DEFAULT 0,
    is_force_closed TINYINT(1) NOT NULL DEFAULT 0,
    description TEXT,
    created_by INT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_projects_created_by FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. project_members
CREATE TABLE project_members (
    id INT AUTO_INCREMENT PRIMARY KEY,
    project_id INT NOT NULL,
    user_id INT NOT NULL,
    role_in_project VARCHAR(50) NOT NULL DEFAULT 'staff',
    assigned_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_project_member (project_id, user_id),
    CONSTRAINT fk_pm_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_pm_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 4. sop_stages
CREATE TABLE sop_stages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    project_id INT NOT NULL UNIQUE,
    stage_data JSON NOT NULL,
    current_stage TINYINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_sop_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 5. landowners
CREATE TABLE landowners (
    id INT AUTO_INCREMENT PRIMARY KEY,
    project_id INT NOT NULL,
    name VARCHAR(100) NOT NULL,
    id_number VARCHAR(20),
    phone VARCHAR(30),
    address VARCHAR(255),
    contact_status ENUM('not_contacted','contacted','declined','agreed') NOT NULL DEFAULT 'not_contacted',
    is_representative TINYINT(1) NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_landowners_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    INDEX idx_landowners_project (project_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 6. land_records (ownership share is DB-computed via GENERATED ALWAYS)
CREATE TABLE land_records (
    id INT AUTO_INCREMENT PRIMARY KEY,
    project_id INT NOT NULL,
    landowner_id INT NULL,
    parcel_number VARCHAR(100) NOT NULL,
    section VARCHAR(100),
    total_area_sqm DECIMAL(12,2) NOT NULL DEFAULT 0,
    ownership_numerator INT NOT NULL DEFAULT 1,
    ownership_denominator INT NOT NULL DEFAULT 1,
    owned_area_sqm DECIMAL(14,4) GENERATED ALWAYS AS (total_area_sqm * ownership_numerator / ownership_denominator) STORED,
    ownership_share_pct DECIMAL(9,6) GENERATED ALWAYS AS (ownership_numerator / ownership_denominator * 100) STORED,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_land_records_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_land_records_landowner FOREIGN KEY (landowner_id) REFERENCES landowners(id) ON DELETE SET NULL,
    CONSTRAINT chk_land_records_denominator CHECK (ownership_denominator > 0),
    INDEX idx_land_records_project (project_id),
    INDEX idx_land_records_landowner (landowner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 7. building_records (ownership share computed by application layer, not SQL-generated)
CREATE TABLE building_records (
    id INT AUTO_INCREMENT PRIMARY KEY,
    project_id INT NOT NULL,
    landowner_id INT NULL,
    land_record_id INT NULL,
    building_number VARCHAR(100),
    address VARCHAR(255),
    floor VARCHAR(20),
    structure_area_sqm DECIMAL(12,2) NOT NULL DEFAULT 0,
    auxiliary_area_sqm DECIMAL(12,2) NOT NULL DEFAULT 0,
    common_area_sqm DECIMAL(12,2) NOT NULL DEFAULT 0,
    total_area_sqm DECIMAL(12,2) NOT NULL DEFAULT 0,
    ownership_numerator INT NOT NULL DEFAULT 1,
    ownership_denominator INT NOT NULL DEFAULT 1,
    ownership_share_pct DECIMAL(9,6) NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_building_records_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_building_records_landowner FOREIGN KEY (landowner_id) REFERENCES landowners(id) ON DELETE SET NULL,
    CONSTRAINT fk_building_records_land FOREIGN KEY (land_record_id) REFERENCES land_records(id) ON DELETE SET NULL,
    INDEX idx_building_records_project (project_id),
    INDEX idx_building_records_landowner (landowner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 8. contact_logs
CREATE TABLE contact_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    project_id INT NOT NULL,
    landowner_id INT NOT NULL,
    contact_date DATETIME NOT NULL,
    contact_method ENUM('phone','visit','mail','email','briefing','other') NOT NULL DEFAULT 'phone',
    contact_result ENUM('no_answer','agreed','opposed','undecided','callback_needed') NOT NULL DEFAULT 'undecided',
    staff_id INT NULL,
    notes TEXT,
    next_follow_up_date DATE NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_contact_logs_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_contact_logs_landowner FOREIGN KEY (landowner_id) REFERENCES landowners(id) ON DELETE CASCADE,
    CONSTRAINT fk_contact_logs_staff FOREIGN KEY (staff_id) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_contact_logs_project (project_id),
    INDEX idx_contact_logs_landowner (landowner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 9. consent_records (one row per landowner per SOP consent round: stage 4 / 8 / 9)
CREATE TABLE consent_records (
    id INT AUTO_INCREMENT PRIMARY KEY,
    project_id INT NOT NULL,
    landowner_id INT NOT NULL,
    sop_stage TINYINT NOT NULL,
    consent_status ENUM('pending','agreed','opposed') NOT NULL DEFAULT 'pending',
    recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    recorded_by INT NULL,
    notes TEXT,
    UNIQUE KEY uq_consent_landowner_stage (landowner_id, sop_stage),
    CONSTRAINT fk_consent_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_consent_landowner FOREIGN KEY (landowner_id) REFERENCES landowners(id) ON DELETE CASCADE,
    CONSTRAINT fk_consent_recorded_by FOREIGN KEY (recorded_by) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_consent_project_stage (project_id, sop_stage)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 10. documents
CREATE TABLE documents (
    id INT AUTO_INCREMENT PRIMARY KEY,
    project_id INT NOT NULL,
    landowner_id INT NULL,
    doc_type ENUM('property_register','consent_form','briefing_material','contract','photo','other') NOT NULL DEFAULT 'other',
    file_name VARCHAR(255) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    file_size_bytes BIGINT NOT NULL DEFAULT 0,
    mime_type VARCHAR(100),
    uploaded_by INT NULL,
    uploaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    description TEXT,
    CONSTRAINT fk_documents_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_documents_landowner FOREIGN KEY (landowner_id) REFERENCES landowners(id) ON DELETE SET NULL,
    CONSTRAINT fk_documents_uploaded_by FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_documents_project (project_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 11. expense_categories
CREATE TABLE expense_categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 12. expenses
CREATE TABLE expenses (
    id INT AUTO_INCREMENT PRIMARY KEY,
    project_id INT NOT NULL,
    category_id INT NULL,
    amount DECIMAL(12,2) NOT NULL,
    expense_date DATE NOT NULL,
    description VARCHAR(255),
    vendor VARCHAR(255),
    receipt_document_id INT NULL,
    created_by INT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_expenses_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_expenses_category FOREIGN KEY (category_id) REFERENCES expense_categories(id) ON DELETE SET NULL,
    CONSTRAINT fk_expenses_receipt FOREIGN KEY (receipt_document_id) REFERENCES documents(id) ON DELETE SET NULL,
    CONSTRAINT fk_expenses_created_by FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_expenses_project (project_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 13. ocr_jobs
CREATE TABLE ocr_jobs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    project_id INT NOT NULL,
    document_id INT NOT NULL,
    status ENUM('pending','processing','completed','failed') NOT NULL DEFAULT 'pending',
    job_type VARCHAR(50) NOT NULL DEFAULT 'land_record',
    error_message TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at DATETIME NULL,
    completed_at DATETIME NULL,
    CONSTRAINT fk_ocr_jobs_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_ocr_jobs_document FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
    INDEX idx_ocr_jobs_project (project_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 14. ocr_match_results
CREATE TABLE ocr_match_results (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ocr_job_id INT NOT NULL,
    extracted_name VARCHAR(100),
    extracted_id_number VARCHAR(20),
    extracted_parcel_number VARCHAR(100),
    raw_text TEXT,
    matched_landowner_id INT NULL,
    confidence_score DECIMAL(5,4),
    review_status ENUM('unreviewed','confirmed','rejected') NOT NULL DEFAULT 'unreviewed',
    reviewed_by INT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_ocr_match_job FOREIGN KEY (ocr_job_id) REFERENCES ocr_jobs(id) ON DELETE CASCADE,
    CONSTRAINT fk_ocr_match_landowner FOREIGN KEY (matched_landowner_id) REFERENCES landowners(id) ON DELETE SET NULL,
    CONSTRAINT fk_ocr_match_reviewed_by FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_ocr_match_job (ocr_job_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
