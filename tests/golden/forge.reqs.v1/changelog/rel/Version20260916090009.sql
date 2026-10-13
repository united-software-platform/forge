--liquibase formatted sql

--changeset model-gen:rel.realizes.to_widened labels:model-1.3.0
--comment: to: добавлены типы TC
DELETE FROM rel_signature WHERE rel = 'realizes';
INSERT INTO rel_signature (rel, src_kind, dst_kind, src_min, src_max, dst_min, dst_max, acyclic)
  VALUES ('realizes', 'FR', 'BR', 1, null, 0, 5, true);
INSERT INTO rel_signature (rel, src_kind, dst_kind, src_min, src_max, dst_min, dst_max, acyclic)
  VALUES ('realizes', 'FR', 'TC', 1, null, 0, 5, true);
--rollback -- прежняя сигнатура связи realizes восстанавливается предыдущей миграцией
