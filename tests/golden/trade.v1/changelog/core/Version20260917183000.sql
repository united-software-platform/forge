--liquibase formatted sql

--changeset model-gen:enum.payment_method.CRYPTO labels:model-1.2.0
--comment: добавлено значение CRYPTO
ALTER TYPE payment_method ADD VALUE IF NOT EXISTS 'CRYPTO';
--rollback -- значение перечислимого типа PostgreSQL не удаляется
