--liquibase formatted sql

--changeset model-gen:BR.f6.add labels:model-1.3.0
--comment: добавлено поле owner
ALTER TABLE br_revision ADD COLUMN owner text;
--rollback ALTER TABLE br_revision DROP COLUMN owner;
