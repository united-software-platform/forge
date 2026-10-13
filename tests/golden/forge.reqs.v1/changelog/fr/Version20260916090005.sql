--liquibase formatted sql

--changeset model-gen:FR.f3.add labels:model-1.3.0
--comment: добавлено поле due
ALTER TABLE fr_revision ADD COLUMN due timestamptz;
--rollback ALTER TABLE fr_revision DROP COLUMN due;
