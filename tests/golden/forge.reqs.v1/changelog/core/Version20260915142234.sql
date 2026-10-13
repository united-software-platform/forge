--liquibase formatted sql

--changeset model-gen:close.1.2.0 labels:model-1.2.0
--comment: отпечаток модели 1.2.0
INSERT INTO model_state (version, hash) VALUES ('1.2.0', 'sha256:75628d78d447f9b0731f4b1879bbf6e3f88961050eb9eaaece117f72b59031da');
--rollback -- откат версии выполняется откатом миграций этой версии
