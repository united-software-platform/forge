--liquibase formatted sql

--changeset model-gen:rel.verified_by.drop labels:model-1.4.0
--comment: удалена связь, её рёбра будут удалены
DELETE FROM link WHERE rel = 'verified_by';
DELETE FROM rel_signature WHERE rel = 'verified_by';
--rollback -- восстановление удалённых рёбер невозможно
