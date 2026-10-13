--liquibase formatted sql

--changeset model-gen:rel.verified_by.add labels:model-1.3.0
--comment: добавлена связь
INSERT INTO rel_signature (rel, src_kind, dst_kind, src_min, src_max, dst_min, dst_max, acyclic)
  VALUES ('verified_by', 'FR', 'TC', 0, 3, 0, null, false);
--rollback DELETE FROM rel_signature WHERE rel = 'verified_by';
