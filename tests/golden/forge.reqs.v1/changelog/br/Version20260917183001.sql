--liquibase formatted sql

--changeset model-gen:BR.f6.drop labels:model-1.4.0
--comment: удалено поле owner, данные колонки owner будут удалены
ALTER TABLE br_revision DROP COLUMN owner;
--rollback ALTER TABLE br_revision ADD COLUMN owner text;
