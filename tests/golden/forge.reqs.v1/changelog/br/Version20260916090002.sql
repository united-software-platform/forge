--liquibase formatted sql

--changeset model-gen:BR.f2.retype labels:model-1.3.0
--comment: тип поля value: text -> int
ALTER TABLE br_revision ALTER COLUMN value TYPE integer USING value::integer;
--rollback ALTER TABLE br_revision ALTER COLUMN value TYPE text USING value::text;
