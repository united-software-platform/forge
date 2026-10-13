--liquibase formatted sql

--changeset model-gen:ORD.f5.rename labels:model-1.2.0
--comment: comment -> note
ALTER TABLE ord_revision RENAME COLUMN comment TO note;
--rollback ALTER TABLE ord_revision RENAME COLUMN note TO comment;
