--liquibase formatted sql

--changeset model-gen:ORD.f6.add labels:model-1.1.0
--comment: добавлено поле discount
ALTER TABLE ord_revision ADD COLUMN discount integer;
--rollback ALTER TABLE ord_revision DROP COLUMN discount;
