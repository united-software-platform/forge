--liquibase formatted sql

--changeset model-gen:enum.req_status.ARCHIVED labels:model-1.3.0
--comment: добавлено значение ARCHIVED
ALTER TYPE req_status ADD VALUE IF NOT EXISTS 'ARCHIVED';
--rollback -- значение перечислимого типа PostgreSQL не удаляется
