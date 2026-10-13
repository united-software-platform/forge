--liquibase formatted sql

--changeset model-gen:FR.f3.require labels:model-1.3.0
--comment: добавлено поле due
ALTER TABLE fr_revision ADD CONSTRAINT fr_due_since_3
  CHECK (mm_version < 3 OR due IS NOT NULL) NOT VALID;
--rollback ALTER TABLE fr_revision DROP CONSTRAINT fr_due_since_3;
