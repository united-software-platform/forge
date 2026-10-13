--liquibase formatted sql

--changeset model-gen:rel.realizes.cardinality labels:model-1.4.0
--comment: to_cardinality: кардинальность ослаблена (0..5 -> 0..*)
DELETE FROM rel_signature WHERE rel = 'realizes';
-- сигнатура связи realizes описана в дескрипторе версии
--rollback -- прежняя сигнатура связи realizes восстанавливается предыдущей миграцией
