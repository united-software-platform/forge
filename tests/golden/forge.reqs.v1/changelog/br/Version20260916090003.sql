--liquibase formatted sql

--changeset model-gen:BR.f4.rename labels:model-1.3.0
--comment: origin -> provenance
ALTER TABLE br_revision RENAME COLUMN origin TO provenance;
--rollback ALTER TABLE br_revision RENAME COLUMN provenance TO origin;
