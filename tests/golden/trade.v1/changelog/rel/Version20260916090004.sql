--liquibase formatted sql

--changeset model-gen:rel.supersedes.add labels:model-1.1.0
--comment: добавлена связь
INSERT INTO rel_signature (rel, src_kind, dst_kind, src_min, src_max, dst_min, dst_max, acyclic)
  VALUES ('supersedes', 'ORD', 'ORD', 0, null, 0, null, true);
--rollback DELETE FROM rel_signature WHERE rel = 'supersedes';
