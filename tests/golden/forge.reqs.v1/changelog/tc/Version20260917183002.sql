--liquibase formatted sql

--changeset model-gen:TC.drop labels:model-1.4.0
--comment: удалён тип узла, таблица tc_revision будет удалена вместе с данными
DROP TABLE tc_revision;
--rollback -- восстановление таблицы с данными невозможно
