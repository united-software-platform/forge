--liquibase formatted sql

--changeset model-gen:rel.realizes.cardinality labels:model-1.3.0
--comment: to_cardinality: кардинальность ужесточена (0..* -> 0..5)
DELETE FROM rel_signature WHERE rel = 'realizes';
-- сигнатура связи realizes описана в дескрипторе версии
--rollback -- прежняя сигнатура связи realizes восстанавливается предыдущей миграцией
