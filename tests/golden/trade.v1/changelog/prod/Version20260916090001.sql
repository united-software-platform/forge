--liquibase formatted sql

--changeset model-gen:PROD.f4.require labels:model-1.1.0
--comment: поле active стало обязательным начиная с 1
ALTER TABLE prod_revision ADD CONSTRAINT prod_active_since_1
  CHECK (mm_version < 1 OR active IS NOT NULL) NOT VALID;
--rollback ALTER TABLE prod_revision DROP CONSTRAINT prod_active_since_1;
