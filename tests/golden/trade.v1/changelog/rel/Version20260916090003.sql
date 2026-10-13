--liquibase formatted sql

--changeset model-gen:rel.shipped_by.cardinality labels:model-1.1.0
--comment: to_cardinality: кардинальность ужесточена (0..* -> 0..1)
DELETE FROM rel_signature WHERE rel = 'shipped_by';
-- сигнатура связи shipped_by описана в дескрипторе версии
--rollback -- прежняя сигнатура связи shipped_by восстанавливается предыдущей миграцией
