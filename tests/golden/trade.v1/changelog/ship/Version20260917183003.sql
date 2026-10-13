--liquibase formatted sql

--changeset model-gen:SHIP.f2.drop labels:model-1.2.0
--comment: удалено поле tracking, данные колонки tracking будут удалены
ALTER TABLE ship_revision DROP COLUMN tracking;
--rollback ALTER TABLE ship_revision ADD COLUMN tracking text;
