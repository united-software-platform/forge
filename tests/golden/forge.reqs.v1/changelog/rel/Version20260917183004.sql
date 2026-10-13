--liquibase formatted sql

--changeset model-gen:rel.realizes.to_narrowed labels:model-1.4.0
--comment: to: удалены типы TC
DELETE FROM rel_signature WHERE rel = 'realizes';
INSERT INTO rel_signature (rel, src_kind, dst_kind, src_min, src_max, dst_min, dst_max, acyclic)
  VALUES ('realizes', 'FR', 'BR', 1, null, 0, null, true);
--rollback -- прежняя сигнатура связи realizes восстанавливается предыдущей миграцией
