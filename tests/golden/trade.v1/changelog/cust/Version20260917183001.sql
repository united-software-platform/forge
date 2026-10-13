--liquibase formatted sql

--changeset model-gen:CUST.f4.add labels:model-1.2.0
--comment: добавлено поле phone
ALTER TABLE cust_revision ADD COLUMN phone text;
--rollback ALTER TABLE cust_revision DROP COLUMN phone;
