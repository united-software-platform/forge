--liquibase formatted sql

--changeset model-gen:kind.TC.add labels:model-1.3.0
--comment: тип узла TC добавлен в перечень видов узлов
ALTER TYPE node_kind ADD VALUE IF NOT EXISTS 'TC';
--rollback -- значение перечислимого типа PostgreSQL не удаляется
