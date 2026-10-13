--liquibase formatted sql

--changeset model-gen:rel.belongs_to.from_widened labels:model-1.1.0
--comment: from: добавлены типы SHIP
DELETE FROM rel_signature WHERE rel = 'belongs_to';
INSERT INTO rel_signature (rel, src_kind, dst_kind, src_min, src_max, dst_min, dst_max, acyclic)
  VALUES ('belongs_to', 'ITEM', 'ORD', 1, 1, 0, null, true);
INSERT INTO rel_signature (rel, src_kind, dst_kind, src_min, src_max, dst_min, dst_max, acyclic)
  VALUES ('belongs_to', 'SHIP', 'ORD', 1, 1, 0, null, true);
--rollback -- прежняя сигнатура связи belongs_to восстанавливается предыдущей миграцией
