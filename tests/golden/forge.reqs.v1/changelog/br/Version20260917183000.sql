--liquibase formatted sql

--changeset model-gen:BR.f4.require labels:model-1.4.0
--comment: поле provenance стало обязательным начиная с 4
ALTER TABLE br_revision ADD CONSTRAINT br_provenance_since_4
  CHECK (mm_version < 4 OR provenance IS NOT NULL) NOT VALID;
--rollback ALTER TABLE br_revision DROP CONSTRAINT br_provenance_since_4;
